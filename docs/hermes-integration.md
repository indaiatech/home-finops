# Hermes Agent Integration Guide

FinOps integrates natively with **Hermes Agent** (`~/.hermes`) through a dedicated **Model Context Protocol (MCP)** server (`finops-mcp`) and a versioned Hermes Skill (`integrations/hermes/skills/finops/`).

---

## Why a Dedicated `finops-mcp` Server?

1. **Unified Household Context:** Consolidates both Meu Pluggy accounts, internal-transfer deduplication, 24-month projections, and automatic shared-expense settlement behind one typed interface.
2. **Pluggy's Hosted MCP Is Docs-Only:** Pluggy's official MCP (`https://mcp.pluggy.ai/mcp`) provides OpenAPI docs and developer diagnostics—it does **not** return personal financial transactions.
3. **Audited & Safe Writes:** Every mutation requested by Hermes (categorizing a transaction or setting a projection override) is authenticated via Bearer token, validated by `finops-api`, and logged in PostgreSQL's `audit_log` table with `actor = 'hermes'`.

---

## Planned MCP Tools (v1)

### Read & Simulation Tools
- `get_spreadsheet_summary(year, scope, person_id, annual_mode)` — 24-month realized vs. projected summary.
- `get_monthly_settlement(month)` — Shared-expense split calculation and net transfer recommendation between household members.
- `list_transactions(month, category_id, scope, person_id, uncategorized_only)` — Filtered transaction search.
- `get_upcoming_annual_expenses(days_ahead)` — Upcoming annual/seasonal outflows (taxes, insurance, vacations).
- `get_budget_alerts(month, threshold_pct)` — Subcategories approaching or exceeding monthly projections.
- `get_sync_health()` — Sync timestamps and `consentExpiresAt` countdown for both Pluggy accounts.
- `simulate_projection_change(description, monthly_amount, start_month, months, scope)` — Non-persistent "what-if" cash-flow simulation.

### Audited Write Tools
- `categorize_transaction(transaction_id, category_id, scope, owner_person_id)` — Classify a transaction and recompute projections & settlement.
- `propose_rule_yaml(pattern, category_id, scope)` — Draft a validated `rules.yaml` snippet for future auto-categorization.
- `set_projection_override(month, category_id, scope, owner_person_id, amount, note)` — Override a future spreadsheet projection cell.
- `trigger_sync(source_id)` — Pull the latest synced data from Pluggy into PostgreSQL on demand.

---

## Configuration

1. Generate a strong random token and place the same value in both FinOps `.env` and `~/.hermes/.env`:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   ```dotenv
   FINOPS_MCP_TOKEN=<strong-random-token>
   ```
2. Start the stack (`docker compose up -d --build`) so `finops-mcp` is listening on `http://127.0.0.1:8090/mcp`.
3. Add the snippet from [integrations/hermes/config.snippet.yaml](../integrations/hermes/config.snippet.yaml) to `~/.hermes/config.yaml`.
4. Copy or symlink the versioned skill into Hermes:
   ```bash
   ln -s "$(pwd)/integrations/hermes/skills/finops" ~/.hermes/skills/finops
   ```
5. Reload and verify in Hermes:
   ```bash
   hermes mcp test finops
   ```
