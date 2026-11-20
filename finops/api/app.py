"""FinOps REST API (FastAPI): 24-month spreadsheet, settlement, triage, sync, and webhooks."""

from __future__ import annotations

import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from finops.config.loader import load_and_sync_config
from finops.db.models import (
    AuditLog,
    BankAccount,
    Category,
    PluggyItem,
    PluggySource,
    ProjectionOverride,
    ProjectionRule,
    SyncRun,
    Transaction,
)
from finops.db.session import SessionLocal, get_db
from finops.engines.export import export_matrix_csv, export_matrix_xlsx
from finops.engines.settlement import compute_monthly_settlement
from finops.engines.spreadsheet import (
    compute_spreadsheet_matrix,
    get_cell_breakdown,
    simulate_projection_change,
)
from finops.ingestion.categorizer import draft_yaml_rule_snippet, recategorize_all
from finops.ingestion.demo_seed import seed_demo_data
from finops.ingestion.file_adapter import import_statement_bytes
from finops.ingestion.pluggy_adapter import PluggyApiAdapter
from finops.settings import ROOT_DIR, get_settings


def _resolve_active_config_dir():
    settings = get_settings()
    cfg_dir = settings.resolved_config_dir()
    if cfg_dir.exists() and (cfg_dir / "people.yaml").exists():
        return cfg_dir
    return ROOT_DIR / "config" / "examples"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Sync declarative YAML configs into PostgreSQL on startup
    db = SessionLocal()
    try:
        load_and_sync_config(db, _resolve_active_config_dir())
    finally:
        db.close()
    yield


