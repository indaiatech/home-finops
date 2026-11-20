"""Unit and integration tests for FinOps ingestion, projection, settlement, and API."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from finops.api.app import app
from finops.config.loader import load_and_sync_config
from finops.db.models import Base, ProjectionOverride
from finops.db.session import get_db
from finops.engines.export import export_matrix_csv, export_matrix_xlsx
from finops.engines.settlement import compute_monthly_settlement
from finops.engines.spreadsheet import (
    compute_spreadsheet_matrix,
    get_cell_breakdown,
    simulate_projection_change,
)
from finops.ingestion.demo_seed import seed_demo_data
from finops.ingestion.file_adapter import import_statement_bytes
from finops.ingestion.fingerprints import build_dedup_fingerprint, parse_installment
from finops.ingestion.pluggy_adapter import normalize_pluggy_amount

ROOT_DIR = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = ROOT_DIR / "config" / "examples"


def _make_memory_db() -> Session:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return factory()


def test_normalize_pluggy_amount_handles_checking_and_credit_cards() -> None:
    assert normalize_pluggy_amount(120.5, "DEBIT", "CREDIT") == Decimal("-120.50")
    assert normalize_pluggy_amount(-120.5, "DEBIT", "BANK") == Decimal("-120.50")
    assert normalize_pluggy_amount(-500.0, "CREDIT", "CREDIT") == Decimal("500.00")
    assert normalize_pluggy_amount(9500.0, "CREDIT", "BANK") == Decimal("9500.00")


def test_installment_parser_handles_metadata_and_descriptions() -> None:
    gid1, n1, t1 = parse_installment("LOJA ABC PARC 3/10")
    gid2, n2, t2 = parse_installment("LOJA ABC PARC 4/10")
    assert (n1, t1) == (3, 10)
    assert (n2, t2) == (4, 10)
    assert gid1 == gid2 and gid1 is not None

    gid3, n3, t3 = parse_installment("ELETRONICOS", {"installmentNumber": 2, "totalInstallments": 6})
    assert (n3, t3) == (2, 6)
    assert gid3 is not None


def test_dedup_fingerprint_is_item_id_independent() -> None:
    fp1 = build_dedup_fingerprint(
        person_id="person_a",
        account_key="CREDIT:Card A",
        tx_date=date(2026, 11, 10),
        amount=Decimal("-99.90"),
        description="  CARREFOUR   SUPERMARKET ",
    )
    fp2 = build_dedup_fingerprint(
        person_id="person_a",
        account_key="credit:card a",
        tx_date=date(2026, 11, 10),
        amount=Decimal("-99.90"),
        description="carrefour supermarket",
    )
    assert fp1 == fp2


def test_spreadsheet_24m_annual_modes_installments_and_overrides() -> None:
    db = _make_memory_db()
    bundle = load_and_sync_config(db, EXAMPLES_DIR)
    ref_today = date(2026, 11, 19)
    seed_demo_data(db, bundle, today=ref_today)

    # Cash view: IPVA (3600) appears in January only
    cash_matrix = compute_spreadsheet_matrix(db, base_year=2026, annual_mode="cash", today=ref_today)
    assert len(cash_matrix["months"]) == 24
    assert cash_matrix["months"][0] == "2026-01"
    assert cash_matrix["months"][-1] == "2027-12"

    ipva_row = next(r for r in cash_matrix["rows"] if r["category_id"] == "transport.vehicle_tax")
    assert ipva_row["cells"]["2027-01"]["value"] == 3600.0
    assert ipva_row["cells"]["2027-02"]["value"] == 0.0

    # Monthly provision view: IPVA smoothed to 300/month
    prov_matrix = compute_spreadsheet_matrix(db, base_year=2026, annual_mode="monthly_provision", today=ref_today)
    ipva_prov = next(r for r in prov_matrix["rows"] if r["category_id"] == "transport.vehicle_tax")
    assert ipva_prov["cells"]["2027-02"]["value"] == 300.0

    # Future installment projection: 6/10 in 2026-11 -> projects 420.00 into 2026-12..2027-03
    util_row = next(r for r in cash_matrix["rows"] if r["category_id"] == "housing.utilities")
    assert util_row["cells"]["2026-12"]["installments"] == 420.0
    assert util_row["cells"]["2027-03"]["installments"] == 420.0
    assert util_row["cells"]["2027-04"]["installments"] == 0.0

    # Manual override takes highest precedence
    db.add(
        ProjectionOverride(
            competence_month="2027-05",
            category_id="food.groceries",
            scope="shared",
            owner_person_id=None,
            amount=Decimal("2500.00"),
            note="Hosting family dinner",
            updated_by="hermes",
        )
    )
    db.commit()

    updated = compute_spreadsheet_matrix(db, base_year=2026, today=ref_today)
    groc_row = next(r for r in updated["rows"] if r["category_id"] == "food.groceries")
    assert groc_row["cells"]["2027-05"]["value"] == 2500.0
    assert groc_row["cells"]["2027-05"]["source"] == "override"
    assert groc_row["cells"]["2027-05"]["note"] == "Hosting family dinner"

    # Cell breakdown & simulation & exports
    cell_info = get_cell_breakdown(db, month="2026-11", category_id="food.groceries", scope="shared")
    assert len(cell_info["transactions"]) >= 1

    sim = simulate_projection_change(
        db,
        description="New car financing",
        monthly_amount=Decimal("1500.00"),
        start_month="2027-01",
        months_count=12,
        base_year=2026,
    )
    assert sim["total_horizon_impact"] == -18000.0

    csv_bytes = export_matrix_csv(updated)
    assert b"2026-01" in csv_bytes and b"2027-12" in csv_bytes
    xlsx_bytes = export_matrix_xlsx(updated)
    assert xlsx_bytes[:2] == b"PK"  # valid ZIP/XLSX container


def test_monthly_settlement_engine() -> None:
    db = _make_memory_db()
    bundle = load_and_sync_config(db, EXAMPLES_DIR)
    seed_demo_data(db, bundle, today=date(2026, 11, 19))

    settlement = compute_monthly_settlement(db, "2026-11")
    assert settlement["total_shared_expenses"] > 0
    assert len(settlement["members"]) == 2
    assert len(settlement["transfers"]) == 1
    transfer = settlement["transfers"][0]
    # Person A paid rent (3400) + appliance + groceries, so Person B owes Person A
    assert transfer["from_person_id"] == "person_b"
    assert transfer["to_person_id"] == "person_a"
    assert transfer["amount"] > 0


def test_csv_and_ofx_fallback_importers() -> None:
    db = _make_memory_db()
    bundle = load_and_sync_config(db, EXAMPLES_DIR)

    csv_data = b"date,description,amount\n2026-10-05,CARREFOUR SUPERMARKET,-450.25\n"
    res_csv = import_statement_bytes(
        db=db,
        bundle=bundle,
        filename="oct.csv",
        content=csv_data,
        person_id="person_a",
    )
    assert res_csv["inserted"] == 1

    # Re-importing the exact same CSV must skip duplicates
    res_dup = import_statement_bytes(
        db=db,
        bundle=bundle,
        filename="oct.csv",
        content=csv_data,
        person_id="person_a",
    )
    assert res_dup["inserted"] == 0
    assert res_dup["skipped_duplicates"] == 1

    ofx_data = b"<OFX><STMTTRN><DTPOSTED>20261012<TRNAMT>-89.90<FITID>12345<MEMO>IFOOD DELIVERY</STMTTRN></OFX>"
    res_ofx = import_statement_bytes(
        db=db,
        bundle=bundle,
        filename="oct.ofx",
        content=ofx_data,
        person_id="person_b",
    )
    assert res_ofx["inserted"] == 1


def test_fastapi_endpoints_end_to_end() -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    seed_db = factory()
    bundle = load_and_sync_config(seed_db, EXAMPLES_DIR)
    seed_demo_data(seed_db, bundle, today=date(2026, 11, 19))
    seed_db.close()

    def override_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        assert client.get("/health").status_code == 200
        sheet = client.get("/api/spreadsheet?base_year=2026")
        assert sheet.status_code == 200
        assert len(sheet.json()["months"]) == 24

        txs = client.get("/api/transactions?uncategorized_only=true").json()
        assert txs["count"] >= 2
        tx_id = txs["transactions"][0]["id"]

        patched = client.patch(
            f"/api/transactions/{tx_id}",
            json={"category_id": "food.groceries", "scope": "shared"},
            headers={"X-FinOps-Actor": "hermes"},
        )
        assert patched.status_code == 200
        assert patched.json()["categorization_source"] == "hermes"

        ov = client.put(
            "/api/spreadsheet/override",
            json={
                "competence_month": "2027-06",
                "category_id": "food.groceries",
                "scope": "shared",
                "amount": 1900.0,
                "note": "Adjusted via test",
            },
            headers={"X-FinOps-Actor": "hermes"},
        )
        assert ov.status_code == 200
        assert ov.json()["updated_by"] == "hermes"
    finally:
        app.dependency_overrides.clear()
