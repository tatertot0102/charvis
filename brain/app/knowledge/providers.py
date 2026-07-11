"""Independent providers over existing subsystems (Phase 2D.3 integration).

Each provider wraps one system Jarvis already has and returns structured Facts — no prose, no LLM. They
are independent so the engine can run them concurrently. A provider NEVER raises: an unreachable source
degrades to an empty result (the engine records the source status separately), so one dead connector
can't sink a whole answer. This is the "everything becomes a provider" layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.commitments import store as commitments_store
from app.config import get_settings
from app.coordination import waiting as waiting_mod
from app.db.models import Message
from app.db.session import get_session
from app.integrations.google import calendar as calendar_mod
from app.integrations.google import gmail as gmail_mod
from app.knowledge.entities import normalize
from app.knowledge.model import Fact, Reality
from app.memory import store as memory_store
from app.telemetry import get_logger

log = get_logger(__name__)

_EVENT_QUERY = (
    '(invite OR invitation OR "calendar invite" OR event OR rsvp OR meeting OR seminar OR webinar '
    'OR flight OR hotel OR reservation OR zoom OR "google meet")'
)


@dataclass
class Query:
    """A resolved request handed to every provider."""

    intent: str
    account: str = "default"
    start: datetime | None = None
    end: datetime | None = None
    text: str = ""
    terms: list[str] = field(default_factory=list)  # entity match terms (lowercased); empty = no filter
    person: str | None = None
    gmail_limit: int = 25
    require_all: bool = False  # verify: an event must contain ALL significant tokens (strict), title-only

    @property
    def scoped(self) -> bool:
        return bool(self.terms)

    @property
    def token_terms(self) -> list[str]:
        """Single-word match terms only (drops multi-word phrases) — used for strict AND-matching."""
        return [t for t in self.terms if " " not in t]


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _text_matches(haystack: str, terms: list[str]) -> bool:
    """True if unscoped (no terms) or any term appears in the (normalized) haystack."""
    if not terms:
        return True
    norm = normalize(haystack)
    return any(t and t in norm for t in terms)


_QUESTION_LEAD = frozenset(
    {"what", "whats", "who", "whos", "when", "where", "why", "how", "is", "are", "do", "does",
     "did", "can", "could", "will", "would", "should", "tell"}
)


def _is_question(text: str) -> bool:
    """A user question (not a statement) — excluded from conversation-as-evidence."""
    tokens = normalize(text).split()
    return bool(tokens) and (tokens[0] in _QUESTION_LEAD or text.strip().endswith("?"))


# --- providers ----------------------------------------------------------------


class CalendarProvider:
    name = "calendar"

    async def fetch(self, q: Query) -> list[Fact]:
        settings = get_settings()
        start = q.start or datetime.now(UTC)
        end = q.end or (start + timedelta(days=settings.upcoming_window_days))
        try:
            events = await calendar_mod.list_events_range(start, end, account=q.account)
        except Exception as exc:  # noqa: BLE001 — a dead calendar degrades to no facts.
            log.info("calendar_provider_unavailable", error=type(exc).__name__)
            return []
        tz = _tz()
        facts: list[Fact] = []
        for ev in events:
            if not ev.event_id:
                continue
            if q.require_all:
                # Strict verification: every significant token must be in the TITLE (not the
                # description) so "is X on my calendar?" can't match on a stray word.
                summary_norm = normalize(ev.summary)
                if not q.token_terms or not all(t in summary_norm for t in q.token_terms):
                    continue
            else:
                haystack = f"{ev.summary} {ev.description} {' '.join(ev.attendees)} {ev.location or ''}"
                if not _text_matches(haystack, q.terms):
                    continue
            facts.append(
                Fact(
                    kind="event", reality=Reality.VERIFIED,
                    text=_event_line(ev, tz), source=self.name, provider="google",
                    provider_object_id=ev.event_id, confidence=0.95, when=ev.start,
                    data={"summary": ev.summary, "attendees": list(ev.attendees),
                          "location": ev.location, "recurring": ev.recurring},
                )
            )
        return facts


class SnapshotProvider:
    """Cached provider-truth (2D.2). The engine uses it as a fallback when the live calendar is down."""

    name = "snapshot"

    async def fetch(self, q: Query) -> list[Fact]:
        from app.calendar_state import snapshots

        start = q.start or datetime.now(UTC)
        end = q.end or (start + timedelta(days=get_settings().week_span_days))
        try:
            events = await snapshots.read_range(q.account, start, end)
        except Exception as exc:  # noqa: BLE001
            log.info("snapshot_provider_unavailable", error=type(exc).__name__)
            return []
        tz = _tz()
        facts: list[Fact] = []
        for ev in events:
            haystack = f"{ev.title} {ev.location or ''}"
            if not _text_matches(haystack, q.terms):
                continue
            facts.append(
                Fact(
                    kind="event", reality=Reality.VERIFIED,
                    text=_snapshot_line(ev, tz), source=self.name, provider="google",
                    provider_object_id=ev.provider_event_id, confidence=0.9, when=ev.start,
                    data={"summary": ev.title, "cached": True},
                )
            )
        return facts


class GmailProvider:
    name = "gmail"

    async def fetch(self, q: Query) -> list[Fact]:
        query = self._build_query(q)
        try:
            messages = await gmail_mod.search(query, account=q.account, max_results=q.gmail_limit)
        except Exception as exc:  # noqa: BLE001
            log.info("gmail_provider_unavailable", error=type(exc).__name__)
            return []
        tz = _tz()
        facts: list[Fact] = []
        for msg in messages:
            if not msg.gmail_id:
                continue
            facts.append(
                Fact(
                    kind="email", reality=Reality.LIKELY,
                    text=_email_line(msg, tz), source=self.name, provider="gmail",
                    provider_object_id=msg.gmail_id, confidence=0.6, when=msg.received_at,
                    data={"subject": msg.subject, "from": msg.from_email,
                          "thread_id": msg.thread_id},
                )
            )
        return facts

    def _build_query(self, q: Query) -> str:
        parts = []
        if q.person:
            parts.append(f'(from:{q.person} OR "{q.person}")')
        elif q.terms:
            # Prefer the full entity phrase(s) over single tokens — searching bare "applications"
            # dredges up unrelated mail; "college applications" as a phrase stays on-topic.
            phrases = [t for t in q.terms if " " in t]
            chosen = phrases or q.terms
            parts.append("(" + " OR ".join(f'"{t}"' for t in chosen) + ")")
        if q.intent in ("schedule", "email_events"):
            parts.append(_EVENT_QUERY)
        parts.append("newer_than:180d")
        return " ".join(parts)


class CommitmentProvider:
    name = "commitment"

    async def fetch(self, q: Query) -> list[Fact]:
        try:
            rows = await commitments_store.list_all(q.account)
        except Exception as exc:  # noqa: BLE001
            log.info("commitment_provider_unavailable", error=type(exc).__name__)
            return []
        facts: list[Fact] = []
        for c in rows:
            haystack = f"{c.title} {c.schedule_summary or ''} {' '.join(c.contexts or [])}"
            if not _text_matches(haystack, q.terms):
                continue
            summary = c.schedule_summary or c.recurrence or c.type or "commitment"
            facts.append(
                Fact(
                    kind="commitment", reality=Reality.REMEMBERED,
                    text=f"{c.title}: {summary}", source=self.name,
                    entity=c.title, confidence=c.confidence or 0.5,
                    data={"title": c.title, "recurrence": c.recurrence,
                          "schedule": c.schedule_summary, "linked_event_ids": c.linked_event_ids},
                )
            )
        return facts


class MemoryProvider:
    name = "memory"

    async def fetch(self, q: Query) -> list[Fact]:
        facts: list[Fact] = []
        try:
            conclusions = await memory_store.list_conclusions(q.account)
        except Exception as exc:  # noqa: BLE001
            log.info("memory_provider_unavailable", error=type(exc).__name__)
            return []
        for c in conclusions:
            if not _text_matches(f"{c.subject} {c.statement}", q.terms):
                continue
            facts.append(
                Fact(
                    kind="conclusion", reality=Reality.REMEMBERED,
                    text=c.statement, source=self.name, entity=c.subject,
                    confidence=c.confidence or 0.5, data={"kind": c.kind, "subject": c.subject},
                )
            )
        try:
            xcommits = await memory_store.list_commitments(q.account)
        except Exception:  # noqa: BLE001
            xcommits = []
        for x in xcommits:
            if not _text_matches(f"{x.description} {x.counterparty or ''}", q.terms):
                continue
            facts.append(
                Fact(
                    kind="conclusion", reality=Reality.REMEMBERED,
                    text=x.description, source=self.name, entity=x.counterparty,
                    confidence=x.confidence or 0.5, when=x.due_at,
                    data={"direction": x.direction, "due_at": x.due_at},
                )
            )
        return facts


class PatternProvider:
    name = "pattern"

    async def fetch(self, q: Query) -> list[Fact]:
        try:
            rows = await memory_store.list_patterns(q.account)
        except Exception as exc:  # noqa: BLE001
            log.info("pattern_provider_unavailable", error=type(exc).__name__)
            return []
        facts: list[Fact] = []
        for p in rows:
            if not _text_matches(f"{p.subject} {p.description}", q.terms):
                continue
            facts.append(
                Fact(
                    kind="pattern", reality=Reality.INFERRED,
                    text=p.description, source=self.name, entity=p.subject,
                    confidence=p.confidence or 0.4, data={"pattern_type": p.pattern_type},
                )
            )
        return facts


class WaitingProvider:
    name = "waiting"

    async def fetch(self, q: Query) -> list[Fact]:
        try:
            rows = await waiting_mod.list_waiting(q.account)
        except Exception as exc:  # noqa: BLE001
            log.info("waiting_provider_unavailable", error=type(exc).__name__)
            return []
        facts: list[Fact] = []
        for w in rows:
            if not _text_matches(f"{w.subject or ''} {w.person_email or ''}", q.terms):
                continue
            facts.append(
                Fact(
                    kind="waiting", reality=Reality.LIKELY,
                    text=f"{w.kind}: {w.subject or '(no subject)'} — {w.person_email or ''}".strip(),
                    source=self.name, entity=w.person_email, provider="gmail",
                    provider_object_id=w.thread_id, confidence=0.6, when=w.last_message_at,
                    data={"kind": w.kind, "thread_id": w.thread_id},
                )
            )
        return facts


class ConversationProvider:
    """Recent user statements — remembered corrections/mentions that other providers may miss."""

    name = "conversation"

    async def fetch(self, q: Query) -> list[Fact]:
        if not q.terms:  # only meaningful when scoped to an entity
            return []
        try:
            async with get_session() as session:
                rows = (
                    await session.execute(
                        select(Message).where(Message.role == "user")
                        .order_by(Message.id.desc()).limit(300)
                    )
                ).scalars().all()
        except Exception as exc:  # noqa: BLE001
            log.info("conversation_provider_unavailable", error=type(exc).__name__)
            return []
        facts: list[Fact] = []
        for m in rows:
            if _is_question(m.content):
                continue  # the user's own questions aren't evidence — only their statements are
            if not _text_matches(m.content, q.terms):
                continue
            facts.append(
                Fact(
                    kind="message", reality=Reality.REMEMBERED,
                    text=f'You said: "{m.content.strip()[:160]}"', source=self.name,
                    confidence=0.5, data={"message_id": m.id},
                )
            )
            if len(facts) >= 5:
                break
        return facts


# --- line formatters (pure) ---------------------------------------------------


def _event_line(ev: calendar_mod.CalendarEvent, tz: ZoneInfo) -> str:
    local = ev.start.astimezone(tz)
    if ev.all_day:
        return f"{ev.summary} ({local.strftime('%a %b %-d')}, all day)"
    where = f" @ {ev.location}" if ev.location else ""
    return f"{ev.summary} — {local.strftime('%a %b %-d %-I:%M %p')}{where}"


def _snapshot_line(ev, tz: ZoneInfo) -> str:
    local = ev.start.astimezone(tz)
    if ev.all_day:
        return f"{ev.title} ({local.strftime('%a %b %-d')}, all day)"
    where = f" @ {ev.location}" if ev.location else ""
    return f"{ev.title} — {local.strftime('%a %b %-d %-I:%M %p')}{where}"


def _email_line(msg: gmail_mod.GmailMessage, tz: ZoneInfo) -> str:
    who = msg.from_name or msg.from_email or "unknown sender"
    when = f" · {msg.received_at.astimezone(tz).strftime('%b %-d')}" if msg.received_at else ""
    return f"{msg.subject or '(no subject)'} — from {who}{when}"


# The default provider roster. The engine selects a subset per intent.
ALL_PROVIDERS = [
    CalendarProvider(), GmailProvider(), CommitmentProvider(), MemoryProvider(),
    PatternProvider(), WaitingProvider(), ConversationProvider(),
]
