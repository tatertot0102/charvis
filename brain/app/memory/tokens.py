"""Distinctive-token extraction for project detection (Phase 2C.5).

Projects are found by spotting distinctive words that recur across email subjects, calendar titles,
captures, and chat. That only works if we first strip the sea of common words. This stoplist is
deliberately broader than the ContextResolver's (which only cleans calendar titles) because here we
tokenize free-form email subjects and notes too. Pure and unit-testable — no I/O.
"""
from __future__ import annotations

import re

# Match 2+ char tokens; the length filter below drops 2-char ones unless they're kept acronyms.
_WORD = re.compile(r"[a-z0-9][a-z0-9'+_-]+")

# Common English + email/calendar boilerplate that make useless project names.
_STOPWORDS = frozenset(
    {
        # calendar/meeting boilerplate (superset of resolver._STOPWORDS)
        "the", "and", "for", "with", "meeting", "call", "sync", "chat", "catch", "ups",
        "weekly", "biweekly", "monthly", "daily", "standup", "1on1", "one", "zoom", "google",
        "meet", "invite", "invitation", "appointment", "reminder", "about", "your", "you",
        # email boilerplate
        "fwd", "fw", "re", "reply", "replied", "email", "emails", "message", "inbox", "sent",
        "unread", "read", "please", "thanks", "thank", "regards", "best", "hello", "hey", "dear",
        "update", "updated", "updates", "notification", "notifications", "confirm", "confirmation",
        "receipt", "order", "account", "newsletter", "unsubscribe", "view", "click", "here",
        # generic verbs/nouns/adverbs
        "have", "has", "had", "was", "were", "are", "will", "would", "can", "could", "should",
        "this", "that", "these", "those", "there", "their", "then", "than", "from", "into",
        "out", "off", "our", "not", "but", "all", "any", "some", "new", "old", "get", "got",
        "now", "today", "tomorrow", "week", "weeks", "day", "days", "time", "times", "next",
        "last", "soon", "just", "need", "needs", "want", "let", "lets", "know", "see", "look",
        "looking", "made", "make", "done", "doing", "going", "good", "great", "hi",
        "info", "information", "details", "detail", "note", "notes", "list", "check", "quick",
        "question", "questions", "request", "following", "follow", "up", "back", "over",
        "morning", "afternoon", "evening", "night", "tonight", "yesterday", "yes", "no",
        # ordinals, weekdays, months — recur constantly but never name a project
        "due", "first", "second", "third", "fourth", "fifth", "final", "draft",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "january", "february", "march", "april", "june", "july", "august", "september",
        "october", "november", "december",
        # interrogatives / connectives (often from the user's own questions to Jarvis)
        "what", "when", "where", "who", "whom", "which", "whose", "how", "why", "coming",
        "whats", "hows", "wheres", "whos",
    }
)

# Very short acronyms worth keeping despite the 3-char minimum (extend as real projects appear).
_KEEP_SHORT = frozenset({"ai", "ml", "hr", "qa", "os", "ux", "ui"})


def distinctive_tokens(text: str) -> list[str]:
    """Lowercase, de-duplicated distinctive tokens from free text (subjects, titles, notes)."""
    if not text:
        return []
    out: list[str] = []
    for raw in _WORD.findall(text.lower()):
        token = raw.strip("'-_+")
        if not token or token in _STOPWORDS:
            continue
        if len(token) < 3 and token not in _KEEP_SHORT:
            continue
        if token.isdigit():
            continue
        if token not in out:
            out.append(token)
    return out


def display_name(token: str) -> str:
    """How a project token is shown: acronym-ish tokens uppercased, else title-cased."""
    if token.isupper() or (len(token) <= 5 and token.isalpha() and token not in {"about"}):
        # Short all-alpha tokens are usually acronyms/proper nouns (ARISE, Union) — uppercase.
        return token.upper()
    return token[:1].upper() + token[1:]
