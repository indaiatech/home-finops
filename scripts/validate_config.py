#!/usr/bin/env python3
"""Validate FinOps declarative YAML configuration files against JSON Schemas
and cross-file referential integrity rules.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from rich.console import Console

ROOT_DIR = Path(__file__).resolve().parent.parent
SCHEMAS_DIR = ROOT_DIR / "config" / "schemas"

CONFIG_FILES = (
    ("people.yaml", "people.schema.json"),
    ("sources.yaml", "sources.schema.json"),
    ("categories.yaml", "categories.schema.json"),
    ("rules.yaml", "rules.schema.json"),
    ("projections.yaml", "projections.schema.json"),
)


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def validate_config_dir(config_dir: Path) -> list[str]:
    """Validate all YAML configs in `config_dir`. Returns a list of error strings."""
    errors: list[str] = []
    loaded: dict[str, Any] = {}

    if not config_dir.exists() or not config_dir.is_dir():
        return [f"Config directory does not exist: {config_dir}"]

    for yaml_name, schema_name in CONFIG_FILES:
        yaml_path = config_dir / yaml_name
        schema_path = SCHEMAS_DIR / schema_name

        if not yaml_path.exists():
            errors.append(f"Missing required config file: {yaml_path}")
            continue

        try:
            data = load_yaml(yaml_path)
        except yaml.YAMLError as exc:
            errors.append(f"{yaml_name}: invalid YAML syntax: {exc}")
            continue

        schema = load_json(schema_path)
        validator = Draft202012Validator(schema)
        file_errors = sorted(validator.iter_errors(data), key=lambda err: list(err.path))
        for err in file_errors:
            loc = ".".join(str(p) for p in err.path) or "<root>"
            errors.append(f"{yaml_name} [{loc}]: {err.message}")

        if not file_errors:
            loaded[yaml_name] = data

    # Stop before cross-file checks if any file failed schema validation
    if errors:
        return errors

    errors.extend(_validate_cross_references(loaded))
    return errors


def _validate_cross_references(loaded: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    people_cfg = loaded["people.yaml"]
    sources_cfg = loaded["sources.yaml"]
    categories_cfg = loaded["categories.yaml"]
    rules_cfg = loaded["rules.yaml"]
    projections_cfg = loaded["projections.yaml"]

    # 1. People: unique IDs & split weights sum to 1.0
    person_ids: set[str] = set()
    weight_sum = 0.0
    for person in people_cfg["people"]:
        pid = person["id"]
        if pid in person_ids:
            errors.append(f"people.yaml: duplicate person id '{pid}'")
        person_ids.add(pid)
        weight_sum += float(person["default_split_weight"])

    if not math.isclose(weight_sum, 1.0, abs_tol=1e-6):
        errors.append(f"people.yaml: default_split_weight values must sum to 1.0 (got {weight_sum:.6f})")

    # 2. Sources: unique source IDs, valid person_ids, unique Pluggy item_ids
    source_ids: set[str] = set()
    pluggy_item_ids: set[str] = set()
    for source in sources_cfg["sources"]:
        sid = source["id"]
        if sid in source_ids:
            errors.append(f"sources.yaml: duplicate source id '{sid}'")
        source_ids.add(sid)

        if source["person_id"] not in person_ids:
            errors.append(f"sources.yaml: source '{sid}' references unknown person_id '{source['person_id']}'")

        if source["provider"] == "pluggy_api":
            for item in source["items"]:
                iid = item["item_id"].lower()
                if iid in pluggy_item_ids:
                    errors.append(f"sources.yaml: duplicate Pluggy item_id '{item['item_id']}'")
                pluggy_item_ids.add(iid)

    # 3. Categories: unique category & subcategory IDs, valid custom_split_weights
    category_ids: set[str] = set()
    full_subcategory_ids: set[str] = set()
    for cat in categories_cfg["categories"]:
        cid = cat["id"]
        if cid in category_ids:
            errors.append(f"categories.yaml: duplicate category id '{cid}'")
        category_ids.add(cid)

        if "custom_split_weights" in cat:
            cweights = cat["custom_split_weights"]
            for pid in cweights:
                if pid not in person_ids:
                    errors.append(
                        f"categories.yaml: category '{cid}' custom_split_weights references "
                        f"unknown person_id '{pid}'"
                    )
            csum = sum(float(v) for v in cweights.values())
            if not math.isclose(csum, 1.0, abs_tol=1e-6):
                errors.append(
                    f"categories.yaml: category '{cid}' custom_split_weights must sum to 1.0 (got {csum:.6f})"
                )

        sub_ids: set[str] = set()
        for sub in cat["subcategories"]:
            sub_id = sub["id"]
            if sub_id in sub_ids:
                errors.append(f"categories.yaml: duplicate subcategory id '{sub_id}' under '{cid}'")
            sub_ids.add(sub_id)
            full_subcategory_ids.add(f"{cid}.{sub_id}")

    # 4. Rules: valid regexes, valid category_id & optional owner_person_id
    for transfer_rule in rules_cfg["internal_transfers"]:
        regex = transfer_rule.get("match_regex")
        if regex:
            try:
                re.compile(regex)
            except re.error as exc:
                errors.append(f"rules.yaml: invalid regex in internal_transfers '{transfer_rule['name']}': {exc}")

    for idx, rule in enumerate(rules_cfg["categorization_rules"]):
        regex = rule.get("match_regex")
        if regex:
            try:
                re.compile(regex)
            except re.error as exc:
                errors.append(f"rules.yaml: invalid regex in categorization_rules[{idx}]: {exc}")

        if rule["category_id"] not in full_subcategory_ids:
            errors.append(
                f"rules.yaml: categorization_rules[{idx}] references unknown category_id '{rule['category_id']}'"
            )

        owner = rule.get("owner_person_id")
        if owner and owner not in person_ids:
            errors.append(f"rules.yaml: categorization_rules[{idx}] references unknown owner_person_id '{owner}'")

    # 5. Projections: unique IDs, valid category_id & owner_person_id
    proj_ids: set[str] = set()
    for section in ("recurring", "annual"):
        for item in projections_cfg[section]:
            pid = item["id"]
            if pid in proj_ids:
                errors.append(f"projections.yaml: duplicate projection id '{pid}'")
            proj_ids.add(pid)

            if item["category_id"] not in full_subcategory_ids:
                errors.append(
                    f"projections.yaml: {section} '{pid}' references unknown category_id '{item['category_id']}'"
                )

            owner = item.get("owner_person_id")
            if owner and owner not in person_ids:
                errors.append(f"projections.yaml: {section} '{pid}' references unknown owner_person_id '{owner}'")

            if item["scope"] == "personal" and not owner:
                errors.append(
                    f"projections.yaml: {section} '{pid}' has scope 'personal' and requires owner_person_id"
                )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate FinOps YAML configurations.")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=ROOT_DIR / "config" / "examples",
        help=(
            "Path to the configuration directory containing "
            "people/sources/categories/rules/projections YAML files."
        ),
    )
    args = parser.parse_args()

    console = Console()
    errors = validate_config_dir(args.config_dir)
    if errors:
        console.print(f"[bold red]Validation failed for {args.config_dir}:[/bold red]")
        for err in errors:
            console.print(f"  - {err}")
        return 1

    console.print(f"[bold green]All YAML configurations in {args.config_dir} are valid.[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
