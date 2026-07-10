"""Live source-status registry (Phase 2D.3).

The single, authoritative answer to "can Jarvis actually reach this source right now?" Capability
statements ("I can't access your email") must come from here — computed live from real connection
state — never from the LLM, which does not know and would guess (root-cause defect R4). There is no
status table: a cached capability would go stale and lie, so status is always derived on demand.
"""
