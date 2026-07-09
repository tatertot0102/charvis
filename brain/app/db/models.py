"""ORM models.

Phase 1: conversations, messages, captures. Phase 2A: oauth_tokens.
Phase 2B (read-only Gmail): email_messages (cached + classified), people (life-model contacts),
waiting_items (waiting-on ledger).
Phase 2C.5 (deep context / memory): durable_conclusions, detected_patterns,
extracted_commitments, contexts, entity_contexts — the evidence-backed model of "me".
"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_conversation_channel_external"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(String(32))  # e.g. "telegram", "http"
    external_id: Mapped[str] = mapped_column(String(128))  # e.g. telegram user id / session id
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Capture(Base):
    __tablename__ = "captures"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="api")  # api | telegram
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OAuthToken(Base):
    """Encrypted OAuth credentials for a cloud provider (Phase 2A: Google, read-only).

    Access and refresh tokens are Fernet-encrypted at rest (see app.security.crypto); this table
    never stores a plaintext token. One row per (provider, account); re-authing upserts the row.
    """

    __tablename__ = "oauth_tokens"
    __table_args__ = (
        UniqueConstraint("provider", "account", name="uq_oauth_provider_account"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))  # e.g. "google"
    account: Mapped[str] = mapped_column(String(255), default="default")  # google email or "default"
    scopes: Mapped[str] = mapped_column(Text)  # space-separated granted scopes
    access_token_encrypted: Mapped[str] = mapped_column(Text)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_uri: Mapped[str] = mapped_column(Text)
    expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EmailMessage(Base):
    """A cached, classified Gmail message (read-only mirror — Jarvis never mutates Gmail).

    One row per Gmail message id. The classification columns are the stored 'analysis' the
    conversation/planner layers reason over without re-fetching Gmail.
    """

    __tablename__ = "email_messages"
    __table_args__ = (UniqueConstraint("account", "gmail_id", name="uq_email_account_gmail_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default")
    gmail_id: Mapped[str] = mapped_column(String(255))
    thread_id: Mapped[str] = mapped_column(String(255), index=True)
    from_email: Mapped[str] = mapped_column(String(320))
    from_name: Mapped[str | None] = mapped_column(String(320), nullable=True)
    to_emails: Mapped[str] = mapped_column(Text, default="")  # comma-separated
    subject: Mapped[str] = mapped_column(Text, default="")
    snippet: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    labels: Mapped[str] = mapped_column(Text, default="")  # space-separated Gmail label ids
    direction: Mapped[str] = mapped_column(String(16), default="inbound")  # inbound | outbound
    # --- stored classification ---
    importance: Mapped[str] = mapped_column(String(16), default="normal")  # high | normal | low
    urgency: Mapped[str] = mapped_column(String(16), default="normal")  # high | normal | low
    requires_response: Mapped[bool] = mapped_column(default=False)
    is_promotional: Mapped[bool] = mapped_column(default=False)
    is_calendar_related: Mapped[bool] = mapped_column(default=False)
    is_deadline_related: Mapped[bool] = mapped_column(default=False)
    is_fyi: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Person(Base):
    """A contact Jarvis has seen in email — the people slice of the life model (CLAUDE.md §5).

    Additive: sync updates last-contact timestamps and counts, never deletes.
    """

    __tablename__ = "people"
    __table_args__ = (UniqueConstraint("account", "email", name="uq_people_account_email"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default")
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str | None] = mapped_column(String(320), nullable=True)
    last_inbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_interaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    message_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WaitingItem(Base):
    """A thread where someone owes a reply — the waiting-on ledger (CLAUDE.md §8, detection only).

    Phase 2B detects and stores these; it never sends a follow-up. One row per (account, thread).
    """

    __tablename__ = "waiting_items"
    __table_args__ = (UniqueConstraint("account", "thread_id", name="uq_waiting_account_thread"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default")
    kind: Mapped[str] = mapped_column(String(32))  # waiting_on_them | waiting_on_me
    thread_id: Mapped[str] = mapped_column(String(255))
    person_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    subject: Mapped[str] = mapped_column(Text, default="")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_direction: Mapped[str] = mapped_column(String(16), default="inbound")
    follow_up_recommended: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# --- Phase 2C.5: memory (evidence-backed conclusions about "me") -------------
#
# Every row in these tables carries confidence, an evidence breakdown, a source list, and
# first_seen/last_updated timestamps. Consolidation upserts them (never blind-inserts) so a
# conclusion's confidence and evidence evolve as more data accrues. Read-only w.r.t. Gmail/Calendar.


class DurableConclusion(Base):
    """A decision-useful belief about the user, traceable to its evidence (EXECUTION_PLAN §2C.5).

    `kind` groups conclusions (project | person | preference | relationship | …); `subject` is the
    thing the conclusion is about (e.g. "ARISE", "dana@lab.org"). One row per (account, kind,
    subject) — re-running consolidation updates confidence/evidence rather than duplicating.
    """

    __tablename__ = "durable_conclusions"
    __table_args__ = (
        UniqueConstraint("account", "kind", "subject", name="uq_conclusion_account_kind_subject"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default")
    kind: Mapped[str] = mapped_column(String(32), index=True)  # project | person | preference | …
    subject: Mapped[str] = mapped_column(String(320))  # the entity/topic the conclusion is about
    statement: Mapped[str] = mapped_column(Text)  # the human-readable, explainable conclusion
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0–1.0, derived from evidence
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)  # {by_source: {...}, records: [...]}
    source_list: Mapped[list] = mapped_column(JSON, default=list)  # ["gmail", "calendar", …]
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DetectedPattern(Base):
    """A recurring behavioral pattern that improves prioritization or prep (never trivia).

    e.g. pattern_type="response_time", subject="dana@lab.org" → "You usually reply to Dana within a
    day." One row per (account, pattern_type, subject).
    """

    __tablename__ = "detected_patterns"
    __table_args__ = (
        UniqueConstraint(
            "account", "pattern_type", "subject", name="uq_pattern_account_type_subject"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default")
    pattern_type: Mapped[str] = mapped_column(String(48), index=True)
    subject: Mapped[str] = mapped_column(String(320))
    description: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    source_list: Mapped[list] = mapped_column(JSON, default=list)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExtractedCommitment(Base):
    """Something owed — by me, to me, or a dated obligation (EXECUTION_PLAN §2C.5).

    `direction` is owed_by_me | owed_to_me | deadline. `dedupe_key` keeps consolidation idempotent
    (e.g. the source thread id, or a hash of the description) so re-runs update in place.
    """

    __tablename__ = "extracted_commitments"
    __table_args__ = (
        UniqueConstraint("account", "dedupe_key", name="uq_commitment_account_dedupe"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default")
    dedupe_key: Mapped[str] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(String(16))  # owed_by_me | owed_to_me | deadline
    description: Mapped[str] = mapped_column(Text)
    counterparty: Mapped[str | None] = mapped_column(String(320), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open (read-only: never closed)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    source_list: Mapped[list] = mapped_column(JSON, default=list)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Context(Base):
    """An overlapping life-domain (Work, School, Research, Family, …) — not a single category.

    Entities (people, projects) may belong to several contexts at once via entity_contexts. Contexts
    are seeded canonically and can also be created by consolidation when a new domain appears.
    """

    __tablename__ = "contexts"
    __table_args__ = (UniqueConstraint("account", "name", name="uq_context_account_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default")
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    entity_links: Mapped[list["EntityContext"]] = relationship(
        back_populates="context", cascade="all, delete-orphan"
    )


class EntityContext(Base):
    """Tags one entity (a person or project) into one context, with its own confidence.

    entity_type is person | project; entity_key is the conclusion subject (email or project token).
    Many-to-many by design — the same person can be tagged Work AND Family.
    """

    __tablename__ = "entity_contexts"
    __table_args__ = (
        UniqueConstraint(
            "account",
            "entity_type",
            "entity_key",
            "context_id",
            name="uq_entity_context_unique",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default")
    entity_type: Mapped[str] = mapped_column(String(32))  # person | project
    entity_key: Mapped[str] = mapped_column(String(320))  # matches a DurableConclusion.subject
    context_id: Mapped[int] = mapped_column(
        ForeignKey("contexts.id", ondelete="CASCADE"), index=True
    )
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    context: Mapped["Context"] = relationship(back_populates="entity_links")
