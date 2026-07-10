# CLAUDE.md — "Jarvis" Personal Secretary System

> Build spec for Claude Code. This file defines **every program** needed for the full
> version, how they fit together, and the order to build them. Read this whole file
> before writing any code. Build in phases; do not skip the Phase 0 deploy proof.

---

## 0. Golden rules for whoever builds this

1. **The brain is portable.** Everything in the core service must run unchanged on either
   Mac. No hardcoded paths, hostnames, or machine assumptions. All machine-specific values
   live in `.env`, never in code.
2. **Dev on the Air, deploy to the Pro.** Develop and test on the MacBook Air with
   `docker compose up`. Ship to the MacBook Pro (the always-on backend) by pulling the same
   repo and running the same command with the Pro's `.env`.
3. **Data layer and action layer are separate.** Reading my life ≠ acting on my life. Never
   let a read path trigger a write without going through the autonomy tier system (§7).
4. **Nothing irreversible fires without clearing its autonomy tier.** Send, delete, post,
   spend → gated. See §7.
5. **OS-touching code cannot live in the container.** Reading open apps/tabs and "open this
   app" actions run as thin **native agents** on each Mac and talk to the brain over
   Tailscale. Keep them dumb; all reasoning stays in the brain.
6. **Prove the deploy path before building features.** Phase 0 is an empty container that a
   phone can reach over Tailscale. Do that first.
7. **Reason, never fabricate (permanent).** Jarvis may reason under uncertainty — infer confidence,
   rank possibilities, ask clarifying questions — but it may **never invent facts**. Google Calendar,
   Gmail, Todoist, and the local database are the **only** sources of truth. Every factual statement
   shown to me (events, titles, times, attendees, email subjects/senders, projects, commitments,
   people) must be traceable to provider-backed or DB-backed evidence. When evidence is insufficient,
   **ASK — never guess.** The execution layer must reject unknown / fabricated / stale / deleted ids.

---

## 1. System shape (plain English)

