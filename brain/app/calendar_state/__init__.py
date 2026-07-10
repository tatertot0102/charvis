"""Truthful calendar state (Phase 2D.2).

`snapshots` mirrors real Google Calendar events into a provider-backed cache; `schedule` answers
week/day queries from that cache ONLY — never from the LLM, conversation history, or memory. This is
the structural cure for the "invent a schedule" bug: the answer can only contain events Google
actually returned.
"""
