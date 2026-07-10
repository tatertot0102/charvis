"""calendar_snapshots + commitments (Phase 2D.2 — truthful calendar state)

Adds the provider-backed calendar snapshot cache (the only source of truth for week/schedule
answers) and the durable commitments table (life understanding that a calendar deletion can never
erase). Both are additive; no existing table changes.

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "calendar_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("provider_event_id", sa.String(length=1024), nullable=False),
        sa.Column("recurring_event_id", sa.String(length=1024), nullable=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("attendees", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="confirmed"),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("account", "provider_event_id", name="uq_snapshot_account_event"),
    )
    op.create_index("ix_calendar_snapshots_account", "calendar_snapshots", ["account"])
    op.create_index("ix_calendar_snapshots_start", "calendar_snapshots", ["start"])

    op.create_table(
        "commitments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("key", sa.String(length=320), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=True),
        sa.Column("schedule_summary", sa.Text(), nullable=True),
        sa.Column("recurrence", sa.Text(), nullable=True),
        sa.Column("contexts", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("linked_event_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("linked_email_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("account", "key", name="uq_commitment_account_key"),
    )
    op.create_index("ix_commitments_account", "commitments", ["account"])


def downgrade() -> None:
    op.drop_index("ix_commitments_account", table_name="commitments")
    op.drop_table("commitments")
    op.drop_index("ix_calendar_snapshots_start", table_name="calendar_snapshots")
    op.drop_index("ix_calendar_snapshots_account", table_name="calendar_snapshots")
    op.drop_table("calendar_snapshots")
