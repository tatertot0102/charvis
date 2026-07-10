"""pending_calendar_actions — confidence, required_phrase, item_count (Phase 2D.1)

Adds the columns that make calendar actions confidence-aware and bulk-safe: a resolution
confidence, the exact phrase the user must type to confirm (a bulk delete requires the stronger
"CONFIRM DELETE"), and how many events the action touches. Bulk targets live in the JSON payload.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pending_calendar_actions",
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "pending_calendar_actions",
        sa.Column("required_phrase", sa.String(length=32), nullable=False, server_default="CONFIRM"),
    )
    op.add_column(
        "pending_calendar_actions",
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("pending_calendar_actions", "item_count")
    op.drop_column("pending_calendar_actions", "required_phrase")
    op.drop_column("pending_calendar_actions", "confidence")
