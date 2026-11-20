"""Resilient transaction fingerprinting and credit-card installment parsing."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from decimal import Decimal
from typing import Any

_WHITESPACE_RE = re.compile(r"\s+")
_INSTALLMENT_PATTERNS = (
    re.compile(r"(?i)\bparc(?:ela)?\.?\s*(\d{1,2})\s*(?:/|de)\s*(\d{1,2})\b"),
    re.compile(r"\((\d{1,2})\s*/\s*(\d{1,2})\)"),
    re.compile(r"(?<!\d)(\d{1,2})\s*/\s*(\d{1,2})(?!\d)"),
)


def normalize_description(description: str) -> str:
    return _WHITESPACE_RE.sub(" ", description.strip().lower())


def build_dedup_fingerprint(
    *,
    person_id: str,
    account_key: str,
    tx_date: date,
    amount: Decimal,
    description: str,
    occurrence: int = 0,
) -> str:
    """Build a deterministic SHA-256 fingerprint independent of Pluggy `item_id`.

    Survives annual `MeuPluggy` re-linking even if Pluggy assigns a new `item_id`.
    """
    norm_desc = normalize_description(description)
    raw = f"{person_id}|{account_key.lower()}|{tx_date.isoformat()}|{amount:.2f}|{norm_desc}|{occurrence}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_installment(
    description: str,
    credit_card_metadata: dict[str, Any] | None = None,
) -> tuple[str | None, int | None, int | None]:
    """Extract `(installment_group_id, installment_number, installment_total)`.

    Prefers structured Pluggy `creditCardMetadata`, falling back to regex parsing
    of Brazilian credit-card descriptions (e.g., `LOJA XYZ PARC 3/10`).
    """
    inst_num: int | None = None
    inst_total: int | None = None

    if credit_card_metadata:
        raw_num = credit_card_metadata.get("installmentNumber")
        raw_total = credit_card_metadata.get("totalInstallments")
        if isinstance(raw_num, int) and isinstance(raw_total, int) and 1 <= raw_num <= raw_total and raw_total > 1:
            inst_num, inst_total = raw_num, raw_total

    if inst_num is None:
        for pat in _INSTALLMENT_PATTERNS:
            match = pat.search(description)
            if match:
                n = int(match.group(1))
                t = int(match.group(2))
                if 1 <= n <= t <= 48 and t > 1 and not (n > 12 and t <= 12):
                    inst_num, inst_total = n, t
                    break

    if inst_num is None or inst_total is None:
        return None, None, None

    # Strip the installment marker so all installments share a stable group key
    base_desc = normalize_description(description)
    for pat in _INSTALLMENT_PATTERNS:
        base_desc = pat.sub("", base_desc)
    base_desc = _WHITESPACE_RE.sub(" ", base_desc).strip()
    group_hash = hashlib.sha256(f"{base_desc}|{inst_total}".encode()).hexdigest()[:24]
    return group_hash, inst_num, inst_total
