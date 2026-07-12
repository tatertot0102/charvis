"""life graph: entity relations + reasoning attributes (Phase 2D.4)

Adds the edges table that turns the isolated knowledge entities into a connected life graph, plus
the derived reasoning attributes (role/importance/evidence_count) on each entity. The
knowledge_facts / knowledge_evidence / knowledge_conflicts tables already exist (0009); 2D.4 is the
first code to actually write to them — no schema change needed there.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-12
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOW = sa.text("now()")


def upgrade() -> None:
    # Reasoning attributes on each entity — derived, evidence-backed, never bare.
    op.add_column(
        "knowledge_entities", sa.Column("inferred_role", sa.Text(), nullable=True)
    )
    op.add_column(
        "knowledge_entities",
        sa.Column("importance", sa.Float(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "knowledge_entities",
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "knowledge_entities",
        sa.Column("last_reasoned_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Typed, evidence-counted edges — the graph itself.
    op.create_table(
        "entity_relations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account", sa.String(length=255), nullable=False, server_default="default"),
        sa.Column(
            "src_entity_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "dst_entity_id",
            sa.Integer(),
            sa.ForeignKey("knowledge_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(length=48), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_updated", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.UniqueConstraint(
            "account", "src_entity_id", "dst_entity_id", "relation_type", name="uq_erel_identity"
        ),
    )
    op.create_index("ix_entity_relations_account", "entity_relations", ["account"])
    op.create_index("ix_entity_relations_src", "entity_relations", ["src_entity_id"])
    op.create_index("ix_entity_relations_dst", "entity_relations", ["dst_entity_id"])
    op.create_index("ix_entity_relations_type", "entity_relations", ["relation_type"])


def downgrade() -> None:
    op.drop_index("ix_entity_relations_type", table_name="entity_relations")
    op.drop_index("ix_entity_relations_dst", table_name="entity_relations")
    op.drop_index("ix_entity_relations_src", table_name="entity_relations")
    op.drop_index("ix_entity_relations_account", table_name="entity_relations")
    op.drop_table("entity_relations")
    op.drop_column("knowledge_entities", "last_reasoned_at")
    op.drop_column("knowledge_entities", "evidence_count")
    op.drop_column("knowledge_entities", "importance")
    op.drop_column("knowledge_entities", "inferred_role")
