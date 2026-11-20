"""Deterministic YAML categorization and internal-transfer detection."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from finops.config.loader import LoadedConfig
from finops.db.models import Category, Transaction

PROTECTED_SOURCES = frozenset({"manual", "hermes"})


def apply_rules_to_transaction(
    tx: Transaction,
    bundle: LoadedConfig,
    categories_by_id: dict[str, Category],
) -> None:
    """Apply internal-transfer detection and categorization rules to one transaction.

    Supports description `match_regex`, Open Finance `match_provider_category`,
    and optional `match_amount_sign` ('positive' | 'negative').
    Never overwrites transactions explicitly classified by `manual` or `hermes`.
    """
    if tx.categorization_source in PROTECTED_SOURCES:
        return

    # Reset rule-derived state before re-evaluating so updated rules take effect cleanly
    tx.is_internal_transfer = False
    tx.category_id = None
    tx.categorization_source = "uncategorized"

    provider_cat = (tx.provider_category or "").strip().lower()

    # 1. Internal transfers (regex or provider_category, e.g., credit card bill payments)
    for rule in bundle.internal_transfers:
        regex = rule.get("match_regex")
        pcat = (rule.get("match_provider_category") or "").strip().lower()
        if not regex and not pcat:
            continue
        regex_ok = True if not regex else bool(re.search(regex, tx.description))
        pcat_ok = True if not pcat else (provider_cat == pcat)
        if regex_ok and pcat_ok:
            tx.is_internal_transfer = True
            tx.categorization_source = "yaml_rule"
            return

    # 2. Priority-ordered categorization rules
    for rule in bundle.categorization_rules:
        sign = rule.get("match_amount_sign")
        if sign == "positive" and tx.amount <= 0:
            continue
        if sign == "negative" and tx.amount >= 0:
            continue

        regex = rule.get("match_regex")
        pcat = (rule.get("match_provider_category") or "").strip().lower()
        regex_ok = True if not regex else bool(re.search(regex, tx.description))
        pcat_ok = True if not pcat else (provider_cat == pcat)

        if regex_ok and pcat_ok:
            cat_id = rule["category_id"]
            if cat_id in categories_by_id:
                tx.category_id = cat_id
                tx.scope = rule["scope"]
                if rule["scope"] == "shared":
                    tx.owner_person_id = None
                else:
                    tx.owner_person_id = rule.get("owner_person_id") or tx.paid_by_person_id
                tx.categorization_source = "yaml_rule"
                return


def detect_inter_account_transfers(db: Session, bundle: LoadedConfig) -> int:
    """Pair opposite-sign equal-amount transactions across household accounts within N days."""
    max_window: int | None = None
    for rule in bundle.internal_transfers:
        days = rule.get("match_same_amount_opposite_sign_within_days")
        if days is not None:
            max_window = max(max_window or 0, int(days))

    if max_window is None:
        return 0

    candidates = (
        db.query(Transaction)
        .filter(Transaction.is_internal_transfer.is_(False))
        .order_by(Transaction.transaction_date.asc())
        .all()
    )

    matched_ids: set[str] = set()
    marked = 0

    for idx, tx_a in enumerate(candidates):
        if tx_a.id in matched_ids or tx_a.categorization_source in PROTECTED_SOURCES:
            continue
        if tx_a.amount == 0:
            continue

        for tx_b in candidates[idx + 1 :]:
            if tx_b.id in matched_ids or tx_b.categorization_source in PROTECTED_SOURCES:
                continue
            if tx_b.transaction_date - tx_a.transaction_date > timedelta(days=max_window):
                break
            if tx_a.account_id == tx_b.account_id:
                continue
            if tx_a.amount + tx_b.amount == 0:
                tx_a.is_internal_transfer = True
                tx_b.is_internal_transfer = True
                tx_a.categorization_source = "yaml_rule"
                tx_b.categorization_source = "yaml_rule"
                matched_ids.add(tx_a.id)
                matched_ids.add(tx_b.id)
                marked += 2
                break

    return marked


def recategorize_all(db: Session, bundle: LoadedConfig) -> dict[str, int]:
    """Re-apply YAML rules to all non-protected transactions."""
    categories_by_id: dict[str, Category] = {c.id: c for c in db.query(Category).all()}
    txs = db.query(Transaction).all()

    categorized = 0
    for tx in txs:
        if tx.categorization_source in PROTECTED_SOURCES:
            continue
        apply_rules_to_transaction(tx, bundle, categories_by_id)
        if tx.category_id is not None:
            categorized += 1

    transfers_marked = detect_inter_account_transfers(db, bundle)
    db.commit()
    return {
        "evaluated": len(txs),
        "categorized": categorized,
        "internal_transfers_marked": transfers_marked,
    }


def draft_yaml_rule_snippet(
    pattern: str,
    category_id: str,
    scope: str,
    owner_person_id: str | None = None,
    priority: int = 50,
    description: str | None = None,
) -> dict[str, Any]:
    """Validate regex and return a ready-to-paste `rules.yaml` entry."""
    re.compile(pattern)
    entry: dict[str, Any] = {
        "priority": priority,
        "description": description or f"Auto-rule for {category_id}",
        "match_regex": pattern,
        "category_id": category_id,
        "scope": scope,
    }
    if scope == "personal" and owner_person_id:
        entry["owner_person_id"] = owner_person_id
    return entry
