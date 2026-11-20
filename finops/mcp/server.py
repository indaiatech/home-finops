"""FinOps MCP Server (Streamable HTTP) for Hermes Agent integration.

Exposes typed read, simulation, and audited write tools backed by `finops-api`.
Authenticated via Bearer token (`FINOPS_MCP_TOKEN`).
"""

from __future__ import annotations

import hmac
from typing import Any

import httpx
import uvicorn
import yaml
from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from finops.settings import get_settings

mcp = MCPServer(
    name="finops",
    title="FinOps Household Finance MCP",
    instructions=(
        "Query consolidated 24-month household finances, shared-expense settlements, "
        "annual expenses, budget alerts, Pluggy sync health, and perform audited "
        "categorization or projection overrides after user confirmation."
    ),
)


def _api_request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = get_settings().finops_api_base_url.rstrip("/")
    clean_params = {k: v for k, v in (params or {}).items() if v is not None}
    with httpx.Client(timeout=30.0) as client:
        resp = client.request(
            method,
            f"{base}{path}",
            params=clean_params,
            json=json_body,
            headers={"X-FinOps-Actor": "hermes"},
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Read & Simulation Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_spreadsheet_summary(
    year: int | None = None,
    scope: str = "all",
    person_id: str | None = None,
    annual_mode: str = "cash",
) -> dict[str, Any]:
    """Get the 24-month household spreadsheet summary (current year + next year).

    Args:
        year: Base calendar year (defaults to current year).
        scope: Filter rows by 'all', 'shared', 'personal', or 'annual'.
        person_id: Optional household member ID (e.g., 'person_a').
        annual_mode: 'cash' (full outflow in due month) or 'monthly_provision' (1/12 monthly).
    """
    matrix = _api_request(
        "GET",
        "/api/spreadsheet",
        params={
            "base_year": year,
            "scope_filter": scope,
            "person_id": person_id,
            "annual_mode": annual_mode,
        },
    )
    # Return a compact, LLM-friendly view preserving totals, settlement, and per-row yearly totals
    return {
        "base_year": matrix["base_year"],
        "next_year": matrix["next_year"],
        "current_month": matrix["current_month"],
        "currency": matrix["currency"],
        "annual_mode": matrix["annual_mode"],
        "uncategorized_count": matrix["uncategorized_count"],
        "starting_cash_balance": matrix["starting_cash_balance"],
        "wealth_summary": matrix.get("wealth_summary"),
        "current_month_settlement": matrix["current_month_settlement"],
        "monthly_summary": matrix["summary"],
        "rows": [
            {
                "section": r["section"],
                "category_id": r["category_id"],
                "name": f"{r['parent_category_name']} > {r['category_name']}",
                "scope": r["scope"],
                "owner": r["owner_display_name"],
                "is_annual": r["is_annual"],
                "current_month_value": r["cells"][matrix["current_month"]]["value"],
                "total_year_1": r["total_year_1"],
                "total_year_2": r["total_year_2"],
                "monthly_avg": r["monthly_avg"],
            }
            for r in matrix["rows"]
        ],
    }


@mcp.tool()
def get_monthly_settlement(month: str) -> dict[str, Any]:
    """Compute automatic shared-expense split and net transfer between household members for YYYY-MM."""
    return _api_request("GET", f"/api/settlement/{month}")


@mcp.tool()
def list_transactions(
    month: str | None = None,
    category_id: str | None = None,
    scope: str | None = None,
    person_id: str | None = None,
    uncategorized_only: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """List normalized household transactions (excluding internal transfers by default)."""
    return _api_request(
        "GET",
        "/api/transactions",
        params={
            "month": month,
            "category_id": category_id,
            "scope": scope,
            "person_id": person_id,
            "uncategorized_only": uncategorized_only,
            "limit": limit,
        },
    )


@mcp.tool()
def get_upcoming_annual_expenses(days_ahead: int = 90) -> dict[str, Any]:
    """List upcoming annual/seasonal expenses (taxes, insurance, vacations) within `days_ahead` days."""
    return _api_request("GET", "/api/annual/upcoming", params={"days_ahead": days_ahead})


@mcp.tool()
def get_budget_alerts(month: str | None = None, threshold_pct: float = 80.0) -> dict[str, Any]:
    """Identify expense subcategories that have reached or exceeded `threshold_pct`% of their monthly projection."""
    return _api_request(
        "GET",
        "/api/alerts/budget",
        params={"month": month, "threshold_pct": threshold_pct},
    )


@mcp.tool()
def get_sync_health() -> dict[str, Any]:
    """Check Meu Pluggy connection health, last sync timestamps, and 1-year consent expiration countdown."""
    return _api_request("GET", "/api/sync/health")


@mcp.tool()
def simulate_projection_change(
    description: str,
    monthly_amount: float,
    start_month: str,
    months_count: int,
    kind: str = "expense",
) -> dict[str, Any]:
    """Run a non-persistent what-if simulation across the 24-month cashflow horizon."""
    return _api_request(
        "POST",
        "/api/simulate",
        json_body={
            "description": description,
            "monthly_amount": monthly_amount,
            "start_month": start_month,
            "months_count": months_count,
            "kind": kind,
        },
    )


# ---------------------------------------------------------------------------
# Audited Write Tools (always confirm with user before invoking via Skill)
# ---------------------------------------------------------------------------


@mcp.tool()
def categorize_transaction(
    transaction_id: str,
    category_id: str,
    scope: str,
    owner_person_id: str | None = None,
) -> dict[str, Any]:
    """Categorize a transaction and update its scope ('shared' or 'personal'). Logged to audit_log."""
    return _api_request(
        "PATCH",
        f"/api/transactions/{transaction_id}",
        json_body={
            "category_id": category_id,
            "scope": scope,
            "owner_person_id": owner_person_id,
        },
    )


@mcp.tool()
def propose_rule_yaml(
    pattern: str,
    category_id: str,
    scope: str,
    owner_person_id: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Validate a regex and produce a ready-to-paste `local/rules.yaml` auto-categorization snippet."""
    res = _api_request(
        "POST",
        "/api/rules/draft",
        json_body={
            "pattern": pattern,
            "category_id": category_id,
            "scope": scope,
            "owner_person_id": owner_person_id,
            "description": description,
        },
    )
    yaml_text = yaml.safe_dump([res["yaml_entry"]], sort_keys=False)
    return {"yaml_snippet": yaml_text, "entry": res["yaml_entry"]}


@mcp.tool()
def set_projection_override(
    month: str,
    category_id: str,
    scope: str,
    amount: float,
    owner_person_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Override a projected cell value in the 24-month spreadsheet. Logged to audit_log."""
    return _api_request(
        "PUT",
        "/api/spreadsheet/override",
        json_body={
            "competence_month": month,
            "category_id": category_id,
            "scope": scope,
            "owner_person_id": owner_person_id,
            "amount": amount,
            "note": note,
        },
    )


@mcp.tool()
def trigger_sync(source_id: str | None = None) -> dict[str, Any]:
    """Pull the latest synced Meu Pluggy data from Pluggy API into PostgreSQL on demand."""
    return _api_request(
        "POST",
        "/api/sync/trigger",
        json_body={"source_id": source_id} if source_id else {},
    )


# ---------------------------------------------------------------------------
# Starlette ASGI App with Bearer Token Middleware + Health Endpoint
# ---------------------------------------------------------------------------


class BearerAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        expected = get_settings().finops_mcp_token.strip()
        if expected and not expected.startswith("replace_with_"):
            auth_header = request.headers.get("Authorization", "")
            provided = auth_header.removeprefix("Bearer ").strip() if auth_header.startswith("Bearer ") else ""
            if not provided or not hmac.compare_digest(provided, expected):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


async def _health_endpoint(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "finops-mcp"})


def create_app():
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        host="0.0.0.0",
    )
    app.routes.insert(0, Route("/health", _health_endpoint, methods=["GET"]))
    app.add_middleware(BearerAuthMiddleware)
    return app


asgi_app = create_app()


def main() -> None:
    port = get_settings().finops_mcp_port
    uvicorn.run(asgi_app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
