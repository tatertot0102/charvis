# MVP.md — The Smallest Useful Jarvis

> The 80/20 slice: the least we can build that you'd actually use **every day within a few days**,
> while staying true to the architecture in `EXECUTION_PLAN.md`. Everything not listed here is
> explicitly **deferred** — not forgotten.

---

## The MVP in one sentence

**"The Briefing Secretary":** you text Jarvis on Telegram; it captures anything you throw at it,
reads your Google Calendar and Gmail (read-only), and every morning (and on demand) tells you what
your day looks like, what you're waiting on, and the single most important next thing — all powered
by a **local LLM on the Pro**, with **zero write/act capability**.

Why this is the right MVP: the daily pain is *orientation and capture*, not automation. A read-only
briefer removes the morning scramble and the "I'll remember it later" leak on day one, at the
**lowest possible risk** (nothing can send, delete, or spend). It exercises the whole spine —
Telegram ↔ conversation ↔ local LLM ↔ life model ↔ integrations ↔ prep — so every later phase bolts
onto proven rails.

---

## What's IN the MVP

### 1. Talk to it (Telegram ↔ local LLM)
- Text the bot; it replies via the local model behind the `LLMProvider` abstraction.
- Whitelisted to your Telegram user ID only.
- Long-polling (no public port).

### 2. Frictionless capture
- Any one-liner ("call the dentist", "Union essay due Friday", "ask Sam about the invoice") is
  parsed, filed to the DB as a `capture`, and acknowledged.
- Capturing is never more work than the thought — send a message, done.

### 3. Read-only life view
- **Google Calendar (read):** today's / upcoming events.
- **Gmail (read):** unread + a simple "who seems to be waiting on a reply from me" signal (basic
  heuristic, not full coordination yet).
- Data is cached in Postgres and refreshed on a schedule.

### 4. Life model — seeded
- Captures + calendar + mail populate the first version of the life model (projects/tasks,
  deadlines, lightweight people list).
- A nightly consolidation job compacts it into working memory the LLM reads.

### 5. Daily briefing + on-demand answers
- **Morning push** to Telegram: today's events + open captures/deadlines + **one** suggested next
  action.
- **On demand:** "what's my day?", "what am I waiting on?", "what's most important right now?" →
  answered from the life model, not raw inboxes.

### 6. Ask-when-unsure
- If priority/intent is ambiguous, Jarvis asks one short concrete question and **stores your answer**
  to the life model so it decides better next time.

### 7. Minimal dashboard (optional within MVP, nice-to-have)
- A single **Today** view (timeline of events + captures) + the current suggested next action.
- If time-boxed, ship this right after the Telegram MVP; Telegram alone is already useful.

---

## What's OUT of the MVP (deferred, by phase)

| Deferred capability | Why deferred | Comes in |
|---|---|---|
| **Any write/act** (send email, move calendar, add/complete tasks, send SMS) | Highest risk; needs the autonomy gate proven first | Phase 4 |
| Autonomy tiers + approval queue (exercised) | No writes in MVP → nothing to gate yet (still design the gate; keep everything Tier 4) | Phase 4 |
| Full planner (decomposition, scheduling into free calendar time, overload detection, re-planning) | MVP briefs from existing data; true planning is the next value tier | Phase 3 |
| Native agents (mac-agent, chrome-ext, Android live context) | Not required to be useful; adds device/permission setup risk | Phase 2 (post-MVP) / can slot in early if desired |
| Coordination (waiting-on ledger, auto-nudges, people-memory drafting) | Depends on write actions + richer people model | Phase 5 |
| Prep briefings from docs, dispatcher/tool routing, weekly review, learning/playbooks | Polish on top of a working core | Phase 5 |
| Trust graduation, off-limits zones, voice | Later maturity | Phase 6 |
| Drive/Docs, Todoist writes | Read-only Todoist optional in MVP; writes later | Phase 2 read / Phase 4 act |

**Note:** Todoist **read** and a basic **Today dashboard** are cheap and may be pulled into the MVP if
they land quickly; they're borderline-in. Everything in the table above is firmly out.

---

## MVP build sequence (maps to EXECUTION_PLAN phases)

1. **Phase 0 — Deploy proof.** Empty brain (`/health`) + Postgres in Docker, reachable from the phone
   over Tailscale; Air→Pro deploy proven. *(EXTERNAL_ACTIONS 0.1–0.4.)*
2. **Phase 1 — Talk + capture.** Telegram ↔ `/chat` ↔ local LLM; capture one-liners; clarifying
   questions. *(EXTERNAL_ACTIONS 1.1–1.4.)*
3. **MVP read slice (subset of Phase 2).** Google OAuth (Calendar + Gmail **read**); cache to DB;
   seed the life model. *(EXTERNAL_ACTIONS 2.1–2.3.)*
4. **MVP briefing slice (subset of Phase 3).** `GET /state/today`, the morning briefing job, and the
   on-demand "day / waiting-on / next action" answers.
5. **(Optional) Today dashboard.** Single React view over `/state/today`.

Stop there. That is a system you use every morning. Then continue into full Phase 2 (native agents,
more connectors) and Phase 3 (real planner).

---

## MVP definition of done

- On the **Pro**, `docker compose up` brings up brain + Postgres; native Ollama serves the model.
- From the **phone**, you text the bot and get useful replies.
- Sending "essay due Friday" files a capture and Jarvis can recall it.
- Asking "what's my day?" returns real calendar events + captures for today.
- A **morning briefing** arrives on Telegram unprompted.
- Ambiguous input triggers a clarifying question whose answer is remembered.
- **No endpoint can perform a write action** (all integrations read-only; act paths disabled/Tier 4).
- Deploys unchanged Air→Pro; smoke tests pass; docs + setup + rollback notes exist for each phase.

---

## Success signal

If, within a few days, your morning starts with Jarvis's briefing instead of manually opening
Calendar + Gmail + your task list — and you capture stray thoughts by texting it instead of losing
them — the MVP has done its job, and every later phase is additive value on a trusted base.
