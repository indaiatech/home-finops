"""24-month spreadsheet matrix, layered projection engine, drill-down, and simulator."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy.orm import Session

from finops.db.models import (
    BankAccount,
    Category,
    Person,
    ProjectionOverride,
    ProjectionRule,
    Transaction,
)
from finops.engines.settlement import compute_monthly_settlement

TWO_PLACES = Decimal("0.01")


def _q(val: Decimal) -> Decimal:
    return val.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def build_24_months(base_year: int) -> list[str]:
    """Return 24 YYYY-MM keys spanning `base_year` and `base_year + 1`."""
    return [f"{y}-{m:02d}" for y in (base_year, base_year + 1) for m in range(1, 13)]


def _shift_month_key(month_key: str, delta: int) -> str:
    y, m = int(month_key[:4]), int(month_key[5:7])
    total = (y * 12 + (m - 1)) + delta
    ny, nm = total // 12, (total % 12) + 1
    return f"{ny:04d}-{nm:02d}"


def _rule_amount_for_month(
    rule: ProjectionRule,
    month_key: str,
    base_year: int,
    annual_mode: str,
) -> Decimal:
    """Evaluate a recurring or annual YAML projection rule for one `YYYY-MM` month."""
    y = int(month_key[:4])
    m = int(month_key[5:7])

    if rule.valid_from and month_key < rule.valid_from:
        return Decimal("0.00")
    if rule.valid_to and month_key > rule.valid_to:
        return Decimal("0.00")

    base_amt = Decimal(str(rule.amount))
    years_ahead = max(0, y - base_year)
    if years_ahead > 0 and rule.annual_adjustment_pct:
        factor = (Decimal("1") + Decimal(str(rule.annual_adjustment_pct)) / Decimal("100")) ** years_ahead
        base_amt = base_amt * factor

    if rule.rule_kind == "annual":
        if annual_mode == "monthly_provision" and rule.smooth_monthly:
            return _q(base_amt / Decimal("12"))
        if rule.due_month == m:
            return _q(base_amt)
        return Decimal("0.00")

    # Recurring rule
    if rule.frequency == "monthly":
        return _q(base_amt)
    if rule.frequency == "quarterly":
        start_m = int(rule.valid_from[5:7]) if rule.valid_from else 1
        return _q(base_amt) if (m - start_m) % 3 == 0 else Decimal("0.00")
    if rule.frequency == "semiannual":
        start_m = int(rule.valid_from[5:7]) if rule.valid_from else 1
        return _q(base_amt) if (m - start_m) % 6 == 0 else Decimal("0.00")
    return Decimal("0.00")


def _compute_future_installments(
    transactions: list[Transaction],
    months_set: set[str],
    current_month: str,
) -> dict[tuple[str, str, str | None, str], list[dict[str, Any]]]:
    """Project remaining credit-card installments into future months.

    Key: `(category_id, scope, owner_person_id, month_key)` -> list of installment dicts.
    """
    latest_by_group: dict[str, Transaction] = {}
    posted_group_months: set[tuple[str, str]] = set()
    for tx in transactions:
        if tx.is_internal_transfer or not tx.installment_group_id:
            continue
        posted_group_months.add((tx.installment_group_id, tx.competence_month))
        if (
            not tx.installment_number
            or not tx.installment_total
            or tx.installment_number >= tx.installment_total
            or not tx.category_id
        ):
            continue
        prev = latest_by_group.get(tx.installment_group_id)
        if prev is None or (tx.installment_number or 0) > (prev.installment_number or 0):
            latest_by_group[tx.installment_group_id] = tx

    projected: dict[tuple[str, str, str | None, str], list[dict[str, Any]]] = defaultdict(list)
    for tx in latest_by_group.values():
        assert tx.installment_number is not None and tx.installment_total is not None
        assert tx.category_id is not None and tx.installment_group_id is not None
        remaining = tx.installment_total - tx.installment_number
        inst_abs = abs(Decimal(str(tx.amount)))
        for step in range(1, remaining + 1):
            target_month = _shift_month_key(tx.competence_month, step)
            if target_month <= current_month or target_month not in months_set:
                continue
            if (tx.installment_group_id, target_month) in posted_group_months:
                continue
            key = (tx.category_id, tx.scope, tx.owner_person_id, target_month)
            projected[key].append(
                {
                    "description": tx.description,
                    "installment_number": tx.installment_number + step,
                    "installment_total": tx.installment_total,
                    "amount": float(_q(inst_abs)),
                }
            )
    return projected


def compute_spreadsheet_matrix(
    db: Session,
    *,
    base_year: int | None = None,
    annual_mode: str = "cash",
    scope_filter: str = "all",
    person_id: str | None = None,
    emergency_months: int = 6,
    today: date | None = None,
) -> dict[str, Any]:
    """Compute the complete 24-month spreadsheet grid (current year + next year)."""
    ref_today = today or date.today()
    year = base_year or ref_today.year
    current_month = ref_today.strftime("%Y-%m")
    months = build_24_months(year)
    months_set = set(months)

    people = db.query(Person).order_by(Person.id.asc()).all()
    people_map = {p.id: p for p in people}
    currency = people[0].currency if people else "BRL"

    all_cats = db.query(Category).all()
    parents_by_id = {c.id: c for c in all_cats if c.parent_id is None}
    subcats = sorted(
        [c for c in all_cats if c.parent_id is not None],
        key=lambda c: (0 if c.kind == "income" else 1, c.parent_id or "", c.id),
    )
    subcat_by_id = {c.id: c for c in subcats}

    # Fetch non-transfer transactions covering rolling average history + horizon
    earliest_lookback = f"{year - 1}-01"
    txs = (
        db.query(Transaction)
        .filter(
            Transaction.is_internal_transfer.is_(False),
            Transaction.competence_month >= earliest_lookback,
        )
        .all()
    )

    rules = db.query(ProjectionRule).all()
    overrides = db.query(ProjectionOverride).filter(ProjectionOverride.competence_month.in_(months)).all()

    # Index realized amounts by (category_id, scope, owner_person_id, month_key)
    realized_map: dict[tuple[str, str, str | None, str], Decimal] = defaultdict(lambda: Decimal("0.00"))
    uncat_map: dict[tuple[str, str | None, str], Decimal] = defaultdict(lambda: Decimal("0.00"))
    uncat_count = 0

    for tx in txs:
        val = abs(Decimal(str(tx.amount)))
        if tx.category_id is None:
            if tx.competence_month in months_set:
                uncat_count += 1
                uncat_map[(tx.scope, tx.owner_person_id, tx.competence_month)] += val
            continue
        owner = None if tx.scope == "shared" else tx.owner_person_id
        realized_map[(tx.category_id, tx.scope, owner, tx.competence_month)] += val

    # Index overrides
    override_map: dict[tuple[str, str, str | None, str], ProjectionOverride] = {}
    for ov in overrides:
        owner = None if ov.scope == "shared" else ov.owner_person_id
        override_map[(ov.category_id, ov.scope, owner, ov.competence_month)] = ov

    # Index YAML projection rules by (category_id, scope, owner_person_id)
    rules_by_row: dict[tuple[str, str, str | None], list[ProjectionRule]] = defaultdict(list)
    for r in rules:
        owner = None if r.scope == "shared" else r.owner_person_id
        rules_by_row[(r.category_id, r.scope, owner)].append(r)

    # Future credit card installments
    installments_map = _compute_future_installments(txs, months_set, current_month)

    # Determine distinct spreadsheet rows: (category_id, scope, owner_person_id)
    row_keys_set: set[tuple[str, str, str | None]] = set()
    for sub in subcats:
        if sub.default_scope == "shared":
            row_keys_set.add((sub.id, "shared", None))
        else:
            for p in people:
                row_keys_set.add((sub.id, "personal", p.id))

    # Also include any row key that has realized transactions, rules, or overrides
    for cid, sc, own, _m in realized_map:
        if cid in subcat_by_id:
            row_keys_set.add((cid, sc, own))
    for cid, sc, own in rules_by_row:
        if cid in subcat_by_id:
            row_keys_set.add((cid, sc, own))
    for cid, sc, own, _m in override_map:
        if cid in subcat_by_id:
            row_keys_set.add((cid, sc, own))

    # Helper to compute moving average over the last N completed months (< current_month)
    def moving_avg(cat_id: str, sc: str, own: str | None, window: int) -> Decimal:
        vals: list[Decimal] = []
        for step in range(1, window + 1):
            mk = _shift_month_key(current_month, -step)
            v = realized_map.get((cat_id, sc, own, mk), Decimal("0.00"))
            if v > Decimal("0.00"):
                vals.append(v)
        if not vals:
            return Decimal("0.00")
        return _q(sum(vals, Decimal("0.00")) / Decimal(len(vals)))

    rows: list[dict[str, Any]] = []
    income_totals = {m: Decimal("0.00") for m in months}
    expense_totals = {m: Decimal("0.00") for m in months}
    shared_expense_totals = {m: Decimal("0.00") for m in months}

    sorted_row_keys = sorted(
        row_keys_set,
        key=lambda k: (
            0
            if subcat_by_id[k[0]].kind == "income"
            else (2 if subcat_by_id[k[0]].is_annual else (1 if k[1] == "shared" else 3)),
            k[2] or "",
            k[0],
        ),
    )

    for cat_id, sc, own in sorted_row_keys:
        sub = subcat_by_id[cat_id]
        parent = parents_by_id.get(sub.parent_id or "")

        # Determine display section
        if sub.kind == "income":
            section = "income"
        elif sub.is_annual:
            section = "annual"
        elif sc == "shared":
            section = "shared"
        else:
            section = "personal"

        # Apply user filters
        if scope_filter == "shared" and sc != "shared":
            continue
        if scope_filter == "personal" and sc != "personal":
            continue
        if scope_filter == "annual" and not sub.is_annual:
            continue
        if person_id and sc == "personal" and own != person_id:
            continue
        if person_id and sc == "shared" and scope_filter == "personal":
            continue

        row_rules = rules_by_row.get((cat_id, sc, own), [])
        avg_3m = moving_avg(cat_id, sc, own, 3) if sub.projection_method == "moving_avg_3m" else Decimal("0.00")
        avg_6m = moving_avg(cat_id, sc, own, 6) if sub.projection_method == "moving_avg_6m" else Decimal("0.00")

        cells: dict[str, dict[str, Any]] = {}
        y1_total = Decimal("0.00")
        y2_total = Decimal("0.00")
        has_any_nonzero = False

        for mk in months:
            realized = _q(realized_map.get((cat_id, sc, own, mk), Decimal("0.00")))
            ov = override_map.get((cat_id, sc, own, mk))

            # Compute baseline projection from layers 2..4
            inst_items = installments_map.get((cat_id, sc, own, mk), [])
            inst_sum = _q(sum((Decimal(str(it["amount"])) for it in inst_items), Decimal("0.00")))

            rule_sum = _q(
                sum(
                    (_rule_amount_for_month(r, mk, year, annual_mode) for r in row_rules),
                    Decimal("0.00"),
                )
            )

            stat_proj = Decimal("0.00")
            if rule_sum == Decimal("0.00"):
                if sub.projection_method == "moving_avg_3m":
                    stat_proj = avg_3m
                elif sub.projection_method == "moving_avg_6m":
                    stat_proj = avg_6m
                elif sub.projection_method == "budget_cap" and sub.monthly_budget_cap is not None:
                    stat_proj = _q(Decimal(str(sub.monthly_budget_cap)))

            posted_future = realized if mk > current_month else Decimal("0.00")
            total_installments = _q(inst_sum + posted_future)
            if mk > current_month and posted_future > Decimal("0.00") and stat_proj > Decimal("0.00"):
                # Avoid double-counting posted future installments with historical moving average
                auto_projected = _q(max(total_installments, stat_proj) + rule_sum)
            else:
                auto_projected = _q(total_installments + rule_sum + stat_proj)

            if mk < current_month:
                # Past month -> 100% realized (keep auto_projected as budget comparison)
                display_val = realized
                cell_source = "realized"
                note = None
            elif mk == current_month:
                # Current month -> hybrid: override if set, else max(realized, auto_projected)
                if ov is not None:
                    display_val = _q(Decimal(str(ov.amount)))
                    cell_source = "override"
                    note = ov.note
                elif realized > Decimal("0.00") and auto_projected > realized:
                    display_val = auto_projected
                    cell_source = "hybrid"
                    note = None
                elif realized > Decimal("0.00"):
                    display_val = realized
                    cell_source = "realized"
                    note = None
                else:
                    display_val = auto_projected
                    cell_source = "projected" if auto_projected > 0 else "realized"
                    note = None
            else:
                # Future month -> Layer 1 Override > Layers 2..4 Auto-projected
                if ov is not None:
                    display_val = _q(Decimal(str(ov.amount)))
                    cell_source = "override"
                    note = ov.note
                else:
                    display_val = auto_projected
                    cell_source = (
                        "installment"
                        if total_installments > 0 and rule_sum == 0 and stat_proj == 0
                        else "projected"
                    )
                    note = None

            if display_val > Decimal("0.00"):
                has_any_nonzero = True

            if mk.startswith(f"{year}-"):
                y1_total += display_val
            else:
                y2_total += display_val

            if sub.kind == "income":
                income_totals[mk] += display_val
            else:
                expense_totals[mk] += display_val
                if sc == "shared":
                    shared_expense_totals[mk] += display_val

            # Compute threshold alarm severity per cell when monthly_budget_cap is configured
            alarm_severity: str | None = None
            util_pct: float | None = None
            cap_val: float | None = (
                float(_q(Decimal(str(sub.monthly_budget_cap))))
                if sub.kind == "expense" and sub.monthly_budget_cap is not None and sub.monthly_budget_cap > 0
                else None
            )
            if cap_val is not None and display_val > Decimal("0.00"):
                cap_dec = Decimal(str(sub.monthly_budget_cap))
                util_pct = float(_q((display_val / cap_dec) * Decimal("100")))
                warn_cutoff = float(sub.warning_threshold_pct or 80)
                if util_pct >= 100.0:
                    alarm_severity = "critical"
                elif util_pct >= warn_cutoff:
                    alarm_severity = "warning"

            cells[mk] = {
                "value": float(display_val),
                "realized": float(realized),
                "projected": float(auto_projected),
                "installments": float(total_installments),
                "source": cell_source,
                "note": note,
                "threshold": cap_val,
                "utilization_pct": util_pct,
                "alarm_severity": alarm_severity,
            }

        # Always keep configured rows with rules/budgets or any data; skip completely empty orphan personal rows
        if not has_any_nonzero and not row_rules and sub.projection_method == "none":
            continue

        rows.append(
            {
                "row_id": f"{cat_id}|{sc}|{own or 'shared'}",
                "section": section,
                "kind": sub.kind,
                "parent_category_id": sub.parent_id,
                "parent_category_name": parent.name if parent else sub.name,
                "category_id": cat_id,
                "category_name": sub.name,
                "scope": sc,
                "owner_person_id": own,
                "owner_display_name": people_map[own].display_name if own and own in people_map else "General",
                "is_annual": sub.is_annual,
                "is_discretionary": bool(sub.is_discretionary),
                "monthly_budget_cap": (
                    float(_q(Decimal(str(sub.monthly_budget_cap)))) if sub.monthly_budget_cap is not None else None
                ),
                "warning_threshold_pct": float(sub.warning_threshold_pct or 80),
                "cut_target_pct": float(sub.cut_target_pct or 20),
                "projection_method": sub.projection_method,
                "cells": cells,
                "total_year_1": float(_q(y1_total)),
                "total_year_2": float(_q(y2_total)),
                "monthly_avg": float(_q((y1_total + y2_total) / Decimal("24"))),
            }
        )

    # Add uncategorized expenses row if any exist in the 24-month window
    if uncat_map and scope_filter != "annual":
        uncat_cells: dict[str, dict[str, Any]] = {}
        u_y1 = Decimal("0.00")
        u_y2 = Decimal("0.00")
        for mk in months:
            val = Decimal("0.00")
            for (sc, own, m), amt in uncat_map.items():
                if m != mk:
                    continue
                if scope_filter == "shared" and sc != "shared":
                    continue
                if scope_filter == "personal" and sc != "personal":
                    continue
                if person_id and sc == "personal" and own != person_id:
                    continue
                val += amt
            val = _q(val)
            expense_totals[mk] += val
            if mk.startswith(f"{year}-"):
                u_y1 += val
            else:
                u_y2 += val
            uncat_cells[mk] = {
                "value": float(val),
                "realized": float(val),
                "projected": 0.0,
                "installments": 0.0,
                "source": "realized",
                "note": "Needs triage",
            }
        if u_y1 + u_y2 > Decimal("0.00"):
            rows.append(
                {
                    "row_id": "uncategorized|all|none",
                    "section": "uncategorized",
                    "kind": "expense",
                    "parent_category_id": "uncategorized",
                    "parent_category_name": "Uncategorized",
                    "category_id": "uncategorized",
                    "category_name": "Pending Triage",
                    "scope": "shared",
                    "owner_person_id": None,
                    "owner_display_name": "Needs Review",
                    "is_annual": False,
                    "projection_method": "none",
                    "cells": uncat_cells,
                    "total_year_1": float(_q(u_y1)),
                    "total_year_2": float(_q(u_y2)),
                    "monthly_avg": float(_q((u_y1 + u_y2) / Decimal("24"))),
                }
            )

    # Compute household wealth & liquidity summary (Cash + Investments / Caixinhas vs. Credit Cards)
    all_accounts = db.query(BankAccount).all()
    cash_balance = Decimal("0.00")
    investments_balance = Decimal("0.00")
    credit_card_balance = Decimal("0.00")
    emergency_reserve_balance = Decimal("0.00")
    person_wealth: dict[str, dict[str, Decimal]] = {
        p.id: {
            "cash": Decimal("0.00"),
            "investments": Decimal("0.00"),
            "credit_card": Decimal("0.00"),
        }
        for p in people
    }
    positions: list[dict[str, Any]] = []

    for acct in all_accounts:
        bal = _q(Decimal(str(acct.current_balance)))
        atype = acct.account_type.upper()
        is_ef = bool(getattr(acct, "is_emergency_fund", True))
        p_entry = person_wealth.setdefault(
            acct.person_id,
            {"cash": Decimal("0.00"), "investments": Decimal("0.00"), "credit_card": Decimal("0.00")},
        )
        if atype == "CREDIT":
            cc_used = abs(bal)
            credit_card_balance += cc_used
            p_entry["credit_card"] += cc_used
        elif atype == "INVESTMENT":
            if bal > Decimal("0.00"):
                investments_balance += bal
                p_entry["investments"] += bal
                if is_ef:
                    emergency_reserve_balance += bal
                positions.append(
                    {
                        "id": acct.id,
                        "person_id": acct.person_id,
                        "person_name": people_map[acct.person_id].display_name
                        if acct.person_id in people_map
                        else acct.person_id,
                        "account_type": "INVESTMENT",
                        "subtype": acct.subtype or "CDB/RDB",
                        "name": acct.name,
                        "balance": float(bal),
                        "is_emergency_fund": is_ef,
                    }
                )
        else:
            cash_balance += bal
            p_entry["cash"] += bal
            if is_ef and bal > Decimal("0.00"):
                emergency_reserve_balance += bal
            if bal != Decimal("0.00"):
                positions.append(
                    {
                        "id": acct.id,
                        "person_id": acct.person_id,
                        "person_name": people_map[acct.person_id].display_name
                        if acct.person_id in people_map
                        else acct.person_id,
                        "account_type": "BANK",
                        "subtype": acct.subtype or "CHECKING",
                        "name": acct.name,
                        "balance": float(bal),
                        "is_emergency_fund": is_ef,
                    }
                )

    total_saved = _q(cash_balance + investments_balance)
    net_liquidity = _q(total_saved - credit_card_balance)
    starting_cash = total_saved
    positions.sort(key=lambda x: x["balance"], reverse=True)

    # Compute average monthly household expense burn rate (from active months in current year)
    active_exp_months = [
        expense_totals[mk] for mk in months[:12] if mk <= current_month and expense_totals[mk] > Decimal("0.00")
    ]
    if not active_exp_months:
        active_exp_months = [expense_totals[mk] for mk in months[:12] if expense_totals[mk] > Decimal("0.00")]
    avg_monthly_burn = (
        _q(sum(active_exp_months, Decimal("0.00")) / Decimal(len(active_exp_months)))
        if active_exp_months
        else Decimal("0.00")
    )

    target_months_dec = Decimal(max(1, int(emergency_months)))
    target_reserve_amount = _q(avg_monthly_burn * target_months_dec)
    selected_reserve = _q(emergency_reserve_balance)
    surplus_or_deficit = _q(selected_reserve - target_reserve_amount)

    if target_reserve_amount > Decimal("0.00"):
        funded_pct = float(_q((selected_reserve / target_reserve_amount) * Decimal("100")))
        delta_pct = float(_q(Decimal(str(funded_pct)) - Decimal("100")))
    else:
        funded_pct = 100.0 if selected_reserve > 0 else 0.0
        delta_pct = 0.0

    coverage_months = float(_q(selected_reserve / avg_monthly_burn)) if avg_monthly_burn > Decimal("0.00") else 0.0

    emergency_fund_summary = {
        "target_months": int(emergency_months),
        "avg_monthly_expenses": float(avg_monthly_burn),
        "target_amount": float(target_reserve_amount),
        "selected_reserve_balance": float(selected_reserve),
        "excluded_balance": float(_q(total_saved - selected_reserve)),
        "funded_pct": funded_pct,
        "surplus_or_deficit_pct": delta_pct,
        "surplus_or_deficit_amount": float(surplus_or_deficit),
        "coverage_months": coverage_months,
        "status": "surplus" if funded_pct >= 100.0 else ("on_track" if funded_pct >= 80.0 else "shortfall"),
        "selected_positions_count": sum(1 for p in positions if p["is_emergency_fund"]),
        "total_positions_count": len(positions),
    }

    wealth_summary = {
        "total_saved": float(total_saved),
        "cash_balance": float(_q(cash_balance)),
        "investments_balance": float(_q(investments_balance)),
        "credit_card_balance": float(_q(credit_card_balance)),
        "net_liquidity": float(net_liquidity),
        "active_positions_count": len(positions),
        "positions": positions,
        "emergency_fund": emergency_fund_summary,
        "by_person": [
            {
                "person_id": p.id,
                "display_name": p.display_name,
                "cash_balance": float(_q(person_wealth[p.id]["cash"])),
                "investments_balance": float(_q(person_wealth[p.id]["investments"])),
                "total_saved": float(_q(person_wealth[p.id]["cash"] + person_wealth[p.id]["investments"])),
                "credit_card_balance": float(_q(person_wealth[p.id]["credit_card"])),
                "net_liquidity": float(
                    _q(
                        person_wealth[p.id]["cash"]
                        + person_wealth[p.id]["investments"]
                        - person_wealth[p.id]["credit_card"]
                    )
                ),
            }
            for p in people
        ],
    }

    # Monthly summary footer
    summary: dict[str, dict[str, float]] = {}
    running_balance = starting_cash
    for mk in months:
        inc = _q(income_totals[mk])
        exp = _q(expense_totals[mk])
        net = _q(inc - exp)
        if mk >= current_month:
            running_balance = _q(running_balance + net)
        savings_rate = float(_q((net / inc) * Decimal("100"))) if inc > Decimal("0.00") else 0.0
        summary[mk] = {
            "income": float(inc),
            "expenses": float(exp),
            "shared_expenses": float(_q(shared_expense_totals[mk])),
            "net_cashflow": float(net),
            "projected_balance": float(running_balance if mk >= current_month else starting_cash),
            "savings_rate_pct": savings_rate,
        }

    current_settlement = compute_monthly_settlement(db, current_month)

    result_matrix = {
        "base_year": year,
        "next_year": year + 1,
        "current_month": current_month,
        "currency": currency,
        "annual_mode": annual_mode,
        "scope_filter": scope_filter,
        "person_id": person_id,
        "months": months,
        "people": [
            {
                "id": p.id,
                "display_name": p.display_name,
                "default_split_weight": float(p.default_split_weight),
            }
            for p in people
        ],
        "starting_cash_balance": float(starting_cash),
        "wealth_summary": wealth_summary,
        "uncategorized_count": uncat_count,
        "rows": rows,
        "summary": summary,
        "current_month_settlement": current_settlement,
    }
    from finops.engines.alerts import compute_alerts_and_cost_cuts

    result_matrix["alerts_and_cuts"] = compute_alerts_and_cost_cuts(db, result_matrix, current_month)
    return result_matrix


def get_cell_breakdown(
    db: Session,
    *,
    month: str,
    category_id: str,
    scope: str,
    owner_person_id: str | None = None,
    annual_mode: str = "cash",
) -> dict[str, Any]:
    """Return exact realized transactions and projection components for a single spreadsheet cell."""
    owner = None if scope == "shared" else owner_person_id

    tx_query = db.query(Transaction).filter(
        Transaction.competence_month == month,
        Transaction.is_internal_transfer.is_(False),
    )
    if category_id == "uncategorized":
        tx_query = tx_query.filter(Transaction.category_id.is_(None))
    else:
        tx_query = tx_query.filter(
            Transaction.category_id == category_id,
            Transaction.scope == scope,
        )
        if owner is not None:
            tx_query = tx_query.filter(Transaction.owner_person_id == owner)

    txs = tx_query.order_by(Transaction.transaction_date.desc()).all()

    override = (
        db.query(ProjectionOverride)
        .filter(
            ProjectionOverride.competence_month == month,
            ProjectionOverride.category_id == category_id,
            ProjectionOverride.scope == scope,
            ProjectionOverride.owner_person_id == owner,
        )
        .one_or_none()
    )

    rules = (
        db.query(ProjectionRule)
        .filter(
            ProjectionRule.category_id == category_id,
            ProjectionRule.scope == scope,
            ProjectionRule.owner_person_id == owner,
        )
        .all()
    )

    year = int(month[:4])
    current_month = date.today().strftime("%Y-%m")
    month_state = "past" if month < current_month else ("current" if month == current_month else "future")

    rule_items = []
    rule_total = Decimal("0.00")
    for r in rules:
        amt = _rule_amount_for_month(r, month, year, annual_mode)
        if amt > Decimal("0.00"):
            rule_total += amt
            rule_items.append(
                {
                    "id": r.id,
                    "name": r.name,
                    "rule_kind": r.rule_kind,
                    "frequency": r.frequency,
                    "amount": float(amt),
                }
            )

    # Build transparent calculation explanation for the CellDrawer
    category = db.get(Category, category_id) if category_id != "uncategorized" else None
    method = category.projection_method if category else "none"
    components: list[dict[str, Any]] = []

    if override is not None:
        components.append(
            {
                "kind": "override",
                "label": f"Manual override (by {override.updated_by})",
                "detail": override.note or "Replaces auto-projected value for this month.",
                "amount": float(override.amount),
            }
        )

    if rule_items:
        mode_note = "1/12 monthly provision" if annual_mode == "monthly_provision" else "cash view"
        components.append(
            {
                "kind": "yaml_rule",
                "label": f"YAML projection rules ({len(rule_items)})",
                "detail": f"Configured in local/projections.yaml ({mode_note}).",
                "amount": float(_q(rule_total)),
            }
        )
    elif category is not None:
        if method in ("moving_avg_3m", "moving_avg_6m"):
            window = 3 if method == "moving_avg_3m" else 6
            lookback_months = [_shift_month_key(current_month, -step) for step in range(window, 0, -1)]
            hist_q = db.query(Transaction).filter(
                Transaction.category_id == category_id,
                Transaction.scope == scope,
                Transaction.is_internal_transfer.is_(False),
                Transaction.competence_month.in_(lookback_months),
            )
            if owner is not None:
                hist_q = hist_q.filter(Transaction.owner_person_id == owner)
            totals_by_m: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
            for ht in hist_q.all():
                totals_by_m[ht.competence_month] += abs(Decimal(str(ht.amount)))

            nonzero_months = [(m, _q(totals_by_m[m])) for m in lookback_months if totals_by_m[m] > 0]
            if nonzero_months:
                avg_val = _q(sum((v for _, v in nonzero_months), Decimal("0.00")) / Decimal(len(nonzero_months)))
                breakdown_str = " • ".join(f"{m}: {float(v):.2f}" for m, v in nonzero_months)
                components.append(
                    {
                        "kind": "moving_avg",
                        "label": f"{window}-month moving average ({len(nonzero_months)} active closed months)",
                        "detail": breakdown_str,
                        "amount": float(avg_val),
                    }
                )
            else:
                components.append(
                    {
                        "kind": "moving_avg",
                        "label": f"{window}-month moving average",
                        "detail": "No closed historical transactions in the lookback window yet.",
                        "amount": 0.0,
                    }
                )
        elif method == "budget_cap" and category.monthly_budget_cap is not None:
            components.append(
                {
                    "kind": "budget_cap",
                    "label": "YAML monthly budget cap",
                    "detail": "Configured in local/categories.yaml.",
                    "amount": float(category.monthly_budget_cap),
                }
            )

    if month_state == "future" and txs:
        posted_sum = _q(sum((abs(Decimal(str(t.amount))) for t in txs), Decimal("0.00")))
        components.append(
            {
                "kind": "installment",
                "label": f"Posted future transactions / installments ({len(txs)})",
                "detail": "Already scheduled by your bank/card in this future month.",
                "amount": float(posted_sum),
            }
        )

    if month_state == "past":
        display_rule = "Past closed month: displays 100% realized transactions."
    elif month_state == "current":
        display_rule = (
            "Current open month: displays manual override if set, otherwise max(Realized, Auto-Projected) "
            "so monthly cash flow reflects expected month-end spend."
        )
    else:
        display_rule = (
            "Future month: prioritizes Manual Override > Committed Installments & YAML Rules > "
            "Historical Moving Average."
        )

    return {
        "month": month,
        "category_id": category_id,
        "scope": scope,
        "owner_person_id": owner,
        "projection_explanation": {
            "method": method,
            "month_state": month_state,
            "display_rule": display_rule,
            "components": components,
        },
        "transactions": [
            {
                "id": t.id,
                "date": t.transaction_date.isoformat(),
                "description": t.description,
                "amount": float(t.amount),
                "paid_by_person_id": t.paid_by_person_id,
                "scope": t.scope,
                "installment": (
                    f"{t.installment_number}/{t.installment_total}"
                    if t.installment_number and t.installment_total
                    else None
                ),
                "categorization_source": t.categorization_source,
            }
            for t in txs
        ],
        "projection_rules": rule_items,
        "override": (
            {
                "id": override.id,
                "amount": float(override.amount),
                "note": override.note,
                "updated_by": override.updated_by,
            }
            if override
            else None
        ),
    }


def simulate_projection_change(
    db: Session,
    *,
    description: str,
    monthly_amount: Decimal,
    start_month: str,
    months_count: int,
    kind: str = "expense",
    base_year: int | None = None,
) -> dict[str, Any]:
    """Simulate a temporary recurring income/expense impact across the 24-month horizon."""
    matrix = compute_spreadsheet_matrix(db, base_year=base_year)
    affected_months = {_shift_month_key(start_month, i) for i in range(months_count)}
    delta_sign = Decimal("1") if kind == "income" else Decimal("-1")
    step_delta = _q(abs(monthly_amount) * delta_sign)

    impact_rows: list[dict[str, Any]] = []
    cumulative_delta = Decimal("0.00")

    for mk in matrix["months"]:
        base_summary = matrix["summary"][mk]
        delta = step_delta if mk in affected_months else Decimal("0.00")
        cumulative_delta = _q(cumulative_delta + delta)
        if mk in affected_months or delta != Decimal("0.00"):
            impact_rows.append(
                {
                    "month": mk,
                    "baseline_net": base_summary["net_cashflow"],
                    "simulated_net": float(_q(Decimal(str(base_summary["net_cashflow"])) + delta)),
                    "baseline_balance": base_summary["projected_balance"],
                    "simulated_balance": float(
                        _q(Decimal(str(base_summary["projected_balance"])) + cumulative_delta)
                    ),
                }
            )

    end_month = matrix["months"][-1]
    end_base_bal = Decimal(str(matrix["summary"][end_month]["projected_balance"]))
    return {
        "description": description,
        "kind": kind,
        "monthly_amount": float(_q(abs(monthly_amount))),
        "start_month": start_month,
        "months_count": months_count,
        "total_horizon_impact": float(cumulative_delta),
        "end_of_horizon_month": end_month,
        "baseline_end_balance": float(end_base_bal),
        "simulated_end_balance": float(_q(end_base_bal + cumulative_delta)),
        "affected_months": impact_rows,
    }
