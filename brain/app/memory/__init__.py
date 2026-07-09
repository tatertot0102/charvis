"""Memory layer (Phase 2C.5) — the evidence-backed model of "me".

A durable support layer *beneath* the ContextResolver: a consolidation pass turns historical
Gmail / Calendar / captures / conversations into decision-useful conclusions, patterns, and
commitments, each carrying confidence, an evidence breakdown, a source list, and timestamps.
Read-only w.r.t. external systems — nothing here sends, deletes, or mutates Gmail/Calendar.

Dependency direction: gather → derive → persist (store) → read by ContextResolver / API / Telegram.
"""
