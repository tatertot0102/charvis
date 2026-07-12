"""Derivation (Phase 2C.5) — turn gathered signals into evidence-backed memory. Pure, no I/O.

This is where "historical data" becomes "useful context for today's decisions". Every conclusion is
built from concrete SourceRefs, so it is always explainable and its confidence is derived from that
evidence. The utility-first rule is enforced here: promotional/no-reply noise is excluded and each
conclusion must clear a support threshold, so trivia never gets stored.
"""
from __future__ import annotations

from collections import defaultdict

from app.integrations.google.classify import is_noreply
from app.memory import confidence, contexts, patterns, tokens
from app.memory.schema import (
    DerivedCommitment,
    DerivedConclusion,
    DerivedPattern,
    Evidence,
    MemorySet,
    SourceRef,
)
from app.memory.signals import Signals

MIN_PROJECT_SIGNALS = 3  # total records a token needs before it can be a project
MIN_SINGLE_SOURCE = 5  # …unless one source alone supplies this many (a strong single signal)
MAX_PROJECTS = 25
MIN_PERSON_EMAILS = 3  # non-promo emails with a person before they're an "important contact"
MAX_PEOPLE = 25
MAX_CAPTURE_COMMITMENTS = 50


# --- projects ----------------------------------------------------------------


def derive_projects(signals: Signals) -> list[DerivedConclusion]:
    """Recurring distinctive tokens across email + calendar + captures + chat become projects."""
    evidence_by_token: dict[str, Evidence] = defaultdict(Evidence)
    texts_by_token: dict[str, list[str]] = defaultdict(list)

    def _ingest(text: str, ref: SourceRef) -> None:
        for token in tokens.distinctive_tokens(text):
            evidence_by_token[token].add(ref)
            texts_by_token[token].append(text)

    for email in signals.emails:
        if email.is_promotional:
            continue
        _ingest(email.subject, SourceRef("gmail", email.thread_id, f"email: {email.subject}",
                                         email.received_at))
    for event in signals.events:
        _ingest(event.summary, SourceRef("calendar", event.event_id, f"event: {event.summary}",
                                         event.start))
    for capture in signals.captures:
        _ingest(capture.text, SourceRef("capture", str(capture.id), f"note: {capture.text[:60]}",
                                        capture.created_at))
    for tele in signals.telegram:
        _ingest(tele.text, SourceRef("telegram", str(tele.id), f"chat: {tele.text[:60]}",
                                     tele.created_at))

    conclusions: list[DerivedConclusion] = []
    for token, evidence in evidence_by_token.items():
        by_source = evidence.by_source
        total = len(evidence.records)
        if total < MIN_PROJECT_SIGNALS:
            continue
        if len(by_source) < 2 and max(by_source.values()) < MIN_SINGLE_SOURCE:
            continue  # a single weak source isn't enough — needs breadth or real volume
        name = tokens.display_name(token)
        score = confidence.score(evidence)
        ctx = sorted(contexts.classify_text(" ".join(texts_by_token[token])).keys())
        conclusions.append(
            DerivedConclusion(
                kind="project",
                subject=name,
                statement=f"“{name}” looks like an active project — {confidence.explain(evidence)}.",
                confidence=score,
                evidence=evidence,
                contexts=tuple(ctx),
            )
        )
    conclusions.sort(key=lambda c: c.confidence, reverse=True)
    return conclusions[:MAX_PROJECTS]


# --- people ------------------------------------------------------------------


def _person_evidence(email: str, signals: Signals) -> tuple[Evidence, list[str]]:
    """Concrete records tying a person to the user, plus the subjects for context classification."""
    evidence = Evidence()
    subjects: list[str] = []
    for msg in signals.emails:
        if msg.is_promotional:
            continue
        involved = msg.from_email == email or email in msg.to_emails
        if involved:
            evidence.add(SourceRef("gmail", msg.thread_id, f"email: {msg.subject}", msg.received_at))
            subjects.append(msg.subject)
    for event in signals.events:
        if email in event.attendees:
            evidence.add(SourceRef("calendar", event.event_id, f"event: {event.summary}",
                                   event.start))
            subjects.append(event.summary)
    for item in signals.waiting:
        if item.person_email == email:
            evidence.add(SourceRef("waiting", item.thread_id, f"open thread: {item.subject}",
                                   item.last_message_at))
    return evidence, subjects


