"""SQLAlchemy 2.0 ORM models for the FinOps PostgreSQL ledger."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Person(Base):
    __tablename__ = "people"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    default_split_weight: Mapped[Decimal] = mapped_column(
        Numeric(6, 5), nullable=False, default=Decimal("0.50000")
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")

    accounts: Mapped[list[BankAccount]] = relationship(back_populates="person")


class PluggySource(Base):
    __tablename__ = "pluggy_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id"), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    client_id_env: Mapped[str | None] = mapped_column(String(128), nullable=True)
    client_secret_env: Mapped[str | None] = mapped_column(String(128), nullable=True)
    import_dir: Mapped[str | None] = mapped_column(String(256), nullable=True)
    default_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list[PluggyItem]] = relationship(back_populates="source", cascade="all, delete-orphan")
    sync_runs: Mapped[list[SyncRun]] = relationship(back_populates="source", cascade="all, delete-orphan")


class PluggyItem(Base):
    __tablename__ = "pluggy_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("pluggy_sources.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    default_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    connector_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="PENDING")
    execution_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped[PluggySource] = relationship(back_populates="items")
    accounts: Mapped[list[BankAccount]] = relationship(back_populates="pluggy_item")


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    pluggy_item_id: Mapped[str | None] = mapped_column(ForeignKey("pluggy_items.id"), nullable=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("pluggy_sources.id"), nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    person_id: Mapped[str] = mapped_column(ForeignKey("people.id"), nullable=False)
    default_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    account_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subtype: Mapped[str | None] = mapped_column(String(64), nullable=True)
    institution_name: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    current_balance: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal("0.00"))
    is_emergency_fund: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    person: Mapped[Person] = relationship(back_populates="accounts")
    pluggy_item: Mapped[PluggyItem | None] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="account")

    __table_args__ = (UniqueConstraint("source_id", "external_account_id", name="uq_bank_account_source_ext"),)


class RawPluggyEvent(Base):
    __tablename__ = "raw_pluggy_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("pluggy_sources.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, default="transaction")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_raw_event_source_ext"),)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # income | expense
    default_scope: Mapped[str] = mapped_column(String(16), nullable=False)  # shared | personal
    is_annual: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    projection_method: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    monthly_budget_cap: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    warning_threshold_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("80.00"))
    is_discretionary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cut_target_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("20.00"))
    custom_split_weights: Mapped[dict[str, float] | None] = mapped_column(JSONType, nullable=True)

    parent: Mapped[Category | None] = relationship(remote_side="Category.id")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    account_id: Mapped[str] = mapped_column(ForeignKey("bank_accounts.id"), nullable=False)
    raw_event_id: Mapped[str | None] = mapped_column(ForeignKey("raw_pluggy_events.id"), nullable=True)
    external_transaction_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dedup_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    competence_month: Mapped[str] = mapped_column(String(7), nullable=False)  # YYYY-MM
    # Signed normalized amount: positive = income/credit inflow, negative = expense/outflow
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="BRL")
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    provider_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="personal")
    paid_by_person_id: Mapped[str] = mapped_column(ForeignKey("people.id"), nullable=False)
    owner_person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id"), nullable=True)
    installment_group_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    installment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_internal_transfer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    categorization_source: Mapped[str] = mapped_column(String(32), nullable=False, default="uncategorized")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    account: Mapped[BankAccount] = relationship(back_populates="transactions")
    category: Mapped[Category | None] = relationship()

    __table_args__ = (
        Index("ix_transactions_competence_month", "competence_month"),
        Index("ix_transactions_category_id", "category_id"),
        Index("ix_transactions_scope_owner", "scope", "owner_person_id"),
    )


class ProjectionRule(Base):
    __tablename__ = "projection_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    rule_kind: Mapped[str] = mapped_column(String(16), nullable=False)  # recurring | annual
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)  # shared | personal
    owner_person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id"), nullable=True)
    frequency: Mapped[str] = mapped_column(String(16), nullable=False)  # monthly|quarterly|annual
    due_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    valid_from: Mapped[str | None] = mapped_column(String(7), nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String(7), nullable=True)
    smooth_monthly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    annual_adjustment_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal("0.00"))


class ProjectionOverride(Base):
    __tablename__ = "projection_overrides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    competence_month: Mapped[str] = mapped_column(String(7), nullable=False)
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_person_id: Mapped[str | None] = mapped_column(ForeignKey("people.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint(
            "competence_month",
            "category_id",
            "scope",
            "owner_person_id",
            name="uq_projection_override_cell",
        ),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)  # user | hermes | worker
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False)
    diff_payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    source_id: Mapped[str] = mapped_column(ForeignKey("pluggy_sources.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # running | success | error
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upserted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source: Mapped[PluggySource] = relationship(back_populates="sync_runs")
