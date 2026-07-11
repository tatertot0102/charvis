"""Dashboard aggregation layer (Phase 2F.0).

The dashboard is NOT a second truth system. It reads the same Unified Knowledge Engine (WorldModel)
and existing services (calendar, waiting, deadlines, approvals, source registry) that Telegram/chat
use, and assembles them into ONE typed DashboardState. Mode and focus selection are DETERMINISTIC
(pure functions over signals) — the local model may only suggest validated layout/navigation commands,
never invent sections or fabricate facts. Every factual item carries a truth badge tracing its origin.
"""
