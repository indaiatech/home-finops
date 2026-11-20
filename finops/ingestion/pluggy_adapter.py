"""Multi-account Pluggy Personal Use API ingestion adapter."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.orm import Session

from finops.config.loader import LoadedConfig
from finops.db.models import (
    BankAccount,
    Category,
    PluggyItem,
    PluggySource,
    RawPluggyEvent,
    SyncRun,
    Transaction,
)
from finops.ingestion.categorizer import (
    PROTECTED_SOURCES,
    apply_rules_to_transaction,
    detect_inter_account_transfers,
)
from finops.ingestion.fingerprints import build_dedup_fingerprint, parse_installment
from finops.settings import get_settings


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_tx_date(value: str) -> date:
    if "T" in value:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    return date.fromisoformat(value[:10])


def normalize_pluggy_amount(
    raw_amount: Any,
    tx_type: str | None,
    account_type: str,
) -> Decimal:
    """Normalize Pluggy amount to signed decimal: negative = outflow, positive = inflow."""
    amt = Decimal(str(raw_amount)).quantize(Decimal("0.01"))
    kind = (tx_type or "").upper()
    if kind == "DEBIT":
        return -abs(amt)
    if kind == "CREDIT":
        return abs(amt)
    if account_type.upper() == "CREDIT":
        return -amt
    return amt


class PluggyApiAdapter:
    """Pulls items, accounts, and transactions from Pluggy REST API for configured sources."""

    def __init__(self, api_base_url: str | None = None, timeout: float = 30.0) -> None:
        self.api_base_url = (api_base_url or get_settings().pluggy_api_base_url).rstrip("/")
        self.timeout = timeout

    def authenticate(self, client: httpx.Client, client_id: str, client_secret: str) -> str:
        resp = client.post(
            f"{self.api_base_url}/auth",
            json={"clientId": client_id, "clientSecret": client_secret},
        )
        resp.raise_for_status()
        api_key = resp.json().get("apiKey")
        if not api_key:
            raise RuntimeError("Pluggy /auth response did not include apiKey")
        return str(api_key)

    def fetch_all_transactions(
        self,
        client: httpx.Client,
        headers: dict[str, str],
        account_id: str,
    ) -> list[dict[str, Any]]:
        """Fetch all transactions using Pluggy's cursor-paginated `GET /v2/transactions`."""
        results: list[dict[str, Any]] = []
        url = f"{self.api_base_url}/v2/transactions"
        params: dict[str, Any] | None = {"accountId": account_id}
        seen_cursors: set[str] = set()

        while True:
            resp = client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            body = resp.json()
            batch = body.get("results", [])
            results.extend(batch)

            next_cursor = body.get("next")
            if not next_cursor or not batch:
                break
            cursor_str = str(next_cursor)
            if cursor_str in seen_cursors:
                break
            seen_cursors.add(cursor_str)

            if cursor_str.startswith("http"):
                url = cursor_str
                params = None
            elif cursor_str.startswith("?"):
                url = f"{self.api_base_url}/v2/transactions{cursor_str}"
                params = None
            else:
                url = f"{self.api_base_url}/v2/transactions"
                params = {"accountId": account_id, "after": cursor_str}

        return results

    def sync_source(
        self,
        db: Session,
        bundle: LoadedConfig,
        source_id: str,
        client: httpx.Client | None = None,
    ) -> dict[str, Any]:
        source = db.get(PluggySource, source_id)
        if source is None:
            raise ValueError(f"Unknown source_id: {source_id}")
        if source.provider_type != "pluggy_api":
            return {"source_id": source_id, "status": "skipped", "reason": "not pluggy_api"}

        run = SyncRun(source_id=source_id, status="running", started_at=datetime.now(UTC))
        db.add(run)
        db.commit()

        client_id = os.getenv(source.client_id_env or "", "").strip()
        client_secret = os.getenv(source.client_secret_env or "", "").strip()
        if (
            not client_id
            or not client_secret
            or client_id.startswith("replace_with_")
            or client_secret.startswith("replace_with_")
        ):
            run.status = "skipped"
            run.error_message = f"Missing credentials in env ({source.client_id_env} / {source.client_secret_env})"
            run.finished_at = datetime.now(UTC)
            db.commit()
            return {
                "source_id": source_id,
                "status": "skipped",
                "error": run.error_message,
            }

        categories_by_id = {c.id: c for c in db.query(Category).all()}
        fetched = 0
        upserted = 0
        own_client = client is None
        http = client or httpx.Client(timeout=self.timeout)

        try:
            api_key = self.authenticate(http, client_id, client_secret)
            headers = {"X-API-KEY": api_key}

            items = db.query(PluggyItem).filter(PluggyItem.source_id == source_id).all()
            for item in items:
                item_resp = http.get(f"{self.api_base_url}/items/{item.id}", headers=headers)
                item_resp.raise_for_status()
                item_data = item_resp.json()

                item.connector_name = (item_data.get("connector") or {}).get("name")
                item.status = item_data.get("status", "UNKNOWN")
                item.execution_status = item_data.get("executionStatus")
                item.consent_expires_at = _parse_iso_dt(item_data.get("consentExpiresAt"))
                item.last_updated_at = _parse_iso_dt(item_data.get("lastUpdatedAt"))

                acct_resp = http.get(
                    f"{self.api_base_url}/accounts",
                    params={"itemId": item.id},
                    headers=headers,
                )
                acct_resp.raise_for_status()
                accounts_data = acct_resp.json().get("results", [])

                for acct_data in accounts_data:
                    ext_acct_id = str(acct_data["id"])
                    account = (
                        db.query(BankAccount)
                        .filter(
                            BankAccount.source_id == source_id,
                            BankAccount.external_account_id == ext_acct_id,
                        )
                        .one_or_none()
                    )
                    if account is None:
                        account = BankAccount(
                            source_id=source_id,
                            external_account_id=ext_acct_id,
                            person_id=source.person_id,
                            default_scope=item.default_scope,
                            account_type=str(acct_data.get("type", "BANK")),
                            institution_name=(
                                (acct_data.get("bankData") or {}).get("name") or item.connector_name or item.label
                            ),
                            name=str(acct_data.get("name") or item.label),
                        )
                        db.add(account)

                    account.pluggy_item_id = item.id
                    account.account_type = str(acct_data.get("type", account.account_type))
                    account.subtype = acct_data.get("subtype")
                    account.name = str(acct_data.get("name") or account.name)
                    account.currency = str(acct_data.get("currencyCode") or "BRL")
                    account.current_balance = Decimal(str(acct_data.get("balance") or 0)).quantize(Decimal("0.01"))
                    account.updated_at = datetime.now(UTC)
                    db.flush()

                    raw_txs = self.fetch_all_transactions(http, headers, ext_acct_id)
                    fetched += len(raw_txs)

                    occurrence_counts: dict[tuple[str, str, str], int] = defaultdict(int)
                    account_key = f"{account.account_type}:{account.name}"

                    for tx_data in raw_txs:
                        ext_tx_id = str(tx_data["id"])
                        raw_event = (
                            db.query(RawPluggyEvent)
                            .filter(
                                RawPluggyEvent.source_id == source_id,
                                RawPluggyEvent.external_id == ext_tx_id,
                            )
                            .one_or_none()
                        )
                        if raw_event is None:
                            raw_event = RawPluggyEvent(
                                source_id=source_id,
                                external_id=ext_tx_id,
                                event_type="transaction",
                                payload=tx_data,
                            )
                            db.add(raw_event)
                            db.flush()
                        else:
                            raw_event.payload = tx_data
                            raw_event.fetched_at = datetime.now(UTC)

                        tx_date = _parse_tx_date(str(tx_data["date"]))
                        amount = normalize_pluggy_amount(
                            tx_data.get("amount", 0),
                            tx_data.get("type"),
                            account.account_type,
                        )
                        description = str(
                            tx_data.get("description") or tx_data.get("descriptionRaw") or "Unknown"
                        ).strip()

                        occ_key = (tx_date.isoformat(), f"{amount:.2f}", description.lower())
                        occ = occurrence_counts[occ_key]
                        occurrence_counts[occ_key] += 1

                        fingerprint = build_dedup_fingerprint(
                            person_id=source.person_id,
                            account_key=account_key,
                            tx_date=tx_date,
                            amount=amount,
                            description=description,
                            occurrence=occ,
                        )

                        # Prefer matching by external_transaction_id, then fingerprint
                        existing_tx = (
                            db.query(Transaction)
                            .filter(
                                Transaction.account_id == account.id,
                                Transaction.external_transaction_id == ext_tx_id,
                            )
                            .one_or_none()
                        )
                        if existing_tx is None:
                            existing_tx = (
                                db.query(Transaction)
                                .filter(Transaction.dedup_fingerprint == fingerprint)
                                .one_or_none()
                            )

                        group_id, inst_num, inst_total = parse_installment(
                            description, tx_data.get("creditCardMetadata")
                        )

                        if existing_tx is None:
                            tx = Transaction(
                                account_id=account.id,
                                raw_event_id=raw_event.id,
                                external_transaction_id=ext_tx_id,
                                dedup_fingerprint=fingerprint,
                                transaction_date=tx_date,
                                competence_month=tx_date.strftime("%Y-%m"),
                                amount=amount,
                                currency=str(tx_data.get("currencyCode") or account.currency),
                                description=description,
                                provider_category=tx_data.get("category"),
                                scope=account.default_scope,
                                paid_by_person_id=source.person_id,
                                owner_person_id=(None if account.default_scope == "shared" else source.person_id),
                                installment_group_id=group_id,
                                installment_number=inst_num,
                                installment_total=inst_total,
                            )
                            apply_rules_to_transaction(tx, bundle, categories_by_id)
                            db.add(tx)
                            upserted += 1
                        else:
                            existing_tx.raw_event_id = raw_event.id
                            existing_tx.external_transaction_id = ext_tx_id
                            existing_tx.provider_category = tx_data.get("category")
                            existing_tx.installment_group_id = group_id
                            existing_tx.installment_number = inst_num
                            existing_tx.installment_total = inst_total
                            if existing_tx.categorization_source not in PROTECTED_SOURCES:
                                apply_rules_to_transaction(existing_tx, bundle, categories_by_id)
                            upserted += 1

            detect_inter_account_transfers(db, bundle)
            source.last_synced_at = datetime.now(UTC)
            run.status = "success"
            run.fetched_count = fetched
            run.upserted_count = upserted
            run.finished_at = datetime.now(UTC)
            db.commit()
            return {
                "source_id": source_id,
                "status": "success",
                "fetched": fetched,
                "upserted": upserted,
            }
        except Exception as exc:
            db.rollback()
            err_run = db.get(SyncRun, run.id)
            if err_run is not None:
                err_run.status = "error"
                err_run.error_message = str(exc)
                err_run.finished_at = datetime.now(UTC)
                db.commit()
            return {
                "source_id": source_id,
                "status": "error",
                "error": str(exc),
            }
        finally:
            if own_client:
                http.close()

    def sync_all(self, db: Session, bundle: LoadedConfig) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        sources = db.query(PluggySource).filter(PluggySource.provider_type == "pluggy_api").all()
        for source in sources:
            results.append(self.sync_source(db, bundle, source.id))
        return results
