"""Automatic shared-expense cost-sharing and monthly settlement engine."""

from __future__ import annotations

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from finops.db.models import Category, Person, Transaction

TWO_PLACES = Decimal("0.01")


def _q(val: Decimal) -> Decimal:
    return val.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_monthly_settlement(db: Session, competence_month: str) -> dict[str, Any]:
    """Compute exact shared-expense settlement between household members for `YYYY-MM`.

    Considers all non-internal-transfer expense transactions (`amount < 0`) with
    `scope == 'shared'`. Respects per-category `custom_split_weights` when defined,
    falling back to `Person.default_split_weight`.
    """
    people = db.query(Person).order_by(Person.id.asc()).all()
    if not people:
        return {
            "month": competence_month,
            "total_shared_expenses": 0.0,
            "members": [],
            "transfers": [],
        }

    default_weights = {p.id: Decimal(str(p.default_split_weight)) for p in people}
    categories_by_id = {c.id: c for c in db.query(Category).all()}

    shared_txs = (
        db.query(Transaction)
        .filter(
            Transaction.competence_month == competence_month,
            Transaction.scope == "shared",
            Transaction.is_internal_transfer.is_(False),
            Transaction.amount < 0,
        )
        .all()
    )

    paid_by: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    target_share: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    total_shared = Decimal("0.00")

    for tx in shared_txs:
        outflow = abs(Decimal(str(tx.amount)))
        total_shared += outflow
        paid_by[tx.paid_by_person_id] += outflow

        weights = default_weights
        if tx.category_id and tx.category_id in categories_by_id:
            cat = categories_by_id[tx.category_id]
            if cat.custom_split_weights:
                weights = {pid: Decimal(str(w)) for pid, w in cat.custom_split_weights.items()}

        for p in people:
            w = weights.get(p.id, Decimal("0.00"))
            target_share[p.id] += outflow * w

    members: list[dict[str, Any]] = []
    creditors: list[tuple[str, str, Decimal]] = []
    debtors: list[tuple[str, str, Decimal]] = []

    for p in people:
        paid = _q(paid_by[p.id])
        share = _q(target_share[p.id])
        net = _q(paid - share)
        members.append(
            {
                "person_id": p.id,
                "display_name": p.display_name,
                "default_weight": float(p.default_split_weight),
                "paid": float(paid),
                "target_share": float(share),
                "net_balance": float(net),
            }
        )
        if net > Decimal("0.00"):
            creditors.append((p.id, p.display_name, net))
        elif net < Decimal("0.00"):
            debtors.append((p.id, p.display_name, abs(net)))

    # Greedy settlement pairing (exact for 2 people and minimal transfers for N people)
    transfers: list[dict[str, Any]] = []
    i = 0
    j = 0
    while i < len(debtors) and j < len(creditors):
        d_id, d_name, d_amt = debtors[i]
        c_id, c_name, c_amt = creditors[j]
        transfer_amt = _q(min(d_amt, c_amt))
        if transfer_amt > Decimal("0.00"):
            transfers.append(
                {
                    "from_person_id": d_id,
                    "from_display_name": d_name,
                    "to_person_id": c_id,
                    "to_display_name": c_name,
                    "amount": float(transfer_amt),
                }
            )
        d_rem = _q(d_amt - transfer_amt)
        c_rem = _q(c_amt - transfer_amt)
        debtors[i] = (d_id, d_name, d_rem)
        creditors[j] = (c_id, c_name, c_rem)
        if d_rem <= Decimal("0.00"):
            i += 1
        if c_rem <= Decimal("0.00"):
            j += 1

    return {
        "month": competence_month,
        "total_shared_expenses": float(_q(total_shared)),
        "transaction_count": len(shared_txs),
        "members": members,
        "transfers": transfers,
    }