def derive_people(signals: Signals) -> list[DerivedConclusion]:
    """People who recur enough (email volume, meetings, open threads) to matter for decisions."""
    conclusions: list[DerivedConclusion] = []
    for person in signals.people:
        if is_noreply(person.email):
            continue
        evidence, subjects = _person_evidence(person.email, signals)
        by_source = evidence.by_source
        gmail_count = by_source.get("gmail", 0)
        if gmail_count < MIN_PERSON_EMAILS and "calendar" not in by_source and "waiting" not in by_source:
            continue  # a one-off sender is not an important contact
        who = person.name or person.email
        ctx = contexts.classify_email(person.email)
        for name in contexts.classify_text(" ".join(subjects)):
            ctx.setdefault(name, [])
        conclusions.append(
            DerivedConclusion(
                kind="person",
                subject=person.email,
                statement=f"{who} is an important contact — {confidence.explain(evidence)}.",
                confidence=confidence.score(evidence),
                evidence=evidence,
                contexts=tuple(sorted(ctx.keys())),
                display_name=person.name or None,
            )
        )
    conclusions.sort(key=lambda c: c.confidence, reverse=True)
    return conclusions[:MAX_PEOPLE]


# --- commitments -------------------------------------------------------------


def _thread_email_ref(thread_id: str, signals: Signals) -> SourceRef | None:
    for msg in signals.emails:
        if msg.thread_id == thread_id:
            return SourceRef("gmail", thread_id, f"email: {msg.subject}", msg.received_at)
    return None


def derive_commitments(signals: Signals) -> list[DerivedCommitment]:
    """Open loops: replies you owe, follow-ups pending, dated obligations, and captured tasks."""
    out: list[DerivedCommitment] = []

    for item in signals.waiting:
        evidence = Evidence()
        evidence.add(SourceRef("waiting", item.thread_id, f"thread: {item.subject}",
                               item.last_message_at))
        email_ref = _thread_email_ref(item.thread_id, signals)
        if email_ref:
            evidence.add(email_ref)
        who = item.person_email or "someone"
        if item.kind == "waiting_on_me":
            out.append(DerivedCommitment(
                dedupe_key=f"waiting:{item.thread_id}",
                direction="owed_by_me",
                description=f"Reply to {who} about “{item.subject or '(no subject)'}”.",
                confidence=confidence.score(evidence),
                evidence=evidence,
                counterparty=item.person_email,
                due_at=None,
            ))
        elif item.follow_up_recommended:
            out.append(DerivedCommitment(
                dedupe_key=f"followup:{item.thread_id}",
                direction="owed_to_me",
                description=f"Follow up with {who} — no reply on “{item.subject or '(no subject)'}”.",
                confidence=confidence.score(evidence),
                evidence=evidence,
                counterparty=item.person_email,
                due_at=None,
            ))

    for msg in signals.emails:
        if msg.direction == "inbound" and msg.is_deadline_related and not msg.is_promotional:
            evidence = Evidence()
            evidence.add(SourceRef("gmail", msg.gmail_id, f"email: {msg.subject}", msg.received_at))
            sender = msg.from_name or msg.from_email
            out.append(DerivedCommitment(
                dedupe_key=f"deadline-email:{msg.gmail_id}",
                direction="deadline",
                description=f"Deadline flagged: “{msg.subject or '(no subject)'}” from {sender}.",
                confidence=confidence.score(evidence),
                evidence=evidence,
                counterparty=msg.from_email,
                due_at=None,
            ))

    for capture in signals.captures[:MAX_CAPTURE_COMMITMENTS]:
        evidence = Evidence()
        evidence.add(SourceRef("capture", str(capture.id), f"note: {capture.text[:60]}",
                               capture.created_at))
        out.append(DerivedCommitment(
            dedupe_key=f"capture:{capture.id}",
            direction="owed_by_me",
            description=f"Task you noted: “{capture.text.strip()}”.",
            confidence=confidence.score(evidence),
            evidence=evidence,
            counterparty=None,
            due_at=None,
        ))
    return out


# --- top-level ---------------------------------------------------------------


def derive(signals: Signals) -> MemorySet:
    """Run every derivation over the gathered signals and return them as one set."""
    project_conclusions = derive_projects(signals)
    people_conclusions = derive_people(signals)
    pattern_list: list[DerivedPattern] = patterns.all_patterns(signals)
    commitments = derive_commitments(signals)
    return MemorySet(
        conclusions=tuple(project_conclusions + people_conclusions),
        patterns=tuple(pattern_list),
        commitments=tuple(commitments),
    )
