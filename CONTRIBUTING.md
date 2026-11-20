# Contributing to FinOps

Thank you for considering contributing to **FinOps**! This project embraces open-source best practices, Infrastructure-as-Code (IaC), and strict privacy hygiene.

## Golden Rules

1. **English-Only Documentation & Archify Diagrams:**
   - All documentation (`README.md`, `docs/`, schemas, comments, commit messages, and example YAML templates) must be written in English. Users customize their personal category labels in their private `local/*.yaml` files.
   - Architecture and workflow diagrams must be authored and validated with **[Archify](https://github.com/tt-a1i/archify)** in `docs/diagrams/` (committing the `.json` spec, interactive `.html`, and `.dark.png`/`.light.png` previews).
   - Keep `README.md` up to date whenever features, architecture, or setup steps change.
2. **Never Commit Secrets or Personal Financial Data (PII):**
   - Never commit `.env`, `local/`, CSV/OFX statements, bank account IDs, real `item_id` UUIDs, real names, or SQL dumps.
   - All PRs are scanned automatically with **Gitleaks** in CI.
3. **Config-as-Code Validation:** Any change to YAML configuration structures must update the corresponding JSON Schema in `config/schemas/`, the templates in `config/examples/`, and unit tests in `tests/`.

## Development Setup

```bash
# Install dependencies into a local uv virtual environment
uv sync --dev

# Validate example YAML configs against schemas
uv run python scripts/validate_config.py --config-dir config/examples

# Run linter, formatter check, and test suite
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

### Recommended Pre-Commit Hooks

Install [pre-commit](https://pre-commit.com/) (or run via `uvx pre-commit`) to catch secrets, YAML errors, and formatting issues before committing:

```bash
uvx pre-commit install
```

## Pull Request Checklist

- [ ] Code is formatted (`uv run ruff format .`) and passes lint (`uv run ruff check .`).
- [ ] Unit tests pass (`uv run pytest`) and cover new behavior.
- [ ] Schema validation passes (`uv run python scripts/validate_config.py --config-dir config/examples`).
- [ ] Documentation in `README.md` / `docs/` is updated in English when architecture or configuration changes.
- [ ] No real credentials, UUIDs, or personal data appear in the diff.