app = FastAPI(
    title="FinOps API",
    version="0.2.0",
    description="Open-source household FinOps API: 24-month spreadsheet projections, shared-expense settlement, and multi-account Meu Pluggy ingestion.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / Response Schemas
# ---------------------------------------------------------------------------


class OverrideUpsertRequest(BaseModel):
    competence_month: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    category_id: str
    scope: str = Field(pattern=r"^(shared|personal)$")
    owner_person_id: str | None = None
    amount: Decimal = Field(ge=0)
    note: str | None = None


class TransactionPatchRequest(BaseModel):
    category_id: str | None = None
    scope: str | None = Field(default=None, pattern=r"^(shared|personal)$")
    owner_person_id: str | None = None
    is_internal_transfer: bool | None = None


class SimulateRequest(BaseModel):
    description: str
    monthly_amount: Decimal = Field(gt=0)
    start_month: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")
    months_count: int = Field(ge=1, le=24)
    kind: str = Field(default="expense", pattern=r"^(income|expense)$")
    base_year: int | None = None


class RuleDraftRequest(BaseModel):
    pattern: str
    category_id: str
    scope: str = Field(pattern=r"^(shared|personal)$")
    owner_person_id: str | None = None
    priority: int = Field(default=50, ge=1)
    description: str | None = None


class SyncTriggerRequest(BaseModel):
    source_id: str | None = None


class AccountPatchRequest(BaseModel):
    is_emergency_fund: bool


# ---------------------------------------------------------------------------
# Health & Configuration Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    db.execute(text("SELECT 1"))
    return {"status": "ok", "config_dir": str(_resolve_active_config_dir())}


@app.post("/api/config/reload")
def reload_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    cfg_dir = _resolve_active_config_dir()
    bundle = load_and_sync_config(db, cfg_dir)
    recat = recategorize_all(db, bundle)
    return {"status": "reloaded", "config_dir": str(cfg_dir), "recategorization": recat}


@app.post("/api/demo/seed")
def trigger_demo_seed(db: Session = Depends(get_db)) -> dict[str, Any]:
    bundle = load_and_sync_config(db, _resolve_active_config_dir())
    result = seed_demo_data(db, bundle)
    return {"status": "seeded", **result}


# ---------------------------------------------------------------------------
# Pluggy Sync & Health
# ---------------------------------------------------------------------------


@app.get("/api/sync/health")
def get_sync_health(db: Session = Depends(get_db)) -> dict[str, Any]:
    now = datetime.now(UTC)
    sources = db.query(PluggySource).order_by(PluggySource.id.asc()).all()
    items = db.query(PluggyItem).order_by(PluggyItem.source_id.asc()).all()
    accounts = db.query(BankAccount).all()
    recent_runs = db.query(SyncRun).order_by(SyncRun.started_at.desc()).limit(10).all()

    items_out = []
    for item in items:
        days_left: int | None = None
        expiry_warning = False
        if item.consent_expires_at:
            exp = item.consent_expires_at
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=UTC)
            days_left = (exp - now).days
            expiry_warning = days_left <= 30

        items_out.append(
            {
                "item_id": item.id,
                "source_id": item.source_id,
                "label": item.label,
                "connector_name": item.connector_name,
                "status": item.status,
                "execution_status": item.execution_status,
                "consent_expires_at": (item.consent_expires_at.isoformat() if item.consent_expires_at else None),
                "days_until_expiry": days_left,
                "expiry_warning": expiry_warning,
                "last_updated_at": (item.last_updated_at.isoformat() if item.last_updated_at else None),
            }
        )

    return {
        "sources": [
            {
                "id": s.id,
                "person_id": s.person_id,
                "provider_type": s.provider_type,
                "last_synced_at": s.last_synced_at.isoformat() if s.last_synced_at else None,
            }
            for s in sources
        ],
        "items": items_out,
        "accounts": [
            {
                "id": a.id,
                "source_id": a.source_id,
                "person_id": a.person_id,
                "name": a.name,
                "institution_name": a.institution_name,
                "account_type": a.account_type,
                "default_scope": a.default_scope,
                "currency": a.currency,
                "current_balance": float(a.current_balance),
            }
            for a in accounts
        ],
        "recent_runs": [
            {
                "id": r.id,
                "source_id": r.source_id,
                "status": r.status,
                "fetched_count": r.fetched_count,
                "upserted_count": r.upserted_count,
                "error_message": r.error_message,
                "started_at": r.started_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in recent_runs
        ],
    }


@app.post("/api/sync/trigger")
def trigger_sync(
    body: SyncTriggerRequest | None = None,
    x_finops_actor: str = Header(default="user"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    bundle = load_and_sync_config(db, _resolve_active_config_dir())
    adapter = PluggyApiAdapter()
    source_id = body.source_id if body else None
    results = [adapter.sync_source(db, bundle, source_id)] if source_id else adapter.sync_all(db, bundle)

    db.add(
        AuditLog(
            actor=x_finops_actor,
            action="trigger_sync",
            entity_type="pluggy_source",
            entity_id=source_id or "all",
            diff_payload={"results": results},
        )
    )
    db.commit()
    return {"results": results}


# ---------------------------------------------------------------------------
# Spreadsheet Matrix, Cell Drill-Down, Overrides, Export
# ---------------------------------------------------------------------------


@app.get("/api/spreadsheet")
def get_spreadsheet(
    base_year: int | None = Query(default=None, ge=2020, le=2100),
    annual_mode: str = Query(default="cash", pattern=r"^(cash|monthly_provision)$"),
    scope_filter: str = Query(default="all", pattern=r"^(all|shared|personal|annual)$"),
    person_id: str | None = Query(default=None),
    emergency_months: int = Query(default=6, ge=1, le=36),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return compute_spreadsheet_matrix(
        db,
        base_year=base_year,
        annual_mode=annual_mode,
        scope_filter=scope_filter,
        person_id=person_id,
        emergency_months=emergency_months,
    )


@app.patch("/api/accounts/{account_id}")
def patch_account(
    account_id: str,
    payload: AccountPatchRequest,
    x_finops_actor: str = Header(default="user"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    acct = db.get(BankAccount, account_id)
    if acct is None:
        raise HTTPException(status_code=404, detail=f"Account not found: {account_id}")
    prev = bool(acct.is_emergency_fund)
    acct.is_emergency_fund = payload.is_emergency_fund
    acct.updated_at = datetime.now(UTC)
    db.add(
        AuditLog(
            actor=x_finops_actor,
            action="toggle_emergency_fund_account",
            entity_type="bank_account",
            entity_id=acct.id,
            diff_payload={
                "name": acct.name,
                "previous_is_emergency_fund": prev,
                "new_is_emergency_fund": payload.is_emergency_fund,
            },
        )
    )
    db.commit()
    return {
        "id": acct.id,
        "name": acct.name,
        "is_emergency_fund": acct.is_emergency_fund,
    }


@app.get("/api/spreadsheet/cell")
def get_spreadsheet_cell(
    month: str = Query(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"),
    category_id: str = Query(),
    scope: str = Query(pattern=r"^(shared|personal)$"),
    owner_person_id: str | None = Query(default=None),
    annual_mode: str = Query(default="cash", pattern=r"^(cash|monthly_provision)$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return get_cell_breakdown(
        db,
        month=month,
        category_id=category_id,
        scope=scope,
        owner_person_id=owner_person_id,
        annual_mode=annual_mode,
    )


@app.put("/api/spreadsheet/override")
def upsert_override(
    payload: OverrideUpsertRequest,
    x_finops_actor: str = Header(default="user"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if db.get(Category, payload.category_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown category_id: {payload.category_id}")

    owner = None if payload.scope == "shared" else payload.owner_person_id
    if payload.scope == "personal" and not owner:
        raise HTTPException(status_code=400, detail="owner_person_id is required when scope is 'personal'")

    existing = (
        db.query(ProjectionOverride)
        .filter(
            ProjectionOverride.competence_month == payload.competence_month,
            ProjectionOverride.category_id == payload.category_id,
            ProjectionOverride.scope == payload.scope,
            ProjectionOverride.owner_person_id == owner,
        )
        .one_or_none()
    )

    prev_amount = float(existing.amount) if existing else None
    if existing is None:
        existing = ProjectionOverride(
            competence_month=payload.competence_month,
            category_id=payload.category_id,
            scope=payload.scope,
            owner_person_id=owner,
            amount=payload.amount,
            note=payload.note,
            updated_by=x_finops_actor,
        )
        db.add(existing)
        db.flush()
    else:
        existing.amount = payload.amount
        existing.note = payload.note
        existing.updated_by = x_finops_actor
        existing.updated_at = datetime.now(UTC)

    db.add(
        AuditLog(
            actor=x_finops_actor,
            action="set_projection_override",
            entity_type="projection_override",
            entity_id=existing.id,
            diff_payload={
                "competence_month": payload.competence_month,
                "category_id": payload.category_id,
                "scope": payload.scope,
                "owner_person_id": owner,
                "previous_amount": prev_amount,
                "new_amount": float(payload.amount),
                "note": payload.note,
            },
        )
    )
    db.commit()
    return {
        "id": existing.id,
        "competence_month": existing.competence_month,
        "category_id": existing.category_id,
        "scope": existing.scope,
        "owner_person_id": existing.owner_person_id,
        "amount": float(existing.amount),
        "note": existing.note,
        "updated_by": existing.updated_by,
    }


@app.delete("/api/spreadsheet/override")
def delete_override(
    month: str = Query(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$"),
    category_id: str = Query(),
    scope: str = Query(pattern=r"^(shared|personal)$"),
    owner_person_id: str | None = Query(default=None),
    x_finops_actor: str = Header(default="user"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    owner = None if scope == "shared" else owner_person_id
    existing = (
        db.query(ProjectionOverride)
        .filter(
            ProjectionOverride.competence_month == month,
            ProjectionOverride.category_id == category_id,
            ProjectionOverride.scope == scope,
            ProjectionOverride.owner_person_id == owner,
        )
        .one_or_none()
    )
    if existing is None:
        return {"deleted": False}

    ov_id = existing.id
    db.delete(existing)
    db.add(
        AuditLog(
            actor=x_finops_actor,
            action="delete_projection_override",
            entity_type="projection_override",
            entity_id=ov_id,
            diff_payload={"month": month, "category_id": category_id, "scope": scope},
        )
    )
    db.commit()
    return {"deleted": True, "id": ov_id}


@app.get("/api/spreadsheet/export")
def export_spreadsheet(
    fmt: str = Query(default="xlsx", pattern=r"^(csv|xlsx)$"),
    base_year: int | None = Query(default=None),
    annual_mode: str = Query(default="cash", pattern=r"^(cash|monthly_provision)$"),
    db: Session = Depends(get_db),
) -> Response:
    matrix = compute_spreadsheet_matrix(db, base_year=base_year, annual_mode=annual_mode)
    if fmt == "csv":
        data = export_matrix_csv(matrix)
        return Response(
            content=data,
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="finops-{matrix["base_year"]}-{matrix["next_year"]}.csv"'
            },
        )
    data = export_matrix_xlsx(matrix)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="finops-{matrix["base_year"]}-{matrix["next_year"]}.xlsx"'
        },
    )


# ---------------------------------------------------------------------------
# Settlement, Transactions, Categories, Alerts, Simulation, Imports
# ---------------------------------------------------------------------------


@app.get("/api/settlement/{month}")
def get_settlement(month: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return compute_monthly_settlement(db, month)


@app.get("/api/categories")
def list_categories(db: Session = Depends(get_db)) -> dict[str, Any]:
    cats = db.query(Category).order_by(Category.id.asc()).all()
    parents = [c for c in cats if c.parent_id is None]
    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for c in cats:
        if c.parent_id:
            children_by_parent.setdefault(c.parent_id, []).append(
                {
                    "id": c.id,
                    "name": c.name,
                    "kind": c.kind,
                    "default_scope": c.default_scope,
                    "is_annual": c.is_annual,
                    "projection_method": c.projection_method,
                    "monthly_budget_cap": (
                        float(c.monthly_budget_cap) if c.monthly_budget_cap is not None else None
                    ),
                }
            )
    return {
        "categories": [
            {
                "id": p.id,
                "name": p.name,
                "kind": p.kind,
                "default_scope": p.default_scope,
                "subcategories": children_by_parent.get(p.id, []),
            }
            for p in parents
        ]
    }


@app.get("/api/transactions")
def list_transactions(
    month: str | None = Query(default=None),
    category_id: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    person_id: str | None = Query(default=None),
    uncategorized_only: bool = Query(default=False),
    include_transfers: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    q = db.query(Transaction)
    if not include_transfers:
        q = q.filter(Transaction.is_internal_transfer.is_(False))
    if month:
        q = q.filter(Transaction.competence_month == month)
    if category_id:
        q = q.filter(Transaction.category_id == category_id)
    if scope:
        q = q.filter(Transaction.scope == scope)
    if person_id:
        q = q.filter((Transaction.paid_by_person_id == person_id) | (Transaction.owner_person_id == person_id))
    if uncategorized_only:
        q = q.filter(Transaction.category_id.is_(None))

    txs = q.order_by(Transaction.transaction_date.desc()).limit(limit).all()
    return {
        "count": len(txs),
        "transactions": [
            {
                "id": t.id,
                "date": t.transaction_date.isoformat(),
                "competence_month": t.competence_month,
                "description": t.description,
                "amount": float(t.amount),
                "currency": t.currency,
                "category_id": t.category_id,
                "scope": t.scope,
                "paid_by_person_id": t.paid_by_person_id,
                "owner_person_id": t.owner_person_id,
                "is_internal_transfer": t.is_internal_transfer,
                "installment": (
                    f"{t.installment_number}/{t.installment_total}"
                    if t.installment_number and t.installment_total
                    else None
                ),
                "categorization_source": t.categorization_source,
            }
            for t in txs
        ],
    }


@app.patch("/api/transactions/{tx_id}")
def patch_transaction(
    tx_id: str,
    payload: TransactionPatchRequest,
    x_finops_actor: str = Header(default="user"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    tx = db.get(Transaction, tx_id)
    if tx is None:
        raise HTTPException(status_code=404, detail=f"Transaction not found: {tx_id}")

    before = {
        "category_id": tx.category_id,
        "scope": tx.scope,
        "owner_person_id": tx.owner_person_id,
        "is_internal_transfer": tx.is_internal_transfer,
    }

    if payload.category_id is not None:
        if db.get(Category, payload.category_id) is None:
            raise HTTPException(status_code=404, detail=f"Unknown category_id: {payload.category_id}")
        tx.category_id = payload.category_id
    if payload.scope is not None:
        tx.scope = payload.scope
        if payload.scope == "shared":
            tx.owner_person_id = None
        else:
            tx.owner_person_id = payload.owner_person_id or tx.paid_by_person_id
    elif payload.owner_person_id is not None and tx.scope == "personal":
        tx.owner_person_id = payload.owner_person_id

    if payload.is_internal_transfer is not None:
        tx.is_internal_transfer = payload.is_internal_transfer

    tx.categorization_source = "hermes" if x_finops_actor == "hermes" else "manual"
    tx.updated_at = datetime.now(UTC)

    after = {
        "category_id": tx.category_id,
        "scope": tx.scope,
        "owner_person_id": tx.owner_person_id,
        "is_internal_transfer": tx.is_internal_transfer,
    }

    db.add(
        AuditLog(
            actor=x_finops_actor,
            action="categorize_transaction",
            entity_type="transaction",
            entity_id=tx.id,
            diff_payload={"before": before, "after": after},
        )
    )
    db.commit()
    return {"id": tx.id, **after, "categorization_source": tx.categorization_source}


@app.get("/api/annual/upcoming")
def get_upcoming_annual(
    days_ahead: int = Query(default=90, ge=1, le=365),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    today = date.today()
    rules = db.query(ProjectionRule).filter(ProjectionRule.rule_kind == "annual").all()
    upcoming = []
    for r in rules:
        if not r.due_month:
            continue
        due_year = today.year if r.due_month >= today.month else today.year + 1
        due_date = date(due_year, r.due_month, 1)
        delta_days = (due_date - today).days
        if delta_days < 0:
            due_date = date(today.year + 1, r.due_month, 1)
            delta_days = (due_date - today).days
        if delta_days <= days_ahead:
            upcoming.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "category_id": r.category_id,
                    "scope": r.scope,
                    "due_date": due_date.isoformat(),
                    "days_until_due": delta_days,
                    "amount": float(r.amount),
                    "monthly_provision": round(float(r.amount) / 12.0, 2),
                }
            )
    upcoming.sort(key=lambda x: x["days_until_due"])
    return {"days_ahead": days_ahead, "upcoming": upcoming}


@app.get("/api/alerts/budget")
def get_budget_alerts(
    month: str | None = Query(default=None),
    threshold_pct: float = Query(default=80.0, ge=1.0, le=500.0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from finops.engines.alerts import compute_alerts_and_cost_cuts

    target_month = month or date.today().strftime("%Y-%m")
    matrix = compute_spreadsheet_matrix(db, base_year=int(target_month[:4]))
    data = compute_alerts_and_cost_cuts(db, matrix, target_month)
    data["threshold_pct"] = threshold_pct
    return data


@app.post("/api/simulate")
def run_simulation(payload: SimulateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return simulate_projection_change(
        db,
        description=payload.description,
        monthly_amount=payload.monthly_amount,
        start_month=payload.start_month,
        months_count=payload.months_count,
        kind=payload.kind,
        base_year=payload.base_year,
    )


@app.post("/api/rules/draft")
def draft_rule(payload: RuleDraftRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    if db.get(Category, payload.category_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown category_id: {payload.category_id}")
    try:
        snippet = draft_yaml_rule_snippet(
            pattern=payload.pattern,
            category_id=payload.category_id,
            scope=payload.scope,
            owner_person_id=payload.owner_person_id,
            priority=payload.priority,
            description=payload.description,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid regex: {exc}") from exc
    return {"yaml_entry": snippet}


@app.post("/api/imports/upload")
async def upload_statement(
    file: UploadFile = File(...),
    person_id: str = Form(...),
    account_name: str = Form(default="Manual Import"),
    default_scope: str = Form(default="personal"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    content = await file.read()
    bundle = load_and_sync_config(db, _resolve_active_config_dir())
    try:
        res = import_statement_bytes(
            db=db,
            bundle=bundle,
            filename=file.filename or "statement.csv",
            content=content,
            person_id=person_id,
            account_name=account_name,
            default_scope=default_scope,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "imported", **res}


@app.post("/webhooks/pluggy/{source_id}")
async def pluggy_webhook(
    source_id: str,
    request: Request,
    x_pluggy_signature: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Optional HMAC-SHA256 verified webhook endpoint (not required for local polling)."""
    source = db.get(PluggySource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Unknown source")

    secret_env = f"{(source.client_id_env or '').replace('_CLIENT_ID', '')}_CLIENT_WEBHOOK_SIGN_SECRET"
    secret = os.getenv(secret_env, "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail=f"Webhook signing secret {secret_env} is not configured.",
        )

    raw_body = await request.body()
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = (x_pluggy_signature or "").removeprefix("sha256=").strip()
    if not provided or not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    bundle = load_and_sync_config(db, _resolve_active_config_dir())
    result = PluggyApiAdapter().sync_source(db, bundle, source_id)
    return {"status": "accepted", "sync": result}
