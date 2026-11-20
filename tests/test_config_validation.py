"""Tests for declarative YAML configuration validation."""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from scripts.validate_config import validate_config_dir

ROOT_DIR = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = ROOT_DIR / "config" / "examples"


def test_example_configs_are_valid() -> None:
    errors = validate_config_dir(EXAMPLES_DIR)
    assert errors == [], f"Expected zero errors, got: {errors}"


def test_rejects_split_weights_not_summing_to_one(tmp_path: Path) -> None:
    shutil.copytree(EXAMPLES_DIR, tmp_path / "cfg")
    people_path = tmp_path / "cfg" / "people.yaml"
    data = yaml.safe_load(people_path.read_text(encoding="utf-8"))
    data["people"][0]["default_split_weight"] = 0.70
    people_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    errors = validate_config_dir(tmp_path / "cfg")
    assert any("must sum to 1.0" in err for err in errors)


def test_rejects_unknown_category_in_rules(tmp_path: Path) -> None:
    shutil.copytree(EXAMPLES_DIR, tmp_path / "cfg")
    rules_path = tmp_path / "cfg" / "rules.yaml"
    data = yaml.safe_load(rules_path.read_text(encoding="utf-8"))
    data["categorization_rules"][0]["category_id"] = "nonexistent.sub"
    rules_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    errors = validate_config_dir(tmp_path / "cfg")
    assert any("unknown category_id 'nonexistent.sub'" in err for err in errors)


def test_rejects_duplicate_pluggy_item_id(tmp_path: Path) -> None:
    shutil.copytree(EXAMPLES_DIR, tmp_path / "cfg")
    sources_path = tmp_path / "cfg" / "sources.yaml"
    data = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
    first_id = data["sources"][0]["items"][0]["item_id"]
    data["sources"][1]["items"][0]["item_id"] = first_id
    sources_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    errors = validate_config_dir(tmp_path / "cfg")
    assert any("duplicate Pluggy item_id" in err for err in errors)


def test_rejects_personal_projection_without_owner(tmp_path: Path) -> None:
    shutil.copytree(EXAMPLES_DIR, tmp_path / "cfg")
    proj_path = tmp_path / "cfg" / "projections.yaml"
    data = yaml.safe_load(proj_path.read_text(encoding="utf-8"))
    del data["recurring"][0]["owner_person_id"]
    proj_path.write_text(yaml.safe_dump(data), encoding="utf-8")

    errors = validate_config_dir(tmp_path / "cfg")
    assert any("requires owner_person_id" in err for err in errors)
