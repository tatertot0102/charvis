"""ORM models.

Phase 1: conversations, messages, captures. Phase 2A: oauth_tokens.
Phase 2B (read-only Gmail): email_messages (cached + classified), people (life-model contacts),
waiting_items (waiting-on ledger).
Phase 2C.5 (deep context / memory): durable_conclusions, detected_patterns,
extracted_commitments, contexts, entity_contexts — the evidence-backed model of "me".
Phase 2D (calendar actions with confirmation): pending_calendar_actions — the approval queue.
Phase 2D.2 (truthful calendar state): calendar_snapshots (provider-backed cache of real events,
the ONLY source for week/schedule answers) and commitments (durable life understanding of recurring
obligations — never erased by deleting a calendar event).
Phase 2D.3 (unified truth + knowledge): knowledge_entities / entity_aliases / knowledge_facts /
knowledge_evidence / knowledge_conflicts — the canonical, source-preserving knowledge store the
dashboard and planner will consume — plus conversation_task_state for active-task continuity across
follow-up messages ("this month", "LuAnn", "LuAnn Williams").
"""
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
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


class PendingCalendarAction(Base):
    """A drafted calendar write awaiting explicit confirmation (Phase 2D, CLAUDE.md §7 tier-3).

    THE HARD RULE: a calendar write NEVER fires directly. Every create/update/delete is first
    written here with status="pending" and a human-readable `summary` of the exact proposed change.
    It only executes after the user replies "CONFIRM" (Telegram) or POSTs /approvals/{id}/confirm.
    Any other response leaves it pending; a fresh proposal supersedes the previous one; a stale one
    expires. `payload` holds everything the executor needs so confirmation is a pure replay.
    """

    __tablename__ = "pending_calendar_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default", index=True)
    channel: Mapped[str] = mapped_column(String(32), default="telegram")  # telegram | http
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)  # e.g. tg user id
    action_type: Mapped[str] = mapped_column(String(16))  # create | update | delete
    # pending | executed | cancelled | expired | superseded | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    summary: Mapped[str] = mapped_column(Text)  # exact proposed change, shown to the user
    target_event_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # everything execute() needs
    # --- Phase 2D.1: confidence-aware + bulk-safe ---
    # For a bulk action, payload["targets"] holds the full list of provider-backed events
    # (event_id + title + start), item_count is how many, and required_phrase is the stronger
    # phrase the user must type ("CONFIRM DELETE") so a plain "CONFIRM" can't fire a bulk delete.
    confidence: Mapped[float] = mapped_column(Float, default=1.0)  # resolution confidence 0.0–1.0
    required_phrase: Mapped[str] = mapped_column(String(32), default="CONFIRM")  # exact confirm text
    item_count: Mapped[int] = mapped_column(default=1)  # number of events this action touches
    result: Mapped[str | None] = mapped_column(Text, nullable=True)  # executed id or error detail
    proposed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
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


# --- Phase 2D.2: truthful calendar state -------------------------------------
#
# Reality (Google Calendar) → snapshots (this cache) → commitments (durable understanding).
# Snapshots are a provider-backed mirror of the real events in a window; they are the ONLY thing
# week/schedule answers read, so Jarvis can never invent a schedule. Commitments are our own memory
# of recurring obligations and are updated by conversation — but a calendar deletion never erases one.


class CalendarSnapshot(Base):
    """A provider-backed mirror of one real Google Calendar event (Phase 2D.2).

    Every row corresponds to an event Google actually returned — never fabricated. `rebuild()` upserts
    the current window and prunes rows Google no longer returns, so the snapshot is always fresh truth.
    Week/schedule replies read ONLY these rows (never the LLM, conversation, or memory).
    """

    __tablename__ = "calendar_snapshots"
    __table_args__ = (
        UniqueConstraint("account", "provider_event_id", name="uq_snapshot_account_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default", index=True)
    provider_event_id: Mapped[str] = mapped_column(String(1024))
    recurring_event_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    attendees: Mapped[list] = mapped_column(JSON, default=list)  # attendee emails
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="confirmed")
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Commitment(Base):
    """A durable understanding of a recurring obligation — the life model of "what I actually do".

    Distinct from ExtractedCommitment (a one-off owed item): this is a standing thing like "ECE
    Machine Learning Lab", "ARISE", "Camp Counselor". Conversation corrects it ("it is X",
    "it's every weekday 10–2"); it may link to calendar events, but deleting those events must NEVER
    delete the commitment. One row per (account, key).
    """

    __tablename__ = "commitments"
    __table_args__ = (UniqueConstraint("account", "key", name="uq_commitment_account_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default", index=True)
    key: Mapped[str] = mapped_column(String(320))  # normalized title — the identity
    title: Mapped[str] = mapped_column(Text)  # display title, original casing
    type: Mapped[str | None] = mapped_column(String(48), nullable=True)  # class | project | job | …
    schedule_summary: Mapped[str | None] = mapped_column(Text, nullable=True)  # "every weekday 10–2"
    recurrence: Mapped[str | None] = mapped_column(Text, nullable=True)  # an RRULE string
    contexts: Mapped[list] = mapped_column(JSON, default=list)  # overlapping life-domains
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)  # {conversation: n, sources: [...]}
    linked_event_ids: Mapped[list] = mapped_column(JSON, default=list)  # provider event ids
    linked_email_ids: Mapped[list] = mapped_column(JSON, default=list)  # gmail ids
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | archived
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --- Phase 2D.3: canonical knowledge store + conversation task state ----------
#
# The knowledge store is the single, source-preserving model of reality that Telegram, the API, the
# future dashboard, and the future planner all read. Every fact links to real evidence and carries a
# truth_status; contradictions are preserved (never silently merged). It sits ALONGSIDE the existing
# commitments/people/memory tables (which the consolidation pass reads from), not on top of them.


