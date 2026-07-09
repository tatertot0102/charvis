"""pending_calendar_actions — the calendar-write approval queue

Phase 2D (calendar actions with confirmation): every create/update/delete is drafted here with
status="pending" and only executes after explicit confirmation. No write ever fires directly.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "pending_calendar_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("channel", sa.String(length=32), nullable=False, server_default="telegram"),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("action_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("target_event_id", sa.String(length=1024), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("proposed_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    )
    op.create_index(
        "ix_pending_calendar_actions_account", "pending_calendar_actions", ["account"]
    )
    op.create_index(
        "ix_pending_calendar_actions_status", "pending_calendar_actions", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_pending_calendar_actions_status", table_name="pending_calendar_actions")
    op.drop_index("ix_pending_calendar_actions_account", table_name="pending_calendar_actions")
    op.drop_table("pending_calendar_actions")
