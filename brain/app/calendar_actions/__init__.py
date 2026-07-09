"""Calendar actions with confirmation (Phase 2D).

THE HARD RULE (CLAUDE.md §7, tier-3): no calendar write ever fires directly. A natural-language
request ("move my meeting to 4") is parsed, the likely event is resolved, a *pending* action is
drafted with the exact proposed change, and the user is shown that change. Execution happens only
after an explicit "CONFIRM". Anything else leaves it pending; a stale proposal expires; a new
proposal supersedes the old one.

Layering:
  parse     — deterministic NL → ParsedRequest (action type, target/time hints)
  resolve   — pick the likely event from a list (single / ambiguous / none) — pure
  conflicts — conflict detection + free-time lookup over calendar reads
  store     — pending_calendar_actions persistence (draft / confirm / cancel / supersede)
  propose   — orchestrate parse+resolve+conflicts → a drafted pending action or a clarifying Q
  execute   — replay a *confirmed* pending action through the write connector (the ONLY writer)
  service   — the front door: request(text) / confirm_latest() / cancel_latest()
"""