class KnowledgeEntity(Base):
    """A real-world thing Jarvis reasons about (person, project, commitment, provider event, …).

    One row per (account, entity_type, normalized_name). `normalized_name` is the lowercased,
    punctuation-collapsed identity used for resolution; `canonical_name` keeps display casing.
    """

    __tablename__ = "knowledge_entities"
    __table_args__ = (
        UniqueConstraint(
            "account", "entity_type", "normalized_name", name="uq_kentity_account_type_name"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default", index=True)
    entity_type: Mapped[str] = mapped_column(String(48), index=True)  # person|project|commitment|…
    canonical_name: Mapped[str] = mapped_column(Text)
    normalized_name: Mapped[str] = mapped_column(String(320), index=True)
    status: Mapped[str] = mapped_column(String(16), default="active")  # active | archived
    # --- Phase 2D.4 reasoning attributes (derived, evidence-backed; never bare) ---
    inferred_role: Mapped[str | None] = mapped_column(Text, nullable=True)  # "ARISE coordinator", …
    importance: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0–1.0, from evidence + activity
    evidence_count: Mapped[int] = mapped_column(default=0)  # supporting records across all sources
    last_reasoned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    aliases: Mapped[list["EntityAlias"]] = relationship(
        back_populates="entity", cascade="all, delete-orphan"
    )


class EntityAlias(Base):
    """An alternate way an entity is referenced ("LuAnn", "LuAnn Williams", "DSI", an email addr).

    Alias resolution ("LuAnn" → LuAnn Williams) only fires when evidence supports it — never invents
    a person. One row per (account, entity_id, normalized_alias).
    """

    __tablename__ = "entity_aliases"
    __table_args__ = (
        UniqueConstraint("account", "entity_id", "normalized_alias", name="uq_alias_entity_norm"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default", index=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entities.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(Text)
    normalized_alias: Mapped[str] = mapped_column(String(320), index=True)
    alias_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # name|email|acronym|…
    source_type: Mapped[str] = mapped_column(String(32), default="conversation")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    entity: Mapped["KnowledgeEntity"] = relationship(back_populates="aliases")


class KnowledgeFact(Base):
    """A single claim about an entity, with a truth_status and evidence (never a bare assertion).

    e.g. entity=ECE ML Lab, predicate="weekday_schedule", display_value="weekdays 10–2",
    truth_status="user_confirmed". A missing-from-calendar claim is itself a fact
    (predicate="in_google_calendar", value="false", truth_status="provider_confirmed").
    One row per (account, entity_id, predicate, normalized_value).
    """

    __tablename__ = "knowledge_facts"
    __table_args__ = (
        UniqueConstraint(
            "account", "entity_id", "predicate", "normalized_value", name="uq_kfact_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default", index=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entities.id", ondelete="CASCADE"), index=True
    )
    predicate: Mapped[str] = mapped_column(String(64), index=True)
    normalized_value: Mapped[str] = mapped_column(Text)
    display_value: Mapped[str] = mapped_column(Text)
    value_type: Mapped[str] = mapped_column(String(24), default="text")  # text|time|date|bool|…
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # provider_confirmed|user_confirmed|multi_source_confirmed|inferred|conflicted|stale|rejected|
    # unverified
    truth_status: Mapped[str] = mapped_column(String(24), default="unverified", index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    evidence: Mapped[list["KnowledgeEvidence"]] = relationship(
        back_populates="fact", cascade="all, delete-orphan"
    )


class KnowledgeEvidence(Base):
    """The exact provenance of a fact — the real record it came from (never a paraphrase-as-source).

    `provider_object_id` holds the real Gmail message/thread id or Calendar event id where applicable,
    so no provider fact is ever shown without a link to a real provider object.
    """

    __tablename__ = "knowledge_evidence"
    __table_args__ = (
        UniqueConstraint("fact_id", "dedupe_key", name="uq_kevidence_fact_dedupe"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default", index=True)
    fact_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_facts.id", ondelete="CASCADE"), index=True
    )
    # calendar_event|calendar_snapshot|gmail_message|gmail_thread|user_statement|conversation_message|
    # capture|commitment|memory_conclusion|waiting_item
    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # local row id
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)  # google|gmail|…
    provider_object_id: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    dedupe_key: Mapped[str] = mapped_column(String(320))  # stable identity for idempotent upsert
    excerpt: Mapped[str] = mapped_column(Text, default="")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freshness_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    fact: Mapped["KnowledgeFact"] = relationship(back_populates="evidence")


class KnowledgeConflict(Base):
    """A preserved contradiction between two facts about the same entity+predicate.

    Jarvis must EXPLAIN disagreement, not resolve it silently (Golden Rule #7 / truth principle #4):
    "you told me weekdays 10–2 and LuAnn's email agrees, but Google Calendar shows no matching event."
    """

    __tablename__ = "knowledge_conflicts"
    __table_args__ = (
        UniqueConstraint(
            "account", "entity_id", "predicate", "fact_a_id", "fact_b_id", name="uq_kconflict_pair"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default", index=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entities.id", ondelete="CASCADE"), index=True
    )
    predicate: Mapped[str] = mapped_column(String(64))
    fact_a_id: Mapped[int] = mapped_column(ForeignKey("knowledge_facts.id", ondelete="CASCADE"))
    fact_b_id: Mapped[int] = mapped_column(ForeignKey("knowledge_facts.id", ondelete="CASCADE"))
    conflict_type: Mapped[str] = mapped_column(String(32))  # value|presence|schedule|…
    explanation: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | resolved
    resolved_fact_id: Mapped[int | None] = mapped_column(nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(32), nullable=True)  # user|provider|…
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EntityRelation(Base):
    """A typed, evidence-counted edge between two knowledge entities (Phase 2D.4 Life Graph).

    This is what makes the life model a *graph* rather than a bag of nodes: person —works_on→ project,
    project —contains→ commitment, project —involves→ person. Every edge is grounded — `evidence_count`
    is the number of shared source records (emails/events) that justify it, and confidence tracks that.
    One row per (account, src_entity_id, dst_entity_id, relation_type); rebuild upserts, never dupes.
    """

    __tablename__ = "entity_relations"
    __table_args__ = (
        UniqueConstraint(
            "account", "src_entity_id", "dst_entity_id", "relation_type", name="uq_erel_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), default="default", index=True)
    src_entity_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entities.id", ondelete="CASCADE"), index=True
    )
    dst_entity_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_entities.id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(48), index=True)  # works_on|contains|involves|…
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_count: Mapped[int] = mapped_column(default=0)  # shared source records justifying the edge
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DashboardPref(Base):
    """Persisted dashboard layout + focus preference (Phase 2F.0) — one row per account.

    Stores only VISUAL/preference state (section order/visibility/sizes, current focus, last open
    workspace). Never stores facts, never stores model-generated UI — the truth always comes live from
    the WorldModel and services.
    """

    __tablename__ = "dashboard_prefs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account: Mapped[str] = mapped_column(String(255), unique=True, index=True, default="default")
    layout: Mapped[dict] = mapped_column(JSON, default=dict)     # serialized LayoutState (sections…)
    focus: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_workspace: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConversationTaskState(Base):
    """The active task carried across follow-up messages — the cure for lost continuity.

    "Check my email for upcoming events." → "LuAnn." → "LuAnn Williams." must refine ONE task, not
    start three unrelated chats. One row per conversation; refreshed each turn, expired after a window.
    """

    __tablename__ = "conversation_task_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True, index=True
    )
    active_intent: Mapped[str | None] = mapped_column(String(48), nullable=True)
    active_entity_id: Mapped[int | None] = mapped_column(nullable=True)
    active_person_name: Mapped[str | None] = mapped_column(String(320), nullable=True)
    active_source_types: Mapped[list] = mapped_column(JSON, default=list)
    active_time_range: Mapped[dict] = mapped_column(JSON, default=dict)  # {type,start,end}
    active_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    unresolved_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
