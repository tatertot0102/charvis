"""email_messages, people, waiting_items (Phase 2B: read-only Gmail)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "email_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("gmail_id", sa.String(length=255), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("from_email", sa.String(length=320), nullable=False),
        sa.Column("from_name", sa.String(length=320), nullable=True),
        sa.Column("to_emails", sa.Text(), nullable=False, server_default=""),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("labels", sa.Text(), nullable=False, server_default=""),
        sa.Column("direction", sa.String(length=16), nullable=False, server_default="inbound"),
        sa.Column("importance", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("urgency", sa.String(length=16), nullable=False, server_default="normal"),
        sa.Column("requires_response", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_promotional", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_calendar_related", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_deadline_related", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_fyi", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("account", "gmail_id", name="uq_email_account_gmail_id"),
    )
    op.create_index("ix_email_messages_thread_id", "email_messages", ["thread_id"])
    op.create_index("ix_email_messages_received_at", "email_messages", ["received_at"])

    op.create_table(
        "people",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("name", sa.String(length=320), nullable=True),
        sa.Column("last_inbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("account", "email", name="uq_people_account_email"),
    )

    op.create_table(
        "waiting_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("person_email", sa.String(length=320), nullable=True),
        sa.Column("subject", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_message_direction", sa.String(length=16), nullable=False, server_default="inbound"
        ),
        sa.Column(
            "follow_up_recommended", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("account", "thread_id", name="uq_waiting_account_thread"),
    )


def downgrade() -> None:
    op.drop_table("waiting_items")
    op.drop_table("people")
    op.drop_index("ix_email_messages_received_at", table_name="email_messages")
    op.drop_index("ix_email_messages_thread_id", table_name="email_messages")
    op.drop_table("email_messages")
