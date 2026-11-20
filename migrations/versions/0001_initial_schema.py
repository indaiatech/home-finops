"""Initial FinOps PostgreSQL schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "people",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("default_split_weight", sa.Numeric(6, 5), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BRL"),
    )

    op.create_table(
        "pluggy_sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("person_id", sa.String(64), sa.ForeignKey("people.id"), nullable=False),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("client_id_env", sa.String(128), nullable=True),
        sa.Column("client_secret_env", sa.String(128), nullable=True),
        sa.Column("import_dir", sa.String(256), nullable=True),
        sa.Column("default_scope", sa.String(16), nullable=False, server_default="personal"),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "pluggy_items",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("pluggy_sources.id"), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("default_scope", sa.String(16), nullable=False, server_default="personal"),
        sa.Column("connector_name", sa.String(128), nullable=True),
        sa.Column("status", sa.String(64), nullable=False, server_default="PENDING"),
        sa.Column("execution_status", sa.String(64), nullable=True),
        sa.Column("consent_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("pluggy_item_id", sa.String(64), sa.ForeignKey("pluggy_items.id"), nullable=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("pluggy_sources.id"), nullable=False),
        sa.Column("external_account_id", sa.String(128), nullable=False),
        sa.Column("person_id", sa.String(64), sa.ForeignKey("people.id"), nullable=False),
        sa.Column("default_scope", sa.String(16), nullable=False, server_default="personal"),
        sa.Column("account_type", sa.String(32), nullable=False),
        sa.Column("subtype", sa.String(64), nullable=True),
        sa.Column("institution_name", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BRL"),
        sa.Column("current_balance", sa.Numeric(14, 2), nullable=False, server_default="0.00"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "external_account_id", name="uq_bank_account_source_ext"),
    )

    op.create_table(
        "raw_pluggy_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("pluggy_sources.id"), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False, server_default="transaction"),
        sa.Column("payload", JSON_TYPE, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "external_id", name="uq_raw_event_source_ext"),
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("parent_id", sa.String(128), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("default_scope", sa.String(16), nullable=False),
        sa.Column("is_annual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("projection_method", sa.String(32), nullable=False, server_default="none"),
        sa.Column("monthly_budget_cap", sa.Numeric(14, 2), nullable=True),
        sa.Column("custom_split_weights", JSON_TYPE, nullable=True),
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("bank_accounts.id"), nullable=False),
        sa.Column("raw_event_id", sa.String(36), sa.ForeignKey("raw_pluggy_events.id"), nullable=True),
        sa.Column("external_transaction_id", sa.String(128), nullable=True),
        sa.Column("dedup_fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("competence_month", sa.String(7), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="BRL"),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("provider_category", sa.String(128), nullable=True),
        sa.Column("category_id", sa.String(128), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("scope", sa.String(16), nullable=False, server_default="personal"),
        sa.Column("paid_by_person_id", sa.String(64), sa.ForeignKey("people.id"), nullable=False),
        sa.Column("owner_person_id", sa.String(64), sa.ForeignKey("people.id"), nullable=True),
        sa.Column("installment_group_id", sa.String(64), nullable=True),
        sa.Column("installment_number", sa.Integer(), nullable=True),
        sa.Column("installment_total", sa.Integer(), nullable=True),
        sa.Column("is_internal_transfer", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("categorization_source", sa.String(32), nullable=False, server_default="uncategorized"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_transactions_competence_month", "transactions", ["competence_month"])
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])
    op.create_index("ix_transactions_scope_owner", "transactions", ["scope", "owner_person_id"])

    op.create_table(
        "projection_rules",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("rule_kind", sa.String(16), nullable=False),
        sa.Column("category_id", sa.String(128), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("owner_person_id", sa.String(64), sa.ForeignKey("people.id"), nullable=True),
        sa.Column("frequency", sa.String(16), nullable=False),
        sa.Column("due_month", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("valid_from", sa.String(7), nullable=True),
        sa.Column("valid_to", sa.String(7), nullable=True),
        sa.Column("smooth_monthly", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("annual_adjustment_pct", sa.Numeric(6, 2), nullable=False, server_default="0.00"),
    )

    op.create_table(
        "projection_overrides",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("competence_month", sa.String(7), nullable=False),
        sa.Column("category_id", sa.String(128), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("owner_person_id", sa.String(64), sa.ForeignKey("people.id"), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(32), nullable=False, server_default="user"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "competence_month",
            "category_id",
            "scope",
            "owner_person_id",
            name="uq_projection_override_cell",
        ),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor", sa.String(32), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("diff_payload", JSON_TYPE, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("pluggy_sources.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("fetched_count", sa.Integer(), nullable=False, default=0),
        sa.Column("upserted_count", sa.Integer(), nullable=False, default=0),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sync_runs")
    op.drop_table("audit_log")
    op.drop_table("projection_overrides")
    op.drop_table("projection_rules")
    op.drop_index("ix_transactions_scope_owner", table_name="transactions")
    op.drop_index("ix_transactions_category_id", table_name="transactions")
    op.drop_index("ix_transactions_competence_month", table_name="transactions")
    op.drop_table("transactions")
    op.drop_table("categories")
    op.drop_table("raw_pluggy_events")
    op.drop_table("bank_accounts")
    op.drop_table("pluggy_items")
    op.drop_table("pluggy_sources")
    op.drop_table("people")
