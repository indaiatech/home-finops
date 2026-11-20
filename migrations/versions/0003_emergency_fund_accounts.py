"""Add is_emergency_fund flag to bank_accounts (default true).

Revision ID: 0003_emergency_fund
Revises: 0002_category_thresholds
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_emergency_fund"
down_revision: str | Sequence[str] | None = "0002_category_thresholds"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bank_accounts",
        sa.Column(
            "is_emergency_fund",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade() -> None:
    op.drop_column("bank_accounts", "is_emergency_fund")
