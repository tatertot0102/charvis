"""knowledge store + conversation task state (Phase 2D.3 — unified truth)

Canonical, source-preserving knowledge store (entities, aliases, facts, evidence, conflicts) plus
per-conversation active-task state. All additive; no existing table changes.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-10
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "knowledge_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column("entity_type", sa.String(length=48), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint(
            "account", "entity_type", "normalized_name", name="uq_kentity_account_type_name"
        ),
    )
    op.create_index("ix_knowledge_entities_account", "knowledge_entities", ["account"])
    op.create_index("ix_knowledge_entities_entity_type", "knowledge_entities", ["entity_type"])
    op.create_index("ix_knowledge_entities_normalized_name", "knowledge_entities", ["normalized_name"])

    op.create_table(
        "entity_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("normalized_alias", sa.String(length=320), nullable=False),
        sa.Column("alias_type", sa.String(length=32), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False, server_default="conversation"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("account", "entity_id", "normalized_alias", name="uq_alias_entity_norm"),
    )
    op.create_index("ix_entity_aliases_account", "entity_aliases", ["account"])
    op.create_index("ix_entity_aliases_entity_id", "entity_aliases", ["entity_id"])
    op.create_index("ix_entity_aliases_normalized_alias", "entity_aliases", ["normalized_alias"])

    op.create_table(
        "knowledge_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("predicate", sa.String(length=64), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column("display_value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(length=24), nullable=False, server_default="text"),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("truth_status", sa.String(length=24), nullable=False, server_default="unverified"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("last_verified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint(
            "account", "entity_id", "predicate", "normalized_value", name="uq_kfact_identity"
        ),
    )
    op.create_index("ix_knowledge_facts_account", "knowledge_facts", ["account"])
    op.create_index("ix_knowledge_facts_entity_id", "knowledge_facts", ["entity_id"])
    op.create_index("ix_knowledge_facts_predicate", "knowledge_facts", ["predicate"])
    op.create_index("ix_knowledge_facts_truth_status", "knowledge_facts", ["truth_status"])

    op.create_table(
        "knowledge_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column(
            "fact_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("provider_object_id", sa.String(length=1024), nullable=True),
        sa.Column("dedupe_key", sa.String(length=320), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freshness_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint("fact_id", "dedupe_key", name="uq_kevidence_fact_dedupe"),
    )
    op.create_index("ix_knowledge_evidence_account", "knowledge_evidence", ["account"])
    op.create_index("ix_knowledge_evidence_fact_id", "knowledge_evidence", ["fact_id"])
    op.create_index("ix_knowledge_evidence_source_type", "knowledge_evidence", ["source_type"])

    op.create_table(
        "knowledge_conflicts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column(
            "entity_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("predicate", sa.String(length=64), nullable=False),
        sa.Column(
            "fact_a_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fact_b_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conflict_type", sa.String(length=32), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("resolved_fact_id", sa.Integer(), nullable=True),
        sa.Column("resolved_by", sa.String(length=32), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint(
            "account", "entity_id", "predicate", "fact_a_id", "fact_b_id", name="uq_kconflict_pair"
        ),
    )
    op.create_index("ix_knowledge_conflicts_account", "knowledge_conflicts", ["account"])
    op.create_index("ix_knowledge_conflicts_entity_id", "knowledge_conflicts", ["entity_id"])

    op.create_table(
        "conversation_task_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("active_intent", sa.String(length=48), nullable=True),
        sa.Column("active_entity_id", sa.Integer(), nullable=True),
        sa.Column("active_person_name", sa.String(length=320), nullable=True),
        sa.Column("active_source_types", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("active_time_range", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("active_query", sa.Text(), nullable=True),
        sa.Column("unresolved_reference", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("conversation_id", name="uq_task_state_conversation"),
    )
    op.create_index(
        "ix_conversation_task_state_conversation_id", "conversation_task_state", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_task_state_conversation_id", table_name="conversation_task_state"
    )
    op.drop_table("conversation_task_state")
    op.drop_index("ix_knowledge_conflicts_entity_id", table_name="knowledge_conflicts")
    op.drop_index("ix_knowledge_conflicts_account", table_name="knowledge_conflicts")
    op.drop_table("knowledge_conflicts")
    op.drop_index("ix_knowledge_evidence_source_type", table_name="knowledge_evidence")
    op.drop_index("ix_knowledge_evidence_fact_id", table_name="knowledge_evidence")
    op.drop_index("ix_knowledge_evidence_account", table_name="knowledge_evidence")
    op.drop_table("knowledge_evidence")
    op.drop_index("ix_knowledge_facts_truth_status", table_name="knowledge_facts")
    op.drop_index("ix_knowledge_facts_predicate", table_name="knowledge_facts")
    op.drop_index("ix_knowledge_facts_entity_id", table_name="knowledge_facts")
    op.drop_index("ix_knowledge_facts_account", table_name="knowledge_facts")
    op.drop_table("knowledge_facts")
    op.drop_index("ix_entity_aliases_normalized_alias", table_name="entity_aliases")
    op.drop_index("ix_entity_aliases_entity_id", table_name="entity_aliases")
    op.drop_index("ix_entity_aliases_account", table_name="entity_aliases")
    op.drop_table("entity_aliases")
    op.drop_index("ix_knowledge_entities_normalized_name", table_name="knowledge_entities")
    op.drop_index("ix_knowledge_entities_entity_type", table_name="knowledge_entities")
    op.drop_index("ix_knowledge_entities_account", table_name="knowledge_entities")
    op.drop_table("knowledge_entities")
