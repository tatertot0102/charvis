"""Overlapping life contexts (Phase 2C.5) — NOT a single work/personal split.

An entity (a project, a person) can belong to several contexts at once: a research project is
Research AND Engineering AND School; a professor is School AND Research. Assignment is a
deterministic keyword/domain match so it stays explainable and testable. Each match is evidence for
tagging, and the caller scores confidence from how many independent signals agree.
"""
from __future__ import annotations

# Canonical contexts seeded on every consolidation run. Consolidation may add more, but these give
# a sensible overlapping baseline aligned with EXECUTION_PLAN §2C.5.
CANONICAL_CONTEXTS: dict[str, str] = {
    "Work": "Jobs, employers, professional obligations.",
    "School": "Coursework, classes, teachers, academic life.",
    "Engineering": "Building, coding, hardware/software projects.",
    "Research": "Labs, studies, papers, experiments.",
    "College Applications": "Applying to colleges — essays, deadlines, counselors.",
    "Personal Project": "Self-directed side projects.",
    "Family": "Relatives and household.",
    "Health": "Medical, fitness, wellbeing.",
    "Finance": "Money, bills, banking, payments.",
    "Travel": "Trips, flights, lodging.",
    "Personal": "Friends and personal life outside the above.",
}

# Substring keywords that imply a context. Overlap is intentional — a term can map to several.
_CONTEXT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Work": ("work", "job", "intern", "internship", "employer", "manager", "client",
             "invoice", "contract", "onboarding", "offer letter", "standup", "sprint"),
    "School": ("class", "course", "homework", "assignment", "exam", "midterm", "final",
               "professor", "teacher", "lecture", "semester", "grade", "syllabus", "school",
               "student", "gpa", "transcript"),
    "Engineering": ("code", "coding", "build", "repo", "github", "deploy", "bug", "api",
                    "hardware", "firmware", "circuit", "robot", "engineering", "software",
                    "backend", "frontend", "pcb", "cad", "prototype"),
    "Research": ("research", "lab", "study", "paper", "experiment", "dataset", "grant",
                 "publication", "thesis", "hypothesis", "journal", "abstract", "arise"),
    "College Applications": ("college app", "application", "admission", "admissions", "essay",
                             "supplement", "common app", "coalition", "counselor", "recommendation",
                             "sat", "act", "early decision", "early action", "union college",
                             "stony brook", "financial aid", "fafsa"),
    "Personal Project": ("side project", "personal project", "hobby", "portfolio", "startup"),
    "Family": ("mom", "dad", "mother", "father", "sister", "brother", "grandma", "grandpa",
               "family", "cousin", "aunt", "uncle", "parents"),
    "Health": ("doctor", "dentist", "appointment", "prescription", "therapy", "gym", "workout",
               "health", "clinic", "medical", "insurance claim"),
    "Finance": ("payment", "invoice", "bill", "bank", "venmo", "paypal", "refund", "receipt",
                "tax", "taxes", "budget", "tuition", "scholarship", "salary", "deposit"),
    "Travel": ("flight", "hotel", "airbnb", "trip", "itinerary", "boarding", "reservation",
               "travel", "airport", "train", "booking"),
}

# Email-domain hints (checked against the sender/counterparty address).
_DOMAIN_CONTEXTS: dict[str, tuple[str, ...]] = {
    ".edu": ("School", "Research"),
}


def classify_text(text: str) -> dict[str, list[str]]:
    """Map free text to {context_name: [matched keywords]} — a term can hit several contexts."""
    lowered = (text or "").lower()
    hits: dict[str, list[str]] = {}
    for context, keywords in _CONTEXT_KEYWORDS.items():
        matched = [kw for kw in keywords if kw in lowered]
        if matched:
            hits[context] = matched
    return hits


def classify_email(email: str | None) -> dict[str, list[str]]:
    """Context hints from an email domain (e.g. an .edu address suggests School/Research)."""
    if not email:
        return {}
    lowered = email.lower()
    hits: dict[str, list[str]] = {}
    for suffix, contexts in _DOMAIN_CONTEXTS.items():
        domain = lowered.rsplit("@", 1)[-1]
        if domain.endswith(suffix):
            for context in contexts:
                hits.setdefault(context, []).append(f"domain {suffix}")
    return hits
