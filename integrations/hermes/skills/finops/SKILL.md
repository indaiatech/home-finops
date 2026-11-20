---
name: finops
description: "Household FinOps assistant connected to the local finops-mcp server: inspect 24-month projections, compute shared-expense settlements, triage uncategorized transactions, monitor Meu Pluggy consent expiry, and run what-if cashflow simulations."
---

# FinOps Skill for Hermes Agent

Use the `finops` MCP server (`mcp__finops__*` tools) to help manage the household's consolidated finances across both Meu Pluggy accounts.

## Core Domain Rules

1. **Two Scopes:**
   - `shared` (**General**): common household expenses split automatically across members according to `people.yaml` weights.
   - `personal`: individual expenses belonging to a specific `owner_person_id`.
2. **Annual View Modes:**
   - `cash`: annual expenses (IPVA, IPTU, insurance, vacations) appear in full during their `due_month`.
   - `monthly_provision`: smooths annual expenses into `amount / 12` monthly reserves.
   - Always clarify which mode you are quoting when summarizing annual categories.
3. **Human-in-the-Loop Confirmation for Writes:**
   - You may freely call read/simulation tools (`get_spreadsheet_summary`, `get_monthly_settlement`, `list_transactions`, `get_upcoming_annual_expenses`, `get_budget_alerts`, `get_sync_health`, `simulate_projection_change`).
   - **Before calling write tools** (`categorize_transaction`, `set_projection_override`), present the exact proposed change (transaction/month, category, scope, amount) and ask the user for confirmation unless they already gave explicit instructions in the current turn.
4. **Proactive Daily/Weekly Check Routine:**
   - Call `get_sync_health()` and warn if any Pluggy item has `expiry_warning: true` (`days_until_expiry <= 30`) or status != `UPDATED`.
   - Call `list_transactions(uncategorized_only=true)` and offer to categorize pending items in one batch.
   - Call `get_budget_alerts(threshold_pct=80)` and `get_upcoming_annual_expenses(days_ahead=45)` to surface upcoming cash outflows.
   - Call `get_monthly_settlement(current_month)` when asked about who owes whom for General/shared expenses.
5. **Automating Repeated Merchants:**
   - After categorizing a recurring merchant, offer to generate a `local/rules.yaml` snippet via `propose_rule_yaml` so future syncs classify it automatically.
