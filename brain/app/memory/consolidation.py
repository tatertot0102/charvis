"""Consolidation (Phase 2C.5) — the periodic pass: gather → derive → persist.

This is the writer beneath the ContextResolver. It optionally refreshes the Gmail mirror first, then
turns the assembled history into evidence-backed conclusions/patterns/commitments. Read-only w.r.t.
external systems — it only writes Jarvis's own memory tables. Run on demand (endpoint / Telegram) or,
later, from a scheduler; there is no background job in this phase.
"""
from __future__ import annotations

from app.integrations.google import gmail
from app.memory import derive, gather, store
from app.memory.store import PersistResult
from app.telemetry import get_logger

log = get_logger(__name__)


async def consolidate(account: str = "default", sync_first: bool = True) -> PersistResult:
    """Run one full consolidation pass and return what was persisted."""
    if sync_first:
        try:
            from app.integrations.google import sync

            await sync.sync_recent(account)
        except gmail.NotConnectedError:
            log.info("consolidate_gmail_unavailable")  # DB-only consolidation still works
        except Exception as exc:  # noqa: BLE001 — a sync hiccup must not abort consolidation.
            log.error("consolidate_sync_failed", error=str(exc), error_type=type(exc).__name__)

    signals = await gather.gather(account)
    memory = derive.derive(signals)
    result = await store.persist(memory, account)
    log.info("memory_consolidated", account=account, conclusions=result.conclusions)
    return result


async def ensure_consolidated(account: str = "default") -> bool:
    """Consolidate once if memory is empty (so first-time introspection has something to show).

    Returns True if a consolidation run happened. Cheap when memory already exists (single indexed
    lookup). Does not refresh stale memory — that's the explicit consolidate() / endpoint's job.
    """
    if await store.has_any_conclusions(account):
        return False
    await consolidate(account, sync_first=False)
    return True
