"""Fallback CSV and OFX bank statement ingestion adapter."""

from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from finops.config.loader import LoadedConfig
from finops.db.models import BankAccount, Category, PluggySource, Transaction
from finops.ingestion.categorizer import (
    apply_rules_to_transaction,
    detect_inter_account_transfers,
)
from finops.ingestion.fingerprints import build_dedup_fingerprint, parse_installment

_DATE_HEADERS = ("date", "data", "dt", "transaction_date", "data_lancamento")
_DESC_HEADERS = ("description", "descricao", "descrição", "memo", "title", "historico", "histórico")
_AMOUNT_HEADERS = ("amount", "valor", "value", "quantia")

_OFX_BLOCK_RE = re.compile(r"<STMTTRN>(.*?)</STMTTRN>", re.DOTALL | re.IGNORECASE)
_OFX_TAG_RE = re.compile(r"<([A-Z0-9_]+)>([^<\r\n]+)", re.IGNORECASE)


def _parse_flexible_date(raw: str) -> date:
    cleaned = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%Y%m%d"):
        try:
            return datetime.strptime(cleaned[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {raw!r}")


def _parse_flexible_amount(raw: str) -> Decimal:
    cleaned = raw.strip().replace("R$", "").replace(" ", "")
    # Handle Brazilian format `1.234,56`
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError(f"Unrecognized amount format: {raw!r}") from exc


def parse_csv_bytes(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig", errors="replace")
    sample = text[:2048]
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        return []

    header_map = {h.strip().lower(): h for h in reader.fieldnames if h}
    date_col = next((header_map[k] for k in _DATE_HEADERS if k in header_map), None)
    desc_col = next((header_map[k] for k in _DESC_HEADERS if k in header_map), None)
    amt_col = next((header_map[k] for k in _AMOUNT_HEADERS if k in header_map), None)
    if not (date_col and desc_col and amt_col):
        raise ValueError(f"CSV must contain date, description, and amount columns. Found: {reader.fieldnames}")

    rows: list[dict[str, Any]] = []
    for row in reader:
        raw_date = (row.get(date_col) or "").strip()
        raw_desc = (row.get(desc_col) or "").strip()
        raw_amt = (row.get(amt_col) or "").strip()
        if not raw_date or not raw_amt:
            continue
        rows.append(
            {
                "date": _parse_flexible_date(raw_date),
                "description": raw_desc or "Imported transaction",
                "amount": _parse_flexible_amount(raw_amt),
                "external_id": None,
            }
        )
    return rows


def parse_ofx_bytes(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    for block in _OFX_BLOCK_RE.findall(text):
        tags = {k.upper(): v.strip() for k, v in _OFX_TAG_RE.findall(block)}
        dt_raw = tags.get("DTPOSTED", "")[:8]
        amt_raw = tags.get("TRNAMT", "")
        desc = tags.get("MEMO") or tags.get("NAME") or "OFX Transaction"
        if not dt_raw or not amt_raw:
            continue
        rows.append(
            {
                "date": _parse_flexible_date(dt_raw),
                "description": desc,
                "amount": _parse_flexible_amount(amt_raw),
                "external_id": tags.get("FITID"),
            }
        )
    return rows


def import_statement_bytes(
    *,
    db: Session,
    bundle: LoadedConfig,
    filename: str,
    content: bytes,
    person_id: str,
    account_name: str = "Manual Import",
    default_scope: str = "personal",
) -> dict[str, int]:
    """Import a CSV or OFX file into PostgreSQL with full deduplication and categorization."""
    lower = filename.lower()
    if lower.endswith(".ofx") or lower.endswith(".qfx"):
        parsed = parse_ofx_bytes(content)
    elif lower.endswith(".csv"):
        parsed = parse_csv_bytes(content)
    else:
        raise ValueError("Unsupported file extension. Please upload a .csv or .ofx file.")

    source_id = f"file_import_{person_id}"
    source = db.get(PluggySource, source_id)
    if source is None:
        source = PluggySource(
            id=source_id,
            person_id=person_id,
            provider_type="file_import",
            default_scope=default_scope,
        )
        db.add(source)
        db.flush()

    ext_acct_id = f"file:{person_id}:{account_name.lower()}"
    account = (
        db.query(BankAccount)
        .filter(
            BankAccount.source_id == source_id,
            BankAccount.external_account_id == ext_acct_id,
        )
        .one_or_none()
    )
    if account is None:
        account = BankAccount(
            source_id=source_id,
            external_account_id=ext_acct_id,
            person_id=person_id,
            default_scope=default_scope,
            account_type="BANK",
            institution_name="Manual Import",
            name=account_name,
            currency=bundle.currency,
        )
        db.add(account)
        db.flush()

    categories_by_id = {c.id: c for c in db.query(Category).all()}
    occurrence_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    inserted = 0
    skipped = 0

    for item in parsed:
        tx_date: date = item["date"]
        amount: Decimal = item["amount"]
        description: str = item["description"]

        occ_key = (tx_date.isoformat(), f"{amount:.2f}", description.lower())
        occ = occurrence_counts[occ_key]
        occurrence_counts[occ_key] += 1

        fp = build_dedup_fingerprint(
            person_id=person_id,
            account_key=f"IMPORT:{account_name}",
            tx_date=tx_date,
            amount=amount,
            description=description,
            occurrence=occ,
        )
        exists = db.query(Transaction).filter(Transaction.dedup_fingerprint == fp).one_or_none()
        if exists is not None:
            skipped += 1
            continue

        group_id, inst_num, inst_total = parse_installment(description)
        tx = Transaction(
            account_id=account.id,
            external_transaction_id=item.get("external_id"),
            dedup_fingerprint=fp,
            transaction_date=tx_date,
            competence_month=tx_date.strftime("%Y-%m"),
            amount=amount,
            currency=bundle.currency,
            description=description,
            scope=default_scope,
            paid_by_person_id=person_id,
            owner_person_id=None if default_scope == "shared" else person_id,
            installment_group_id=group_id,
            installment_number=inst_num,
            installment_total=inst_total,
        )
        apply_rules_to_transaction(tx, bundle, categories_by_id)
        db.add(tx)
        inserted += 1

    detect_inter_account_transfers(db, bundle)
    source.last_synced_at = datetime.now(UTC)
    db.commit()
    return {"parsed": len(parsed), "inserted": inserted, "skipped_duplicates": skipped}
