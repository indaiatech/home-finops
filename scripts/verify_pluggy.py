#!/usr/bin/env python3
"""Verify Meu Pluggy -> Pluggy Dashboard API connectivity for all configured sources.

Reads `sources.yaml` from `--config-dir` (default: `./local`) and credentials from `.env`.
Never prints secrets or raw API keys. Reports item sync status, `consentExpiresAt`,
and discovered accounts for each configured `item_id`.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

ROOT_DIR = Path(__file__).resolve().parent.parent
PLUGGY_API_BASE = "https://api.pluggy.ai"
EXPIRY_WARNING_DAYS = 30


def authenticate(client: httpx.Client, client_id: str, client_secret: str) -> str:
    resp = client.post(
        f"{PLUGGY_API_BASE}/auth",
        json={"clientId": client_id, "clientSecret": client_secret},
    )
    resp.raise_for_status()
    api_key = resp.json().get("apiKey")
    if not api_key:
        raise RuntimeError("Pluggy /auth response did not contain apiKey")
    return str(api_key)


def format_expiry(consent_expires_at: str | None) -> str:
    if not consent_expires_at:
        return "none"
    try:
        dt = datetime.fromisoformat(consent_expires_at.replace("Z", "+00:00"))
    except ValueError:
        return consent_expires_at
    days_left = (dt - datetime.now(UTC)).days
    if days_left < 0:
        return f"[bold red]EXPIRED ({dt.date()})[/bold red]"
    if days_left <= EXPIRY_WARNING_DAYS:
        return f"[bold yellow]{dt.date()} ({days_left}d left)[/bold yellow]"
    return f"[green]{dt.date()} ({days_left}d left)[/green]"


def verify_sources(config_dir: Path, env_file: Path) -> int:
    console = Console()
    load_dotenv(env_file)

    sources_path = config_dir / "sources.yaml"
    if not sources_path.exists():
        console.print(f"[bold red]Missing {sources_path}.[/bold red] Run `./scripts/init_local.sh` first.")
        return 1

    with sources_path.open("r", encoding="utf-8") as fh:
        cfg: dict[str, Any] = yaml.safe_load(fh)

    pluggy_sources = [s for s in cfg.get("sources", []) if s.get("provider") == "pluggy_api"]
    if not pluggy_sources:
        console.print("[yellow]No pluggy_api sources configured.[/yellow]")
        return 0

    table = Table(title="Pluggy Personal API Connectivity Check")
    table.add_column("Source", style="cyan")
    table.add_column("Person")
    table.add_column("Label")
    table.add_column("Connector")
    table.add_column("Status")
    table.add_column("Consent Expires")
    table.add_column("Accounts", justify="right")

    has_failure = False

    with httpx.Client(timeout=30.0) as client:
        for source in pluggy_sources:
            sid = source["id"]
            person_id = source["person_id"]
            cid_env = source["client_id_env"]
            csec_env = source["client_secret_env"]

            client_id = os.getenv(cid_env, "").strip()
            client_secret = os.getenv(csec_env, "").strip()

            if (
                not client_id
                or not client_secret
                or client_id.startswith("replace_with_")
                or client_secret.startswith("replace_with_")
            ):
                has_failure = True
                table.add_row(
                    sid,
                    person_id,
                    "-",
                    "-",
                    f"[bold red]MISSING ENV ({cid_env} / {csec_env})[/bold red]",
                    "-",
                    "0",
                )
                continue

            try:
                api_key = authenticate(client, client_id, client_secret)
            except httpx.HTTPError as exc:
                has_failure = True
                table.add_row(
                    sid,
                    person_id,
                    "-",
                    "-",
                    f"[bold red]AUTH FAILED ({exc.__class__.__name__})[/bold red]",
                    "-",
                    "0",
                )
                continue

            headers = {"X-API-KEY": api_key}
            for item_cfg in source.get("items", []):
                item_id = item_cfg["item_id"]
                label = item_cfg["label"]

                try:
                    item_resp = client.get(f"{PLUGGY_API_BASE}/items/{item_id}", headers=headers)
                    item_resp.raise_for_status()
                    item_data = item_resp.json()

                    acct_resp = client.get(
                        f"{PLUGGY_API_BASE}/accounts",
                        params={"itemId": item_id},
                        headers=headers,
                    )
                    acct_resp.raise_for_status()
                    accounts = acct_resp.json().get("results", [])

                    connector_name = item_data.get("connector", {}).get("name", "unknown")
                    status = item_data.get("status", "UNKNOWN")
                    exec_status = item_data.get("executionStatus")
                    status_display = f"{status}" + (f" ({exec_status})" if exec_status else "")
                    if status != "UPDATED":
                        status_display = f"[yellow]{status_display}[/yellow]"
                    else:
                        status_display = f"[green]{status_display}[/green]"

                    table.add_row(
                        sid,
                        person_id,
                        label,
                        connector_name,
                        status_display,
                        format_expiry(item_data.get("consentExpiresAt")),
                        str(len(accounts)),
                    )
                except httpx.HTTPStatusError as exc:
                    has_failure = True
                    table.add_row(
                        sid,
                        person_id,
                        label,
                        "-",
                        f"[bold red]HTTP {exc.response.status_code}[/bold red]",
                        "-",
                        "0",
                    )
                except httpx.HTTPError as exc:
                    has_failure = True
                    table.add_row(
                        sid,
                        person_id,
                        label,
                        "-",
                        f"[bold red]ERROR ({exc.__class__.__name__})[/bold red]",
                        "-",
                        "0",
                    )

    console.print(table)
    return 1 if has_failure else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Pluggy API credentials and items.")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=ROOT_DIR / "local",
        help="Directory containing sources.yaml (default: ./local).",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT_DIR / ".env",
        help="Path to .env file (default: ./.env).",
    )
    args = parser.parse_args()
    return verify_sources(args.config_dir, args.env_file)


if __name__ == "__main__":
    sys.exit(main())