A personal secretary I **talk to by text** (voice later) that:
- sees my whole life (email, calendar, tasks, texts, location, battery, what I'm doing now),
- keeps its **own memory** of my priorities/projects/people, separate from any app,
- **decides** what matters via an explicit priority model, and **asks me** when it's unsure,
- plans execution and slots it into real calendar time,
- coordinates with people (drafts/sends, tracks who's waiting on whom),
- acts on a **graduated leash** it earns over time,
- knows its limits and **dispatches** jobs to better tools (e.g. Claude Cowork for file
  reorg), and
- shows all of it in **one dashboard**.

---

## 2. Repository layout (monorepo)

```
jarvis/
├── docker-compose.yml          # brain + db, one command up
├── .env.example                # every config key, no secrets committed
├── README.md                   # setup + deploy steps (Air → Pro)
├── brain/                      # THE CONTAINERIZED CORE (portable)
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py             # FastAPI entrypoint, mounts routers
│   │   ├── config.py           # loads .env, no hardcoding
│   │   ├── db/                 # models, migrations, session
│   │   ├── api/                # HTTP routers (see §3)
│   │   ├── llm/                # Claude client wrapper, prompt builders
│   │   ├── lifemodel/          # persistent model of "me" (§5)
│   │   ├── planner/            # priority model + decomposition + scheduling (§6)
│   │   ├── autonomy/           # tier engine + approval queue (§7)
│   │   ├── conversation/       # text chat handler, intent, clarifying Qs (§4)
│   │   ├── coordination/       # waiting-on tracking, follow-up nudges (§8)
│   │   ├── prep/               # briefings + draft-from-template (§9)
│   │   ├── dispatch/           # tool-awareness / routing (§11)
│   │   ├── learning/           # correction capture, playbooks (§12)
│   │   ├── integrations/       # cloud connectors (§10)
│   │   └── scheduler/          # APScheduler jobs: daily/weekly/monitor loops
│   └── tests/
├── agents/                     # NATIVE, run outside the container
│   ├── mac-agent/              # runs on BOTH Air and Pro
│   │   ├── agent.py            # reports running apps; executes open-app actions
│   │   └── launchd/            # plist to keep it alive
│   ├── chrome-extension/       # tabs + history → brain
│   └── android-tasker/         # Tasker profiles export + setup guide (location,
│                               #   battery, SMS read/send, notification forwarding)
├── dashboard/                  # web frontend (§14)
│   ├── package.json
│   └── src/
└── comms/
    └── text-channel/           # inbound/outbound text front door (§4)
```

---

## 3. The brain — API surface (FastAPI)

Build these routers. All require auth even on Tailscale (shared token in `.env`).

- `POST /ingest/{source}` — generic intake for agents (mac-agent, chrome-ext, android).
  Payloads: running_apps, active_tabs, location, battery, sms_in.
- `POST /chat` — inbound text message from me → returns Jarvis's reply + any actions taken.
- `GET /state/today` — unified timeline (calendar events + scheduled task blocks).
- `GET /state/waiting` — stalled items split by who's blocking.
- `GET /state/deadlines` — upcoming deadlines with computed urgency.
- `GET /state/context` — what I'm doing right now.
- `GET /state/next-action` — the single top recommendation.
- `GET /approvals` / `POST /approvals/{id}` — approval queue read + yes/no.
- `POST /capture` — frictionless one-liner intake (files + plans it).
- Internal action executors are **not** public endpoints; they're called by the planner/
  conversation layers through the autonomy gate.

---

## 4. Conversation layer (Jarvis front door) — text first

- **Channel:** start with a **Telegram bot** (fastest reliable two-way text; no carrier/SMS
  friction, works over data, trivial to send/receive). Abstract the channel behind a
  `TextChannel` interface so SMS-via-Android or a web chat can be swapped in later. Voice is
  a later front-end onto the same `/chat` brain.
- **Flow:** message → intent parse (LLM) → either answer, act (through autonomy gate), or
  **ask a clarifying question**.
- **Ask-when-unsure is mandatory:** if priority/intent is ambiguous, Jarvis asks a short,
  concrete question ("Union essay or Stony Brook first? Union's deadline is closer — which
  wins?"), then **stores the answer** to the life model so it decides better next time.
- **Frictionless capture:** any stray one-liner or (later) voice memo is filed and planned;
  capturing must never be more work than the thought.

---

## 5. Life model (its own memory — separate from any app)

A persistent store (DB tables + a summarized working memory the LLM reads) holding:
- Active **projects** and what each is **blocked on**.
- Standing **priorities** and deadlines.
- **Patterns** (deep-work hours, what I procrastinate on).
- **People**: who's slow to reply, who I owe, last contact, context per person.
- Updated continuously by ingest + conversation + a nightly consolidation job.
- This is what makes it feel like it knows me, not just mirrors my inbox. It is the source
  the planner and conversation layers reason over.

---

## 6. Planner (the actual brain)

- **Priority model (explicit, not vibes):** every decision weighs (a) deadline proximity,
  (b) consequence of missing, (c) who else is blocked, (d) effort-vs-payoff.
- **On genuine ties / unclear priority → ask me** (via §4), don't guess; store the reasoning.
- **Decomposition:** goal → ordered sub-steps with time estimates and dependencies.
- **Scheduling:** slot steps into **real** open calendar time; check conflicts; don't just
  pile onto a list.
- **Overload detection:** flag an unrealistic day *before* I hit it.
- **Re-planning:** when something slips, re-plan automatically.
- **Batching:** group similar work to cut context-switching.
- **Rhythms:** daily rundown (tactical) + **weekly review** (strategic). Anything that slips
  3 daily reviews running is escalated or explicitly killed — never silently re-added.

---

## 7. Autonomy tiers + approval queue

Four tiers, configurable per action type in `.env`/DB, not a single on/off:
1. **Silent** — do it, don't bother me (batching, prep briefs, organizing).
2. **Act-then-notify** — do it, tell me after (moving a task block).
3. **Propose-and-wait** — draft it, wait for my yes (most emails/texts).
4. **Never without me** — anyone who matters, anything with money.

- Every executor call routes through the tier engine first.
- Tier-3 items land in the **approval queue** (dashboard + phone), one-tap yes/no.
- Actions **graduate** toward more autonomy as trust is earned (track override rate).

---

## 8. Coordination

- Draft/send emails/texts to schedule, confirm, follow up (within tier).
- Track **"I'm waiting on them" vs "they're waiting on me"** so nothing dies in an inbox.
- Auto-nudge when something's gone quiet ("no reply in 4 days — follow up?").
- Use people-memory (§5) so coordination is thoughtful, not mechanical.

---

## 9. Prep & research

- Before a meeting/interview/appointment, auto-assemble a short briefing from relevant
  emails, notes, and docs.
- Pre-draft documents from template + my data so I never start blank.

---

## 10. Integrations (cloud connectors — data + action)

Each is a module under `brain/app/integrations/` with a read side and (where relevant) an
action side that respects §7.

| Connector | Read | Act |
|---|---|---|
| Gmail (API, OAuth) | threads, who's waiting | send (draft-first) |
| Google Calendar | commitments, free/busy | create/move blocks |
| Google Drive/Docs | files + state | edit docs |
| Todo (Todoist or Google Tasks) | tasks + deadlines | add/complete |
| SMS (via android agent) | inbound texts | send (via agent) |
| Location / battery (android agent) | current values | — |

OAuth tokens live in the DB/secret store, never in code. Provide a one-time auth flow.

---

## 11. Tool-aware dispatcher

- Knows its own limits and the wider toolkit.
- Classifies "what kind of job is this," then either does core secretary work itself or
  **routes**: "reorganize my files" → **Claude Cowork**; a document → a Docs tool; a deck →
  a slides tool. Offers to kick the handoff off.

---

## 12. Learning

- Capture every **correction** (I override a plan, move a scheduled block, rewrite a draft)
  as signal; adjust future behavior instead of repeating the mistake.
- Turn recurring multi-step jobs into **playbooks** it recognizes and re-runs instead of
  re-decomposing from scratch.

---

## 13. Onboarding, trust & boundaries

- **Cold start:** deliberately dumb on day one; asks more, acts less, stays in low tiers;
  graduates as it learns patterns.
- **Boundaries:** explicit off-limits zones — certain chats/accounts/hours it does **not**
  observe or act on. Defined in config, honored everywhere. "Know everything" *with chosen
  blind spots*, not total self-surveillance.

---

## 14. Dashboard (web, served over Tailscale)

Unifies the separate apps into one view without replacing them:
- **Today** — one timeline blending calendar events + scheduled task blocks.
- **Waiting-on** — stalled items, split by who's holding them up.
- **Deadlines** — upcoming, urgency escalating visually as they near.
- **Live context strip** — what I'm doing right now (from agents).
- **Suggested next action** — one prominent, always-current recommendation.
- **Approval queue** — one-tap yes/no on anything pending.

Stack: lightweight SPA (React + Vite). Talks only to the brain's API. No business logic in
the frontend.

---

## 15. Native agents (outside the container)

- **mac-agent** (runs on Air *and* Pro): reports running apps (via `NSWorkspace`/`osascript`);
  executes "open app / open URL / close tabs" actions; kept alive by launchd; auth'd to brain.
- **chrome-extension** (both Macs): pushes active tabs + history to `/ingest`.
- **android-tasker**: profiles for location, battery, SMS read/send, notification forwarding,
  each POSTing to the brain's Tailscale address. Ship an export + a written setup guide.

---

## 16. Infrastructure

- **Networking:** Tailscale mesh across Air, Pro, Android. No public ports. Brain binds to
  the Tailscale interface; every endpoint requires the shared auth token.
- **Container:** `docker-compose.yml` defines `brain` + `db` (Postgres; SQLite acceptable
  for earliest phases). One `docker compose up`.
- **Config:** `.env` for all secrets/hosts; commit only `.env.example`.
- **Source control:** Git repo (GitHub or local). Deploy = pull + `.env` + compose up.
- **Deploy path (Air → Pro):** install Docker on Pro → clone → drop Pro `.env` →
  `docker compose up`. Comes up identically. Native agents installed per-machine.

---

## 17. Build order (phases — do in sequence)

- **Phase 0 — Deploy proof.** Empty containerized brain (`/health` endpoint) + Postgres,
  reachable from my phone over Tailscale. Prove Air→Pro deploy works. **Nothing else until
  this is done.**
- **Phase 1 — Talk to it.** Telegram text channel ↔ `/chat` ↔ Claude LLM. It can converse,
  capture one-liners to the DB, and ask clarifying questions. No integrations yet.
- **Phase 2 — See my life (read-only connectors).** Starts as Calendar (2A) + Gmail (2B) read,
  then unified intelligence layer:
  - **2A (done):** Google Calendar read-only, OAuth flow, `GET /calendar/today`.
  - **2B (done):** Gmail read-only + classification + waiting-on ledger + people life-model.
  - **2C (done):** Unified Intelligence: Combine Calendar + Gmail + waiting-on into context-aware Telegram 
    replies. `/state/today`, `/state/waiting`, `/state/deadlines`, `/state/next-action`. Meeting briefings.
  - **2C.5 — Deep Context + Better Judgment:** **Turn historical data into useful context for today's
    decisions.** Long-range lookback/lookahead across all sources. Pattern detection (recurring people,
    projects, deadlines, response patterns) — but *only* patterns that improve prioritization, meeting
    prep, next-action, deadline awareness, or decision-making. Every durable conclusion carries a
    **confidence score (0.0–1.0), supporting evidence, and a source list**, and must be **explainable**
    ("I think ARISE is a primary project because: 12 Gmail threads, 6 calendar events, mentioned in
    Telegram → confidence 0.96"). **Memory-inspection endpoints** (`GET /memory/{conclusions,patterns,
    projects,people,commitments}`) and Telegram introspection ("what do you know about me?", "why do you
    think Dana matters?", "show low-confidence conclusions"). **Utility-first rule:** store only
    conclusions that change a decision; never store trivia. **Read-only** — no writes.
  - **2D (done):** Calendar Actions with Confirmation. Calendar write connector (create/update/delete
    events, find free time, propose blocks, detect conflicts) + `pending_calendar_actions` approval
    queue + `calendar.events` scope. **Always draft-then-confirm:** move/create/cancel request → Jarvis
    proposes the exact change → user must reply "CONFIRM" (or POST `/approvals/{id}/confirm`) to execute.
    Endpoints `GET /approvals`, `POST /approvals/{id}/{confirm,cancel}`. Tests prove: no write without
    confirmation, only the latest pending confirms, wrong/expired confirmations don't execute, ambiguous
    requests ask a clarifying question. No email sends; no other writes yet.
  - **2D.1 (done):** Calendar Resolution Hardening. **Confidence-scored** event resolution with cited
    evidence (title-keyword, **acronym** DSI→Data Science Institute, fuzzy, attendee, location,
    description, recurring-series, time-of-day) over configurable lookback/lookahead. **Bulk actions**
    ("delete all future DSI events") that list count + first-N matches + per-event confidence + why,
    and require the stronger **`CONFIRM DELETE`** (a plain `CONFIRM` can't fire a bulk delete). Zero
    matches → asks, never fabricates; several distinct → asks which. Execution re-validates every id
    against Google — unknown/fabricated/stale/deleted ids are rejected (Golden Rule #7). Migration
    `0007`. Enshrines the permanent no-fabrication principle.
  - **2D.2 (done):** Truthful Calendar State + Persistent Commitments. Fixes a real hallucination bug
    (after deleting DSI events, "what is my week?" made Jarvis invent a schedule + placeholder text +
    a false "I've updated your schedule"). Architecture: reality (Google) → **calendar_snapshots**
    (provider-backed cache) → **commitments** (durable life understanding) → memory → resolver.
    Week/schedule queries answered **deterministically from snapshots** (rebuild-then-read = always
    fresh), never the LLM/conversation/memory. **Commitments** table (distinct from `ExtractedCommitment`):
    naming corrections ("it is ECE Machine Learning Lab") update memory and NEVER touch/claim a calendar
    change; a recurrence statement ("it's every weekday 10–2") stores evidence + drafts a CONFIRM-gated
    recurring create (RRULE support added to `calendar_write`/`execute`). **Truth guard** (core fix):
    hardened system prompt + post-filter that blocks placeholder text and false write-claims, replacing
    them with a safe message; Jarvis says "I updated your schedule" ONLY after proposal→CONFIRM→write→
    snapshot rebuild. Deleting a calendar event NEVER erases a commitment. Migration `0008`. Read-mostly:
    no email sends; all writes still draft-then-confirm.
  - **2E — Todoist read:** Tasks, projects, due dates. `/todoist/tasks`, `/todoist/upcoming`.
  - **2F — Dashboard:** Read-only React SPA. Today + waiting-on + deadlines + next-action views.
  - **2G — Device context:** mac-agent (running apps), chrome-ext (tabs), android-tasker (location/battery).
    `/ingest/{source}`, `/state/context`.
- **Phase 3 — Think.** Planner (§6): decomposition, priority model, scheduling into free
  calendar time, overload detection, life-model fact extraction (projects/deadlines from content),
  daily rundown.
- **Phase 4 — Act (gated).** Autonomy tiers + approval queue (§7). Turn on write actions:
  send email (draft-first), move/update task blocks, add/complete tasks, send texts via agent. Expand
  confirmation to non-calendar actions.
- **Phase 5 — Secretary polish.** Coordination + follow-up nudges (§8), prep briefings (§9),
  dispatcher/tool-routing (§11), weekly review, learning + playbooks (§12).
- **Phase 6 — Trust & boundaries.** Autonomy graduation, off-limits zones (§13), then voice
  front-end onto the existing `/chat` brain.

Each phase ends with: it runs on the Air via compose, deploys clean to the Pro, and has
tests for the new surface.

---

## 18. Definition of done (full version)

Every component in §2 exists and is wired; all six phases pass; the brain deploys unchanged
Air→Pro; agents run natively on each device; and I can text Jarvis, have it plan my day
against my real calendar, coordinate with people on a leash it's earned, hand off jobs it
shouldn't do itself, and see all of it in one dashboard.
