"""Load, validate, and idempotently sync declarative YAML IaC configs into PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from finops.db.models import Category, Person, PluggyItem, PluggySource, ProjectionRule
from scripts.validate_config import load_yaml, validate_config_dir


@dataclass
class LoadedConfig:
    config_dir: Path
    currency: str
    people: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    categories: list[dict[str, Any]]
    internal_transfers: list[dict[str, Any]]
    categorization_rules: list[dict[str, Any]]
    horizon: dict[str, Any]
    recurring: list[dict[str, Any]]
    annual: list[dict[str, Any]]


def load_yaml_bundle(config_dir: Path) -> LoadedConfig:
    """Validate and parse all 5 FinOps YAML files from `config_dir`."""
    errors = validate_config_dir(config_dir)
    if errors:
        joined = "\n".join(f"  - {e}" for e in errors)
        raise ValueError(f"Invalid FinOps YAML configuration in {config_dir}:\n{joined}")

    people_cfg = load_yaml(config_dir / "people.yaml")
    sources_cfg = load_yaml(config_dir / "sources.yaml")
    categories_cfg = load_yaml(config_dir / "categories.yaml")
    rules_cfg = load_yaml(config_dir / "rules.yaml")
    projections_cfg = load_yaml(config_dir / "projections.yaml")

    sorted_rules = sorted(rules_cfg.get("categorization_rules", []), key=lambda r: int(r["priority"]))

    return LoadedConfig(
        config_dir=config_dir,
        currency=people_cfg["currency"],
        people=people_cfg["people"],
        sources=sources_cfg["sources"],
        categories=categories_cfg["categories"],
        internal_transfers=rules_cfg.get("internal_transfers", []),
        categorization_rules=sorted_rules,
        horizon=projections_cfg["horizon"],
        recurring=projections_cfg.get("recurring", []),
        annual=projections_cfg.get("annual", []),
    )


def load_and_sync_config(db: Session, config_dir: Path) -> LoadedConfig:
    """Validate YAML files and idempotently upsert entities into PostgreSQL."""
    bundle = load_yaml_bundle(config_dir)

    # 1. People
    for p in bundle.people:
        person = db.get(Person, p["id"])
        if person is None:
            person = Person(id=p["id"])
            db.add(person)
        person.display_name = p["display_name"]
        person.default_split_weight = Decimal(str(p["default_split_weight"]))
        person.currency = bundle.currency

    db.flush()

    # 2. Sources & Pluggy Items
    for src in bundle.sources:
        source = db.get(PluggySource, src["id"])
        if source is None:
            source = PluggySource(id=src["id"])
            db.add(source)
        source.person_id = src["person_id"]
        source.provider_type = src["provider"]
        source.client_id_env = src.get("client_id_env")
        source.client_secret_env = src.get("client_secret_env")
        source.import_dir = src.get("import_dir")
        source.default_scope = src.get("default_scope", "personal")

        if src["provider"] == "pluggy_api":
            for item_cfg in src.get("items", []):
                item = db.get(PluggyItem, item_cfg["item_id"])
                if item is None:
                    item = PluggyItem(id=item_cfg["item_id"], source_id=src["id"])
                    db.add(item)
                item.source_id = src["id"]
                item.label = item_cfg["label"]
                item.default_scope = item_cfg["default_scope"]

    db.flush()

    # 3. Two-level Categories (parent + parent.subcategory)
    active_category_ids: set[str] = set()
    for cat in bundle.categories:
        active_category_ids.add(cat["id"])
        parent = db.get(Category, cat["id"])
        if parent is None:
            parent = Category(id=cat["id"])
            db.add(parent)
        parent.parent_id = None
        parent.name = cat["name"]
        parent.kind = cat["kind"]
        parent.default_scope = cat["default_scope"]
        parent.is_annual = False
        parent.projection_method = "none"
        parent.monthly_budget_cap = None
        parent.warning_threshold_pct = Decimal("80.00")
        parent.is_discretionary = False
        parent.cut_target_pct = Decimal("20.00")
        parent.custom_split_weights = cat.get("custom_split_weights")

        db.flush()

        for sub in cat["subcategories"]:
            full_id = f"{cat['id']}.{sub['id']}"
            active_category_ids.add(full_id)
            sub_row = db.get(Category, full_id)
            if sub_row is None:
                sub_row = Category(id=full_id)
                db.add(sub_row)
            sub_row.parent_id = cat["id"]
            sub_row.name = sub["name"]
            sub_row.kind = cat["kind"]
            sub_row.default_scope = sub.get("default_scope", cat["default_scope"])
            sub_row.is_annual = bool(sub.get("is_annual", False))
            sub_row.projection_method = sub["projection_method"]
            cap = sub.get("monthly_budget_cap")
            sub_row.monthly_budget_cap = Decimal(str(cap)) if cap is not None else None
            sub_row.warning_threshold_pct = Decimal(str(sub.get("warning_threshold_pct", 80)))
            sub_row.is_discretionary = bool(sub.get("discretionary", False))
            sub_row.cut_target_pct = Decimal(str(sub.get("cut_target_pct", 20)))
            sub_row.custom_split_weights = cat.get("custom_split_weights")

    db.flush()

    # 4. Projection Rules (recurring + annual) — replace rules removed from YAML
    active_rule_ids: set[str] = set()

    for rec in bundle.recurring:
        active_rule_ids.add(rec["id"])
        rule = db.get(ProjectionRule, rec["id"])
        if rule is None:
            rule = ProjectionRule(id=rec["id"])
            db.add(rule)
        rule.name = rec.get("name", rec["id"])
        rule.rule_kind = "recurring"
        rule.category_id = rec["category_id"]
        rule.scope = rec["scope"]
        rule.owner_person_id = rec.get("owner_person_id")
        rule.frequency = rec["frequency"]
        rule.due_month = None
        rule.amount = Decimal(str(rec["amount"]))
        rule.valid_from = rec.get("valid_from")
        rule.valid_to = rec.get("valid_to")
        rule.smooth_monthly = False
        rule.annual_adjustment_pct = Decimal(str(rec.get("annual_adjustment_pct", 0)))

    for ann in bundle.annual:
        active_rule_ids.add(ann["id"])
        rule = db.get(ProjectionRule, ann["id"])
        if rule is None:
            rule = ProjectionRule(id=ann["id"])
            db.add(rule)
        rule.name = ann.get("name", ann["id"])
        rule.rule_kind = "annual"
        rule.category_id = ann["category_id"]
        rule.scope = ann["scope"]
        rule.owner_person_id = ann.get("owner_person_id")
        rule.frequency = "annual"
        rule.due_month = int(ann["due_month"])
        rule.amount = Decimal(str(ann["amount"]))
        rule.valid_from = None
        rule.valid_to = None
        rule.smooth_monthly = bool(ann.get("smooth_monthly", False))
        rule.annual_adjustment_pct = Decimal(str(ann.get("annual_adjustment_pct", 0)))

    # Prune deleted YAML rules
    for existing in db.query(ProjectionRule).all():
        if existing.id not in active_rule_ids:
            db.delete(existing)

    db.flush()

    # Prune orphan categories no longer in categories.yaml (if unreferenced by transactions/overrides)
    from finops.db.models import ProjectionOverride, Transaction

    referenced_cats: set[str] = {
        r[0] for r in db.query(Transaction.category_id).filter(Transaction.category_id.is_not(None)).distinct()
    }
    referenced_cats.update(r[0] for r in db.query(ProjectionOverride.category_id).distinct())

    for existing_cat in db.query(Category).filter(Category.parent_id.is_not(None)).all():
        if existing_cat.id not in active_category_ids and existing_cat.id not in referenced_cats:
            db.delete(existing_cat)

    db.flush()

    remaining_parents = {
        r[0] for r in db.query(Category.parent_id).filter(Category.parent_id.is_not(None)).distinct()
    }
    for parent_cat in db.query(Category).filter(Category.parent_id.is_(None)).all():
        if parent_cat.id not in active_category_ids and parent_cat.id not in remaining_parents:
            db.delete(parent_cat)

    db.commit()
    return bundle
