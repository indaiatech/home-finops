"""Synthetic 2-person household seed data for open-source demos and local testing."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from finops.config.loader import LoadedConfig, load_and_sync_config
from finops.db.models import BankAccount, Category, PluggyItem, PluggySource, Transaction
from finops.ingestion.categorizer import (
    apply_rules_to_transaction,
    detect_inter_account_transfers,
)
from finops.ingestion.fingerprints import build_dedup_fingerprint, parse_installment


def _month_date(year: int, month: int, day: int) -> date:
    safe_day = min(day, 28)
    return date(year, month, safe_day)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + delta
    return total // 12, (total % 12) + 1


def seed_demo_data(db: Session, bundle: LoadedConfig | None = None, today: date | None = None) -> dict[str, int]:
    """Populate realistic synthetic transactions across 2 people without touching real bank APIs."""
    ref_today = today or date.today()
    if bundle is None:
        from finops.settings import ROOT_DIR

        bundle = load_and_sync_config(db, ROOT_DIR / "config" / "examples")

    # Mark demo Pluggy items with healthy status + 1-year expiry
    for item in db.query(PluggyItem).all():
        item.connector_name = "MeuPluggy (Demo)"
        item.status = "UPDATED"
        item.execution_status = "SUCCESS"
        item.consent_expires_at = datetime.now(UTC) + timedelta(days=340)
        item.last_updated_at = datetime.now(UTC)

    # Create demo bank accounts & credit cards for person_a and person_b
    people_ids = [p["id"] for p in bundle.people]
    person_a = people_ids[0]
    person_b = people_ids[1] if len(people_ids) > 1 else person_a

    sources_by_person = {s.person_id: s.id for s in db.query(PluggySource).all()}
    src_a = sources_by_person.get(person_a, next(iter(sources_by_person.values())))
    src_b = sources_by_person.get(person_b, src_a)

    def ensure_account(
        source_id: str,
        ext_id: str,
        person_id: str,
        scope: str,
        acct_type: str,
        name: str,
        balance: Decimal,
    ) -> BankAccount:
        acct = (
            db.query(BankAccount)
            .filter(
                BankAccount.source_id == source_id,
                BankAccount.external_account_id == ext_id,
            )
            .one_or_none()
        )
        if acct is None:
            acct = BankAccount(
                source_id=source_id,
                external_account_id=ext_id,
                person_id=person_id,
                default_scope=scope,
                account_type=acct_type,
                institution_name="Demo Bank",
                name=name,
                currency=bundle.currency,
                current_balance=balance,
            )
            db.add(acct)
            db.flush()
        return acct

    acct_a_bank = ensure_account(
        src_a, "demo-bank-a", person_a, "personal", "BANK", "Checking A", Decimal("14500.00")
    )
    acct_a_card = ensure_account(
        src_a, "demo-card-a", person_a, "shared", "CREDIT", "Household Card A", Decimal("-2400.00")
    )
    acct_b_bank = ensure_account(
        src_b, "demo-bank-b", person_b, "personal", "BANK", "Checking B", Decimal("11200.00")
    )
    acct_b_card = ensure_account(
        src_b, "demo-card-b", person_b, "personal", "CREDIT", "Personal Card B", Decimal("-1150.00")
    )

    categories_by_id = {c.id: c for c in db.query(Category).all()}
    inserted = 0

    def add_tx(
        acct: BankAccount,
        tx_date: date,
        amount: Decimal,
        desc: str,
        category_id: str | None = None,
        scope: str | None = None,
        owner: str | None = None,
        source_tag: str = "yaml_rule",
    ) -> None:
        nonlocal inserted
        fp = build_dedup_fingerprint(
            person_id=acct.person_id,
            account_key=f"DEMO:{acct.name}",
            tx_date=tx_date,
            amount=amount,
            description=desc,
        )
        if db.query(Transaction).filter(Transaction.dedup_fingerprint == fp).one_or_none():
            return

        group_id, inst_num, inst_total = parse_installment(desc)
        resolved_scope = scope or acct.default_scope
        resolved_owner = None if resolved_scope == "shared" else (owner or acct.person_id)

        tx = Transaction(
            account_id=acct.id,
            dedup_fingerprint=fp,
            transaction_date=tx_date,
            competence_month=tx_date.strftime("%Y-%m"),
            amount=amount,
            currency=bundle.currency,
            description=desc,
            category_id=category_id,
            scope=resolved_scope,
            paid_by_person_id=acct.person_id,
            owner_person_id=resolved_owner,
            installment_group_id=group_id,
            installment_number=inst_num,
            installment_total=inst_total,
            categorization_source=source_tag if category_id else "uncategorized",
        )
        if category_id is None:
            apply_rules_to_transaction(tx, bundle, categories_by_id)
        db.add(tx)
        inserted += 1

    # Generate 6 months of realistic history up to the current month
    for offset in range(-5, 1):
        y, m = _shift_month(ref_today.year, ref_today.month, offset)
        # Salaries
        add_tx(
            acct_a_bank,
            _month_date(y, m, 5),
            Decimal("9500.00"),
            "Monthly Salary Deposit",
            "income.salary",
            "personal",
            person_a,
        )
        add_tx(
            acct_b_bank,
            _month_date(y, m, 5),
            Decimal("8500.00"),
            "Monthly Salary Deposit",
            "income.salary",
            "personal",
            person_b,
        )

        # Shared fixed & variable expenses (split across Person A and Person B to demonstrate settlement!)
        add_tx(
            acct_a_bank,
            _month_date(y, m, 7),
            Decimal("-3400.00"),
            "Apartment Rent & Condo",
            "housing.rent",
            "shared",
        )
        add_tx(
            acct_b_bank,
            _month_date(y, m, 10),
            Decimal("-149.90"),
            "Home Fiber Internet",
            "housing.internet",
            "shared",
        )
        add_tx(
            acct_b_bank,
            _month_date(y, m, 12),
            Decimal(f"-{310 + (m % 4) * 25}.00"),
            "Power & Water Utilities",
            "housing.utilities",
            "shared",
        )

        # Groceries & dining (rules match Carrefour / iFood automatically)
        add_tx(acct_a_card, _month_date(y, m, 8), Decimal(f"-{920 + (m % 3) * 75}.40"), "CARREFOUR SUPERMARKET")
        add_tx(acct_b_card, _month_date(y, m, 18), Decimal(f"-{780 + (m % 2) * 90}.20"), "PAO DE ACUCAR GROCERY")
        add_tx(acct_a_card, _month_date(y, m, 14), Decimal(f"-{280 + (m % 3) * 45}.00"), "IFOOD *DELIVERY")
        add_tx(acct_b_card, _month_date(y, m, 22), Decimal(f"-{220 + (m % 2) * 35}.50"), "RESTAURANT BISTRO")

        # Personal expenses
        add_tx(
            acct_a_card,
            _month_date(y, m, 9),
            Decimal("-169.90"),
            "SMARTFIT GYM",
            "personal.health_fitness",
            "personal",
            person_a,
        )
        add_tx(
            acct_b_card,
            _month_date(y, m, 9),
            Decimal("-169.90"),
            "WELLHUB GYM",
            "personal.health_fitness",
            "personal",
            person_b,
        )
        add_tx(
            acct_a_card,
            _month_date(y, m, 16),
            Decimal("-145.00"),
            "UBER *TRIP",
            "transport.fuel_ridehail",
            "personal",
            person_a,
        )
        add_tx(
            acct_b_card,
            _month_date(y, m, 20),
            Decimal("-340.00"),
            "BOOKSTORE & HOBBIES",
            "personal.leisure",
            "personal",
            person_b,
        )

        # Active credit-card installment spanning into future months!
        inst_num = offset + 6  # 1..6 out of 10 -> projects installments 7..10 into future months!
        add_tx(
            acct_a_card,
            _month_date(y, m, 15),
            Decimal("-420.00"),
            f"HOME APPLIANCE STORE PARC {inst_num}/10",
            "housing.utilities",
            "shared",
        )

        # Simulated credit card bill payment (must be detected as internal transfer!)
        add_tx(acct_a_bank, _month_date(y, m, 25), Decimal("-2100.00"), "PAGAMENTO DE FATURA CARTAO")

    # Add 2 uncategorized transactions in the current month for triage UI & Hermes demo
    add_tx(
        acct_a_card,
        _month_date(ref_today.year, ref_today.month, min(ref_today.day, 24)),
        Decimal("-189.50"),
        "LOCAL NEIGHBORHOOD MARKET XYZ",
        category_id=None,
        scope="shared",
    )
    add_tx(
        acct_b_card,
        _month_date(ref_today.year, ref_today.month, min(ref_today.day, 24)),
        Decimal("-275.00"),
        "SPECIALTY COFFEE ROASTERS",
        category_id=None,
        scope="personal",
    )

    detect_inter_account_transfers(db, bundle)
    db.commit()
    return {"inserted": inserted}
