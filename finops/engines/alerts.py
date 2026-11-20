"""Threshold alarms and Where-to-Cut-Costs optimization engine."""

from __future__ import annotations

import re
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from finops.db.models import Category, Transaction

TWO_PLACES = Decimal("0.01")
_INSTALLMENT_SUFFIX_RE = re.compile(r"\s+\d{1,2}/\d{1,2}.*$")


def _q(val: Decimal) -> Decimal:
    return val.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _clean_merchant(desc: str) -> str:
    cleaned = _INSTALLMENT_SUFFIX_RE.sub("", desc.strip())
    return cleaned[:48]


def compute_alerts_and_cost_cuts(
    db: Session,
    matrix: dict[str, Any],
    target_month: str | None = None,
) -> dict[str, Any]:
    """Compute threshold alarms for `target_month` and ranked cost-cutting opportunities."""
    month = target_month or matrix["current_month"]
    base_year = int(matrix["base_year"])
    year_prefix = f"{base_year}-"

    categories_by_id = {c.id: c for c in db.query(Category).all()}

    # Load all non-transfer expense transactions in base_year up to max(month, current_month)
    upper_month = max(month, matrix["current_month"])
    year_txs = (
        db.query(Transaction)
        .filter(
            Transaction.is_internal_transfer.is_(False),
            Transaction.amount < 0,
            Transaction.competence_month >= f"{base_year}-01",
            Transaction.competence_month <= upper_month,
        )
        .all()
    )

    # Index transactions by (category_id, month) and (category_id) across the year
    month_merchants: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal("0.00")))
    year_cat_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    year_cat_months: dict[str, set[str]] = defaultdict(set)
    year_cat_merchants: dict[str, dict[str, list[Any]]] = defaultdict(
        lambda: defaultdict(lambda: [Decimal("0.00"), 0])
    )
    active_year_months: set[str] = set()

    for tx in year_txs:
        amt = abs(Decimal(str(tx.amount)))
        if tx.competence_month.startswith(year_prefix) and tx.competence_month <= matrix["current_month"]:
            active_year_months.add(tx.competence_month)
        if not tx.category_id:
            continue

        m_name = _clean_merchant(tx.description)
        if tx.competence_month == month:
            month_merchants[tx.category_id][m_name] += amt

        if tx.competence_month.startswith(year_prefix) and tx.competence_month <= matrix["current_month"]:
            year_cat_totals[tx.category_id] += amt
            year_cat_months[tx.category_id].add(tx.competence_month)
            entry = year_cat_merchants[tx.category_id][m_name]
            entry[0] += amt
            entry[1] += 1

    elapsed_months_count = max(1, len(active_year_months))

    # 1. Threshold Alarms for `month`
    alarms: list[dict[str, Any]] = []
    for row in matrix["rows"]:
        if row["kind"] != "expense" or row["category_id"] == "uncategorized":
            continue
        cell = row["cells"].get(month)
        if not cell:
            continue

        cat = categories_by_id.get(row["category_id"])
        cap = (
            Decimal(str(cat.monthly_budget_cap))
            if cat and cat.monthly_budget_cap is not None and cat.monthly_budget_cap > 0
            else None
        )
        warn_pct = float(cat.warning_threshold_pct) if cat else 80.0

        # Fallback dynamic baseline: historical monthly avg in base_year (for non-annual categories)
        hist_avg = _q(year_cat_totals.get(row["category_id"], Decimal("0.00")) / Decimal(elapsed_months_count))
        if cap is not None:
            threshold = _q(cap)
            threshold_source = "yaml_threshold"
        elif not row["is_annual"] and hist_avg > Decimal("150.00"):
            threshold = hist_avg
            threshold_source = "historical_avg"
            warn_pct = 110.0  # Warn if 10%+ above historical avg
        else:
            continue

        if threshold <= Decimal("0.00"):
            continue

        realized = Decimal(str(cell["realized"]))
        displayed = Decimal(str(cell["value"]))
        eval_amount = realized if month < matrix["current_month"] else max(realized, displayed)
        if eval_amount <= Decimal("0.00"):
            continue

        util_pct = float(_q((eval_amount / threshold) * Decimal("100")))
        crit_cutoff = 100.0 if threshold_source == "yaml_threshold" else 125.0

        if util_pct >= crit_cutoff:
            severity = "critical"
        elif util_pct >= warn_pct:
            severity = "warning"
        else:
            continue

        top_m = sorted(
            month_merchants.get(row["category_id"], {}).items(),
            key=lambda kv: kv[1],
            reverse=True,
        )[:3]

        alarms.append(
            {
                "row_id": row["row_id"],
                "month": month,
                "severity": severity,
                "category_id": row["category_id"],
                "category_name": row["category_name"],
                "parent_category_name": row["parent_category_name"],
                "scope": row["scope"],
                "owner_person_id": row["owner_person_id"],
                "owner_display_name": row["owner_display_name"],
                "realized": float(_q(realized)),
                "projected": float(_q(displayed)),
                "evaluated_amount": float(_q(eval_amount)),
                "threshold": float(threshold),
                "threshold_source": threshold_source,
                "warning_threshold_pct": warn_pct,
                "utilization_pct": util_pct,
                "overage": float(_q(max(Decimal("0.00"), eval_amount - threshold))),
                "top_merchants": [{"name": name, "amount": float(_q(val))} for name, val in top_m],
            }
        )

    alarms.sort(
        key=lambda a: (0 if a["severity"] == "critical" else 1, -a["utilization_pct"], -a["evaluated_amount"])
    )

    # 2. Where to Cut Costs (Discretionary & High-Spend Categories)
    opportunities: list[dict[str, Any]] = []
    total_monthly_savings = Decimal("0.00")

    for cat_id, total_yr in year_cat_totals.items():
        cat = categories_by_id.get(cat_id)
        if not cat or cat.kind != "expense" or cat.is_annual:
            continue

        avg_mo = _q(total_yr / Decimal(elapsed_months_count))
        if avg_mo < Decimal("80.00"):
            continue

        cap = (
            Decimal(str(cat.monthly_budget_cap))
            if cat.monthly_budget_cap is not None and cat.monthly_budget_cap > 0
            else None
        )
        is_disc = bool(cat.is_discretionary)
        over_cap = cap is not None and avg_mo > cap

        if not is_disc and not over_cap:
            continue

        cut_pct = Decimal(str(cat.cut_target_pct)) if is_disc else Decimal("15.00")
        if over_cap and cap is not None:
            # Target bringing spend down to cap or applying cut_pct, whichever saves more
            target_by_pct = _q(avg_mo * (Decimal("100") - cut_pct) / Decimal("100"))
            suggested_cap = min(cap, target_by_pct) if is_disc else _q(cap)
        else:
            suggested_cap = _q(avg_mo * (Decimal("100") - cut_pct) / Decimal("100"))

        monthly_save = _q(max(Decimal("0.00"), avg_mo - suggested_cap))
        if monthly_save <= Decimal("0.00"):
            continue

        annual_save = _q(monthly_save * Decimal("12"))
        total_monthly_savings += monthly_save

        top_year_merchants = sorted(
            year_cat_merchants[cat_id].items(),
            key=lambda kv: kv[1][0],
            reverse=True,
        )[:4]

        parent = categories_by_id.get(cat.parent_id or "")
        effective_cut_pct = float(_q((monthly_save / avg_mo) * Decimal("100")))

        opportunities.append(
            {
                "category_id": cat_id,
                "category_name": cat.name,
                "parent_category_name": parent.name if parent else cat.name,
                "is_discretionary": is_disc,
                "over_threshold": over_cap,
                "configured_threshold": float(_q(cap)) if cap is not None else None,
                "current_monthly_avg": float(avg_mo),
                "total_ytd": float(_q(total_yr)),
                "cut_target_pct": effective_cut_pct,
                "suggested_monthly_cap": float(suggested_cap),
                "potential_monthly_savings": float(monthly_save),
                "potential_annual_savings": float(annual_save),
                "top_merchants": [
                    {
                        "name": m_name,
                        "total_ytd": float(_q(vals[0])),
                        "monthly_avg": float(_q(vals[0] / Decimal(elapsed_months_count))),
                        "tx_count": int(vals[1]),
                    }
                    for m_name, vals in top_year_merchants
                ],
            }
        )

    opportunities.sort(key=lambda o: o["potential_annual_savings"], reverse=True)

    # 3. Recurring Subscriptions & Micro-Drains Audit
    sub_drains: list[dict[str, Any]] = []
    for cat_id in ("subscriptions.streaming_digital", "personal.education"):
        for m_name, vals in year_cat_merchants.get(cat_id, {}).items():
            total_amt, cnt = vals[0], int(vals[1])
            if cnt >= 3:
                mo_cost = _q(total_amt / Decimal(elapsed_months_count))
                sub_drains.append(
                    {
                        "merchant": m_name,
                        "charges_count": cnt,
                        "monthly_avg": float(mo_cost),
                        "annualized_cost": float(_q(mo_cost * Decimal("12"))),
                        "total_ytd": float(_q(total_amt)),
                    }
                )
    sub_drains.sort(key=lambda s: s["annualized_cost"], reverse=True)

    return {
        "month": month,
        "elapsed_months_analyzed": elapsed_months_count,
        "critical_alarms_count": sum(1 for a in alarms if a["severity"] == "critical"),
        "warning_alarms_count": sum(1 for a in alarms if a["severity"] == "warning"),
        "alarms": alarms,
        "total_potential_monthly_savings": float(_q(total_monthly_savings)),
        "total_potential_annual_savings": float(_q(total_monthly_savings * Decimal("12"))),
        "opportunities": opportunities,
        "subscription_drains": sub_drains[:10],
    }
