"""dashboard preferences (Phase 2F.0 — visual layout + focus only)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-11
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "dashboard_prefs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("layout", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("focus", sa.String(length=120), nullable=True),
        sa.Column("last_workspace", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("account", name="uq_dashboard_prefs_account"),
    )
    op.create_index("ix_dashboard_prefs_account", "dashboard_prefs", ["account"])


def downgrade() -> None:
    op.drop_index("ix_dashboard_prefs_account", table_name="dashboard_prefs")
    op.drop_table("dashboard_prefs")
