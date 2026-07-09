"""durable_conclusions, detected_patterns, extracted_commitments, contexts, entity_contexts

Phase 2C.5 (deep context / memory): evidence-backed conclusions about "me". Read-only w.r.t.
external systems — these tables are written only by the consolidation pass.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-09
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def _evidence_columns() -> list[sa.Column]:
    """The evidence/confidence/timestamp columns shared by every memory table."""
    return [
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_list", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "durable_conclusions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("subject", sa.String(length=320), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        *_evidence_columns(),
        sa.UniqueConstraint(
            "account", "kind", "subject", name="uq_conclusion_account_kind_subject"
        ),
    )
    op.create_index("ix_durable_conclusions_kind", "durable_conclusions", ["kind"])

    op.create_table(
        "detected_patterns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("pattern_type", sa.String(length=48), nullable=False),
        sa.Column("subject", sa.String(length=320), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        *_evidence_columns(),
        sa.UniqueConstraint(
            "account", "pattern_type", "subject", name="uq_pattern_account_type_subject"
        ),
    )
    op.create_index("ix_detected_patterns_pattern_type", "detected_patterns", ["pattern_type"])

    op.create_table(
        "extracted_commitments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("counterparty", sa.String(length=320), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        *_evidence_columns(),
        sa.UniqueConstraint("account", "dedupe_key", name="uq_commitment_account_dedupe"),
    )

    op.create_table(
        "contexts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("account", "name", name="uq_context_account_name"),
    )

    op.create_table(
        "entity_contexts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_key", sa.String(length=320), nullable=False),
        sa.Column(
            "context_id",
            sa.Integer(),
            sa.ForeignKey("contexts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint(
            "account", "entity_type", "entity_key", "context_id", name="uq_entity_context_unique"
        ),
    )
    op.create_index("ix_entity_contexts_context_id", "entity_contexts", ["context_id"])


def downgrade() -> None:
    op.drop_index("ix_entity_contexts_context_id", table_name="entity_contexts")
    op.drop_table("entity_contexts")
    op.drop_table("contexts")
    op.drop_table("extracted_commitments")
    op.drop_index("ix_detected_patterns_pattern_type", table_name="detected_patterns")
    op.drop_table("detected_patterns")
    op.drop_index("ix_durable_conclusions_kind", table_name="durable_conclusions")
    op.drop_table("durable_conclusions")
