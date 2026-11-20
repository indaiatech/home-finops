"""Add threshold alarm and cost-cutting metadata columns to categories.

Revision ID: 0002_category_thresholds
Revises: 0001_initial_schema
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_category_thresholds"
down_revision: str | Sequence[str] | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column(
            "warning_threshold_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="80.00",
        ),
    )
    op.add_column(
        "categories",
        sa.Column(
            "is_discretionary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "categories",
        sa.Column(
            "cut_target_pct",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="20.00",
        ),
    )


def downgrade() -> None:
    op.drop_column("categories", "cut_target_pct")
    op.drop_column("categories", "is_discretionary")
    op.drop_column("categories", "warning_threshold_pct")
