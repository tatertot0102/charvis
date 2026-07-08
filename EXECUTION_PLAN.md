# EXECUTION_PLAN.md — Jarvis Master Roadmap

> The authoritative build plan. Read alongside `CLAUDE.md` (product spec), `TECH_STACK.md`
> (technology choices + rationale), `MACHINE_SETUP.md` (per-device setup), `MVP.md` (smallest
> useful slice), and `EXTERNAL_ACTIONS.md` (everything you must do by hand outside the repo).
>
> **Prime directive (unchanged from CLAUDE.md):** the brain is portable, config-driven, and
> deploys unchanged from the Air to the Pro. **Amendment (this project):** the AI backend runs
> entirely on a **local LLM on the MacBook Pro**, reached through a single provider abstraction.
> No application code ever names a specific model vendor.

---

## 0. Executive summary

Jarvis is a personal secretary you text (Telegram first), backed by a portable FastAPI "brain"
in Docker, a Postgres database, and a **local LLM** served on the always-on MacBook Pro. The
brain reads your life (calendar, mail, tasks, device signals), keeps its own memory model of
you, plans your day, and — only through a hard autonomy gate — acts on your behalf.

We build in **thin vertical slices**. Each phase is independently runnable, testable, and
deployable Air→Pro before the next begins. The MVP (see `MVP.md`) is a **read-only briefing
secretary** reachable within a few days: text it, it captures tasks, reads your calendar and
mail, and briefs you every morning. Writing/acting is deliberately deferred behind the autonomy
tier engine.

---

## 1. Architecture

### 1.1 System diagram (logical)

```
┌──────────────────────────────────────── Tailscale mesh (no public ports) ───────────────────────────────────────┐
│                                                                                                                    │
│   ANDROID PHONE                     MacBook AIR (dev)                        MacBook PRO (always-on server)         │
│   ┌───────────────┐                 ┌──────────────────┐                    ┌──────────────────────────────────┐  │
│   │ Telegram app  │                 │ docker compose   │   deploy (git      │  docker compose up               │  │
│   │  ⇅ chat       │                 │  (same stack,    │   pull + Pro .env) │  ┌────────────┐  ┌─────────────┐ │  │
│   │ Tasker        │                 │  points LLM at   │ ─────────────────► │  │  brain     │  │  postgres   │ │  │
│   │  → location   │                 │  Pro's Ollama)   │                    │  │  (FastAPI) │◄─┤  + pgvector │ │  │
│   │  → battery    │                 └──────────────────┘                    │  └─────┬──────┘  └─────────────┘ │  │
│   │  → SMS        │                          ▲                              │        │                         │  │
│   └──────┬────────┘                          │ native agents                │        ▼                         │  │
│          │                                    │ (run on BOTH Macs)          │  ┌────────────┐                  │  │
│          │ POST /ingest, /chat                │  mac-agent, chrome-ext      │  │  Ollama    │  local model     │  │
│          └────────────────────────────────────┴──────────────┬─────────────┼─►│ (LLM host) │  (Apple Silicon) │  │
│                                                               │             │  └────────────┘                  │  │
│                                                               │             └──────────────────────────────────┘  │
│   Dashboard (React SPA, served by brain) ─────────────────────┘  talks only to brain API                         │
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

External clouds (reached from brain over the internet, OAuth):  Gmail · Google Calendar · Google Drive · Todoist
```

### 1.2 Brain internal architecture (layers, strict dependency direction)

```
                        ┌─────────────────────────────────────────────┐
   inbound              │  api/         FastAPI routers (HTTP surface) │   ← only layer that speaks HTTP
   (Telegram, agents,   │  comms/       TextChannel (Telegram adapter) │
    dashboard)          └───────────────┬─────────────────────────────┘
                                         │ calls
                        ┌────────────────▼─────────────────────────────┐
   orchestration        │  conversation/  intent → answer/act/ask      │
                        │  planner/       priority · decompose · schedule│
                        │  coordination/  waiting-on · nudges           │
                        │  prep/          briefings · draft-from-template│
                        │  dispatch/      route to external tools       │
                        │  learning/      corrections · playbooks       │
                        └───────┬───────────────────────┬──────────────┘
                                │ reads/writes          │ requests actions
                        ┌───────▼──────────┐   ┌─────────▼────────────────┐
   core services        │  lifemodel/      │   │  autonomy/  ActionGateway │  ← the ONLY path to any write
                        │  (memory of me)  │   │  tier engine + approvals  │
                        └───────┬──────────┘   └─────────┬────────────────┘
                                │                        │ gated calls only
        ┌───────────────────────▼──────────┐   ┌─────────▼──────────────────┐
   infra │  db/   models · session · migr.  │   │  integrations/ Gmail·Cal·   │
         │  llm/  LLMProvider + adapters     │   │  Drive·Todoist·SMS (read+act)│
         │  scheduler/  APScheduler jobs     │   └──────────────────────────────┘
         │  config/  pydantic-settings (.env)│
         │  telemetry/ structlog             │
         └───────────────────────────────────┘
```

**Rules of the dependency graph (enforced in review):**

1. `api/` and `comms/` never touch `db/`, `integrations/`, or `llm/` directly — they call
   orchestration services.
2. **Every write/side-effecting action goes through `autonomy/ActionGateway`.** Integrations
   expose an "act" method but the orchestration layers may only reach it via the gateway. A read
   path physically cannot trigger a write (Golden Rule #3).
3. **Nothing imports a concrete LLM vendor.** Everything depends on the `LLMProvider` interface
   in `llm/`. Swapping Ollama→Anthropic is a `.env` change (Golden Rule: portability).
4. `lifemodel/` is the single source of truth the planner and conversation reason over — not the
   raw inboxes.

### 1.3 The LLM provider abstraction (the central amendment)

```
         application code (conversation, planner, prep, learning)
                              │  depends only on ▼
                    ┌──────────────────────────────┐
                    │  llm/provider.py              │
                    │  class LLMProvider(Protocol): │
                    │    complete(messages, tools)  │
                    │    embed(texts)               │
                    │    (JSON/structured helpers)  │
                    └───────────────┬───────────────┘
        ┌───────────────┬───────────┴───────┬───────────────┬──────────────┐
        ▼               ▼                   ▼               ▼              ▼
   OllamaProvider  LMStudioProvider   OpenAICompatProvider  OpenAIProvider AnthropicProvider
   (default, Pro)  (OpenAI-compat)    (vLLM/LocalAI/etc.)   (cloud opt-in)  (cloud opt-in)
        │               │                   │
        └───────────────┴───────────────────┘  All four speak the OpenAI Chat Completions shape.
                                                Implemented as ONE adapter (base_url + model swap).
```

- **Implementation strategy:** a single `LLMProvider` interface we own. Because Ollama, LM Studio,
  vLLM/LocalAI, and OpenAI all expose an **OpenAI-compatible** endpoint, one adapter (the `openai`
  SDK pointed at a configurable `LLM_BASE_URL`) covers 4 of the 5 providers. Anthropic gets a
  second small adapter. We wrap **LiteLLM** as the transport so we get retries, timeouts, and
  uniform tool-calling normalization "for free" — but the rest of the app only ever sees *our*
  interface, so LiteLLM itself is swappable. See `TECH_STACK.md §LLM`.
- **Selection:** `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_EMBED_MODEL` in `.env`. The
  factory in `llm/factory.py` returns the right adapter. **No other module knows or cares.**
- **Dev vs prod nuance (call-out):** the local model physically runs on the **Pro**. On the Air
  during dev you either (a) point `LLM_BASE_URL` at the Pro's Ollama over Tailscale, or (b) run a
  small model locally on the Air. Both are pure config — the code is identical. This is exactly
  what the provider abstraction buys us.
- **Structured-output discipline:** local models are less reliable at JSON/tool-calls than frontier
  APIs. The `llm/` layer provides a `structured()` helper: request JSON/tool schema → validate with
  Pydantic → on failure, one bounded "repair" retry → then fail loudly. Never let malformed model
  output silently corrupt the life model.

---

## 2. Repository layout

Mirrors `CLAUDE.md §2` with the LLM abstraction and a few pragmatic additions (marked ★).

```
jarvis/
├── docker-compose.yml           # brain + db (+ optional ollama profile), one command up
├── .env.example                 # every config key; no secrets committed
├── README.md                    # setup + Air→Pro deploy steps
├── EXECUTION_PLAN.md            # ← this file
├── EXTERNAL_ACTIONS.md
├── TECH_STACK.md
├── MACHINE_SETUP.md
├── MVP.md
├── Makefile                     # ★ dev ergonomics: make up / test / lint / fmt / migrate
├── brain/
│   ├── Dockerfile
│   ├── pyproject.toml           # uv-managed
│   ├── alembic.ini              # ★ migrations config
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint, mounts routers, startup checks
│   │   ├── config.py            # pydantic-settings; loads .env; fail-fast on missing secrets
│   │   ├── telemetry.py         # ★ structlog setup, request IDs
│   │   ├── deps.py              # ★ FastAPI dependency providers (DB session, auth, services)
│   │   ├── db/                  # models, session, alembic/versions
│   │   ├── api/                 # routers: ingest, chat, state, approvals, capture, health
│   │   ├── llm/                 # provider.py (interface), factory.py, adapters/, structured.py
│   │   ├── lifemodel/           # projects, priorities, patterns, people; working-memory summary
│   │   ├── planner/             # priority model, decomposition, scheduling, overload, replan
│   │   ├── autonomy/            # ActionGateway, tier engine, approval queue
│   │   ├── conversation/        # chat handler, intent parse, clarifying-question flow, capture
│   │   ├── coordination/        # waiting-on tracking, follow-up nudges
│   │   ├── prep/                # briefings, draft-from-template
│   │   ├── dispatch/            # tool-awareness / routing (Cowork, Docs, Slides)
│   │   ├── learning/            # correction capture, playbooks
│   │   ├── integrations/        # base.py (Connector protocol) + gmail/ calendar/ drive/ todoist/ sms/
│   │   └── scheduler/           # APScheduler jobs: daily/weekly/monitor loops
│   └── tests/                   # unit + integration + e2e-ish; mirrors app/ layout
├── agents/
│   ├── mac-agent/               # runs on Air AND Pro (report apps; open-app/url actions)
│   │   ├── agent.py
│   │   └── launchd/             # plist template
│   ├── chrome-extension/        # MV3: active tabs + history → /ingest
│   └── android-tasker/          # Tasker profiles export + written setup guide
├── dashboard/                   # React + Vite + TS SPA (talks only to brain API)
│   ├── package.json
│   └── src/
└── comms/
    └── text-channel/            # (folded into brain/app/comms for MVP; kept per spec for future
                                 #  standalone SMS/web front doors)
```

**Design note (redesign vs CLAUDE.md):** the spec places `comms/text-channel/` as a top-level
sibling. For the MVP the Telegram adapter lives inside `brain/app/comms/` behind a `TextChannel`
interface (fewer moving parts, one deployable). The top-level `comms/` folder is reserved for the
day a truly out-of-process front door (e.g., an SMS gateway) is warranted. This honors the spec's
intent (channel abstraction) without prematurely splitting a service.

---

## 3. Dependency graph (build order of components)

```
config ──► telemetry ──► db (models/session/migrations)
   │                        │
   └──► llm (provider/factory/adapters) ──┐
                                          ▼
                              conversation ◄── comms/TextChannel (Telegram)
                                 │  │
                    lifemodel ◄──┘  └──► api/chat, api/capture, api/health
                       │
        ┌──────────────┼───────────────────────────────┐
        ▼              ▼                                ▼
   integrations   planner ──► scheduler (daily/weekly)  autonomy/ActionGateway
   (read side)        │                                     ▲
        │             └──► prep (briefings) ────────────────┘  (writes gated)
        ▼
   coordination ──► dispatch ──► learning
        │
        ▼
   dashboard (consumes /state/*, /approvals)
```

**Critical path (longest chain that gates a usable product):**
`config → db → llm → conversation → comms(Telegram) → integrations(Calendar read) → prep(daily briefing)`

Everything else (native agents, Drive, Todoist, coordination, dispatch, learning, autonomy
writes) hangs off this spine and can be scheduled around it.

---

## 4. Execution phases

Each phase ends with the **same gate**: runs on the Air via `docker compose up`, deploys clean to
the Pro, passes smoke tests, has docs + setup + rollback notes. **One phase at a time; no starting
the next until the current is manually verified.**

| Phase | Name | Delivers | New external setup (see EXTERNAL_ACTIONS) | Est. effort |
|------:|------|----------|-------------------------------------------|-------------|
| **0** | Deploy proof | Empty containerized brain (`/health`) + Postgres, reachable from phone over Tailscale; Air→Pro deploy proven | Docker, Git/GitHub, Tailscale on all 3 devices | 0.5–1 day |
| **1** | Talk to it | Telegram ↔ `/chat` ↔ **local LLM** via provider abstraction; capture one-liners to DB; clarifying questions | Telegram bot token; **Ollama + model on Pro** | 2–3 days |
| **2** | See my life (read-only) | Gmail + Calendar + Todoist read connectors; life model starts populating; mac-agent + chrome-ext + Android ingest; Dashboard **Today** + **Live context** | Google OAuth (Gmail+Cal+Drive), Todoist token, Chrome ext load, mac perms + LaunchAgent, Tasker profiles | 4–6 days |
| **3** | Think | Planner: decomposition, priority model, schedule into free calendar time, overload detection, **daily rundown**; Dashboard **Deadlines** + **Waiting-on** | — (uses Phase-2 data) | 3–5 days |
| **4** | Act (gated) | Autonomy tiers + approval queue; write actions: send email (draft-first), move calendar blocks, add/complete tasks, send SMS via agent | Gmail send scope re-consent; SMS-send Tasker profile | 3–5 days |
| **5** | Secretary polish | Coordination + follow-up nudges; prep briefings from docs; dispatcher/tool routing; weekly review; learning + playbooks | Drive scope; Cowork/tool handles | 5–8 days |
| **6** | Trust & boundaries | Autonomy graduation (override-rate tracking); off-limits zones; then voice front-end onto `/chat` | Voice input choice (later) | 4–7 days |

**MVP line:** Phase 0 + Phase 1 + the **read + daily-briefing** subset of Phases 2–3 (Calendar
read, Gmail read, `/state/today`, morning briefing). Everything write-related is post-MVP. See
`MVP.md`.

**Phase 2 is shipped in read-only sub-phases (one deployable increment each):**
- **2A — Calendar (✓ verified):** Google OAuth (Web-app client, Fernet-encrypted tokens), read-only
  Calendar connector, `GET /calendar/today`, "what's my day?" on Telegram. Migration `0003`.
- **2B — Gmail (✓ verified):** `gmail.readonly` added to the same client; read-only Gmail connector
  (unread/today/search/thread); **deterministic** classification (importance, urgency,
  requires-response, promotional, calendar/deadline-related, FYI) stored in `email_messages`;
  **waiting-on ledger** (`waiting_items`, detection only — never sends); **people** life-model slice
  (`people`); `GET /gmail/{unread,today,search,waiting,thread/{id}}`; natural-language email intents
  on Telegram. Migration `0004`. External step: enable Gmail API + re-consent (EXTERNAL_ACTIONS §2.3b).

**Roadmap refinement (post-2B):** Originally Phase 2C was monolithic. Split into smaller, deployable increments:
- **2C — Unified Intelligence / Meeting Prep:** Combine Calendar + Gmail + waiting-on + people into
  context-aware replies. `GET /state/today` (calendar + task timeline), `GET /state/waiting` (waiting-on
  split), `GET /state/deadlines` (upcoming with urgency), `GET /state/next-action` (priority). Calendar
  event context resolver (find related emails, waiting-on context). Meeting briefing generator. Telegram:
  "what's my day?", "prep me for my next meeting", "what is this meeting about?", "what am I waiting on?",
  "what deadlines are coming up?". Migration `0005`.
- **2D — Todoist read:** Todoist OAuth connector (tasks, projects, due dates, completion). `GET /todoist/tasks`,
  `GET /todoist/upcoming`. Telegram task intents ("show my tasks", "what's overdue?"). Migration `0006`.
- **2E — Dashboard:** Read-only React/Vite SPA (no auth, talks only to brain API over Tailscale).
  Today view (timeline), waiting-on view (split), deadlines view (urgency escalation), next-action view.
- **2F — Device context / Native agents:** Agents outside container, POST to brain. mac-agent (running apps,
  active window, via launchd), chrome-extension (active tab), android-tasker (location, battery, SMS,
  notifications). `POST /ingest/{source}`, `GET /state/context`. Migration `0007`.

**Design note (2B & 2C):** Classification, intent routing, and context resolution are **deterministic**
(labels, thread structure, keyword heuristics, not LLM-based) — reliable, free, unit-testable. The local
model is reserved for open-ended conversation and future Phase 3 life-model reasoning.

**Deferred to Phase 3:** LLM-based life-model fact extraction (projects/deadlines/commitments from content),
planner (priority model, scheduling, decomposition), autonomy tiers, approval queue. Phase 3 is the "Think"
phase where Jarvis reasons over the data Phase 2 collects.

### Time-per-phase caveat
Estimates assume one focused engineer + Claude Code, and that external setup (OAuth screens, Tasker,
device perms) is done promptly when a phase STOPs for it. External setup is the usual schedule risk,
not the code.

---

## 5. What can be parallelized

Independent workstreams once Phase 1 is stable:

- **A — Integrations (read):** Gmail, Calendar, Todoist connectors are independent modules behind a
  common `Connector` protocol. Build in parallel; each is small and separately testable with
  recorded fixtures.
- **B — Native agents:** mac-agent, chrome-extension, android-tasker each POST to `/ingest` and share
  nothing but the payload contract. Fully parallel with A and with each other.
- **C — Dashboard:** consumes `/state/*` and `/approvals`; can be built against a stubbed API
  (fixtures) in parallel with the backend.
- **D — Planner:** priority model + scheduling logic is pure/unit-testable and can be developed
  against synthetic life-model data before real integrations land.

**Serial (do not parallelize):** the critical-path spine (§3), the autonomy `ActionGateway`
(single chokepoint — must land and be reviewed before *any* Phase-4 write connector is enabled),
and DB schema/migrations (one owner to avoid migration conflicts).

**Sequencing rule for parallel work:** parallel modules must each ship behind their interface with
tests and NOT be wired into a phase until that phase's gate. Don't let a half-done Todoist connector
block the Calendar path.

---

## 6. Risks & mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | **Local model too weak** for reliable intent/tool-calling/JSON | High | High | Provider abstraction lets us dial model size or fall back to a cloud provider per-task via `.env`; strict `structured()` validate-and-repair loop; choose a tool-use-capable model (Qwen2.5/Llama-3.x) sized to the Pro's RAM. Keep prompts small & explicit. |
| R2 | **Pro RAM/thermals** can't run a big model + Postgres + brain 24/7 | Med | High | Right-size the model to available unified memory (see MACHINE_SETUP); Ollama unloads idle models; monitor with a health job; Postgres is light. |
| R3 | **OAuth / Google verification** friction (unverified app, scopes, refresh tokens) | High | Med | Use "Testing" OAuth app with yourself as test user (no verification needed); request minimal scopes per phase; store + auto-refresh tokens; document exact clicks in EXTERNAL_ACTIONS. |
| R4 | **Autonomy leak** — a read path triggers an unintended write | Low | Critical | Single `ActionGateway` chokepoint; integrations' act-methods unreachable except via gateway; tests assert no executor is called outside a tier decision; default every new action to Tier 4. |
| R5 | **Secrets exposure** (tokens in DB/logs, committed .env) | Med | Critical | `.env` git-ignored; only `.env.example` committed; OAuth tokens encrypted at rest (Fernet); structlog scrubber redacts tokens; pre-commit secret scan. |
| R6 | **Tailscale connectivity** (Pro sleeps, ACLs, DNS) | Med | Med | Disable Pro sleep / `caffeinate`; verify with `/health` from phone in Phase 0; Tailscale ACLs documented; brain binds Tailscale interface only. |
| R7 | **Telegram inbound** requires a public webhook | Low | Med | Use **long-polling** (bot pulls from Telegram) — no inbound public port, honors "no public ports". Webhook is an optional later optimization. |
| R8 | **Android Tasker fragility** (OEM battery-killing, permission resets) | Med | Med | Document exact battery-optimization exemptions per OEM; keep Tasker profiles dumb (POST only); treat device signals as best-effort, never a hard dependency. |
| R9 | **Migration drift** between SQLite-early and Postgres-later | Med | Med | **Use Postgres from Phase 0** (we already run Docker) — skip SQLite entirely to avoid the migration tax. pgvector gives us memory embeddings without a second datastore. |
| R10 | **Native OS APIs change / permission prompts** on macOS | Low | Med | Keep mac-agent thin (osascript/NSWorkspace); all reasoning in brain; agent degrades gracefully if a permission is denied. |
| R11 | **Scope creep** — building §5–§13 before §0–§3 solid | High | Med | Phase gates + "one phase at a time" rule; MVP.md is the contract for what ships first. |

---

## 7. MVP definition (summary — full detail in MVP.md)

**"The Briefing Secretary."** The smallest thing usable every day within a few days:

- Text Jarvis on **Telegram**; it replies via the **local LLM**.
- **Capture:** any one-liner ("call the dentist", "essay due Friday") is filed to the DB and
  acknowledged.
- **Read-only life view:** connects to **Google Calendar** (events) and **Gmail** (unread /
  waiting-on signal), read scopes only.
- **Daily morning briefing** pushed to Telegram: today's events + captured tasks + a single
  suggested next action; plus on-demand "what's my day?" / "what am I waiting on?".
- **No writes, no native agents, no autonomy gate exercised** (all actions Tier 4 / disabled).

This is genuinely useful (it replaces the morning scramble) while touching only the low-risk read
surface. Everything else is deferred.

---

## 8. Long-term roadmap (beyond MVP)

1. **Acting, gated (Phase 4):** draft-first email, calendar block moves, task add/complete, SMS via
   Android agent — each behind its autonomy tier.
2. **Coordination (Phase 5):** waiting-on ledger, auto-nudges, people-memory-aware drafting.
3. **Prep & dispatch (Phase 5):** meeting briefings assembled from mail/docs; route "reorganize my
   files" → Claude Cowork, docs → Docs tool, etc.
4. **Learning (Phase 5):** capture corrections; turn recurring multi-step jobs into playbooks.
5. **Trust graduation (Phase 6):** actions earn autonomy as override-rate drops; off-limits zones.
6. **Voice (Phase 6):** speech front-end onto the same `/chat` brain.
7. **Later horizons:** multi-user hardening, richer dashboard analytics, more connectors (Slack,
   Notion), on-device model upgrades as hardware allows.

---

## 9. Deployment strategy

- **Topology:** dev on the **Air** (`docker compose up`), deploy to the **Pro** by `git pull` +
  dropping the Pro's `.env` + `docker compose up`. Identical images, different config. (CLAUDE.md
  Golden Rules #1/#2.)
- **LLM placement:** the model runs on the **Pro** via Ollama. Two supported topologies, both pure
  config:
  - *Pro production:* brain and Ollama both on the Pro; `LLM_BASE_URL=http://host.docker.internal:11434`
    (or the Pro's Tailscale IP).
  - *Air dev:* brain on the Air points `LLM_BASE_URL` at the **Pro's Tailscale IP:11434**, or runs a
    smaller local model on the Air.
- **Compose profiles:** `brain` + `db` always; an optional `ollama` compose profile for running the
  model in a container is provided but on Apple Silicon we recommend **native Ollama** (GPU/Metal
  access; containers can't use the Mac GPU). Documented in MACHINE_SETUP.
- **Networking:** Tailscale mesh, **no public ports**. Brain binds the Tailscale interface; every
  endpoint requires the shared auth token (Phase 0) → per-agent tokens (hardening). Telegram uses
  long-polling so no inbound port is exposed.
- **Data & migrations:** Postgres volume persists across deploys; schema changes via **Alembic**
  migrations run on startup (or an explicit `make migrate`). Never auto-drop.
- **Rollback:** each phase tags a git release (`phase-0`, `phase-1`, …). Rollback = `git checkout
  <prev tag>` + `docker compose up --build`; DB migrations are written with a `downgrade()` and a
  pre-deploy `pg_dump` snapshot. Rollback steps are listed at the end of each phase's docs.
- **Backups:** nightly `pg_dump` to a local path on the Pro (and optionally an encrypted off-box
  copy). OAuth tokens are in the DB, so DB backups are sensitive → keep them encrypted.

---

## 10. Testing strategy

Follows the ECC testing rules (80% coverage target; unit + integration + E2E). Pragmatically:

- **Unit (fast, most numerous):** planner priority math, decomposition, life-model updates,
  `structured()` validation/repair, autonomy tier decisions, config loading. Pure functions, no I/O.
- **Integration:** API routers via `httpx.AsyncClient` against a **test Postgres** (Docker or
  `testcontainers`); integrations tested against **recorded fixtures** (VCR-style cassettes) — never
  hit live Google/Telegram in CI.
- **LLM in tests:** a `FakeLLMProvider` implementing the `LLMProvider` interface returns canned
  completions/tool-calls. **No test calls a real model.** This is the payoff of the abstraction.
- **E2E / smoke (per phase gate):** scripted happy-path — e.g., Phase 1: send a Telegram message via
  the bot API in a test chat → assert a reply + a captured row; Phase 0: curl `/health` from the
  phone's Tailscale.
- **Autonomy safety tests (mandatory before Phase 4):** assert that no integration act-method is
  reachable without a passing tier decision, and that every action type defaults to Tier 4.
- **Dashboard:** component/unit for logic; Playwright smoke for the Today view (visual regression at
  key breakpoints per web testing rules).
- **CI:** GitHub Actions runs lint + type-check + unit + integration on every PR; the Pro deploy is
  manual/gated (not auto-deployed from CI).

---

## 11. Branching strategy

- **Trunk-based with short-lived branches.** `main` is always deployable (it's what the Pro pulls).
- **Branch per phase/feature:** `phase-1/telegram-chat`, `feat/calendar-read`, `fix/...`.
- **PR into `main`** with the ECC review checklist; squash-merge for a clean history.
- **Release tags per phase:** `phase-0`, `phase-1`, … used as rollback points.
- **`.env` never branches** — only `.env.example` is versioned; real env lives on each machine.
- **Deploy = `main` (or a phase tag) pulled on the Pro.** No long-running `develop` branch; YAGNI
  for a single-operator project.

---

## 12. Coding standards & conventions

Anchored to the user's ECC rules (`~/.claude/rules/ecc/*`). Highlights that bind this project:

**General (common/coding-style):**
- Immutability by default; return new objects, don't mutate. Pydantic models are frozen where
  practical.
- KISS / DRY / YAGNI. Many small files (200–400 lines typical, **800 hard max**). Organize by
  feature/domain, not by type.
- Explicit error handling at every boundary; never swallow errors. User-facing messages friendly;
  server logs detailed (structlog).
- Validate all input at system boundaries (Pydantic schemas on every `/ingest` and `/chat` payload).
- No hardcoded secrets/paths/hosts — everything via `config.py`/`.env` (portability rule).
- Early returns over deep nesting (>4 levels is a smell); functions <50 lines; named constants over
  magic numbers.

**Python-specific:**
- Python 3.12, full type hints, `ruff` (lint+format) + `mypy` (strict-ish). `uv` for deps.
- FastAPI `Depends()` for DI — no separate DI framework (YAGNI). Async throughout; no blocking I/O in
  the event loop (offload to threads/`run_in_executor` for sync SDKs).
- SQLAlchemy 2.0 typed models; Alembic for every schema change (no autogen-and-pray without review).

**Web/dashboard (web rules):**
- React + Vite + TS; TanStack Query for server state (don't duplicate server state into a client
  store); URL as state for tabs/filters. CSS custom-property design tokens; compositor-friendly
  animation only. Semantic HTML; accessibility + reduced-motion respected. Anti-template design bar.

**Commits (git-workflow):** `type: description` (feat/fix/refactor/docs/test/chore/perf/ci).
Attribution disabled globally. Meaningful commit boundaries (one logical change each).

**Reviews:** `code-reviewer` after writing code; `security-reviewer` before anything touching auth,
OAuth tokens, `/ingest`, or the autonomy gate (mandatory security trigger).

### Naming conventions
- Python: modules `snake_case`; classes/Pydantic models `PascalCase`; funcs/vars `snake_case`;
  constants `UPPER_SNAKE_CASE`; booleans `is_/has_/should_/can_`.
- Interfaces/Protocols: `PascalCase` ending in the role (`LLMProvider`, `TextChannel`, `Connector`).
- DB tables: `snake_case` plural (`captures`, `people`, `waiting_items`). Alembic revisions have
  descriptive slugs.
- React: components `PascalCase`; hooks `useX`; CSS classes kebab-case; design tokens `--kebab-case`.
- Env vars: `UPPER_SNAKE_CASE`, prefixed by domain (`LLM_`, `GOOGLE_`, `TELEGRAM_`, `DB_`, `AUTH_`).
- Autonomy tiers referenced by name enum (`SILENT`, `ACT_THEN_NOTIFY`, `PROPOSE_AND_WAIT`,
  `NEVER_WITHOUT_ME`), never bare ints in code.

---

## 13. Technology & package choices (summary — full rationale in TECH_STACK.md)

| Concern | Choice | One-line why (rejected alt) |
|---|---|---|
| Backend | **Python 3.12 + FastAPI** | Async, Pydantic-native, best LLM ecosystem (rej: Node — weaker local-LLM tooling). |
| Deps/build | **uv** | 10–100× faster, lockfile, reproducible (rej: Poetry — slower; pip — no lock). |
| Database | **Postgres 16 + pgvector** | Relational + vector memory in one store; production-grade (rej: SQLite — migration tax + no server; separate vector DB — extra moving part). |
| ORM / migrations | **SQLAlchemy 2.0 + Alembic** | Typed, mature, explicit migrations (rej: raw SQL — no safety; Tortoise — smaller ecosystem). |
| Validation/config | **Pydantic v2 + pydantic-settings** | One model layer for API, config, structured LLM output. |
| LLM transport | **LiteLLM behind our `LLMProvider`** | One dep normalizes Ollama/LM Studio/OpenAI-compat/OpenAI/Anthropic; wrapped so it's swappable (rej: vendor SDKs everywhere — vendor lock; raw httpx — reinvent retries). |
| Local model host | **Ollama (native on Pro)** | Simplest Apple-Silicon local serving, Metal GPU, OpenAI-compat API (rej: containerized LLM — no Mac GPU; LM Studio — GUI-centric for a server). |
| Embeddings | **Local embed model via Ollama** (e.g. `nomic-embed-text`) → pgvector | Keeps memory search local & free. |
| Scheduler | **APScheduler** | In-process cron for daily/weekly/monitor jobs; no broker needed (rej: Celery beat — heavy). |
| Task queue | **None for MVP; ARQ later** | FastAPI background tasks suffice early; ARQ (async, Redis) when real queuing is needed (rej: Celery — sync-first, heavier). |
| Chat channel | **python-telegram-bot v21 (long-polling)** | Mature async lib; polling = no public port (rej: webhook — needs inbound port). |
| Logging | **structlog** | Structured JSON, request IDs, easy redaction. |
| Testing | **pytest + pytest-asyncio + httpx + VCR + testcontainers** | Async-friendly; fixtures over live calls. |
| DI | **FastAPI `Depends`** | Built-in, enough (rej: dependency-injector — overkill). |
| Frontend | **React + Vite + TypeScript + TanStack Query + Tailwind** | Fast SPA, strong typing, per web rules (rej: Next.js — SSR unneeded for a Tailscale-internal dashboard). |
| Reverse proxy | **None for MVP** (Tailscale handles reachability/TLS) | Add Caddy only if external TLS/host routing is ever needed. |
| Native mac agent | **Python + osascript/NSWorkspace + launchd** | Thin, no heavy deps. |
| Chrome ext | **Manifest V3, vanilla JS** | Minimal surface. |
| Android | **Tasker + Tailscale** | Per spec; dumb POSTers. |
| Secrets at rest | **Fernet-encrypted OAuth tokens in Postgres** | No plaintext tokens; key in `.env`. |

---

## 14. Things in CLAUDE.md to redesign before implementation (be opinionated)

1. **LLM vendor assumption → provider abstraction (mandated).** CLAUDE.md §3/§4 assume the
   Anthropic API. Replace with the `LLMProvider` interface (§1.3). *Application code never names a
   vendor.* **Adopt.**
2. **SQLite "acceptable for early phases" → go Postgres from Phase 0.** Since we already run Docker,
   there is no reason to pay a later SQLite→Postgres migration and lose pgvector. **Redesign:** start
   on Postgres+pgvector. (Risk R9.)
3. **Shared single auth token → per-agent tokens + Tailscale ACLs (phased).** Ship the shared token
   for Phase 0 (simple), but treat it as a stopgap. Design the auth dependency so multiple named
   tokens/scopes drop in without refactor. Encrypt OAuth tokens at rest. **Redesign the auth model's
   shape now, upgrade the implementation during hardening.**
4. **`comms/text-channel/` as a separate top-level service → fold into `brain/app/comms` behind
   `TextChannel` for MVP.** Keeps one deployable; the interface preserves the spec's intent to swap
   SMS/web later. **Redesign folder placement; keep the abstraction.**
5. **Telegram transport: prefer long-polling over webhooks.** The spec says "no public ports";
   webhooks contradict that. Long-polling satisfies both. **Decide now: polling.**
6. **Ingest should be an append-only event log, then derive the life model.** Rather than agents
   mutating life-model tables directly, `/ingest` writes immutable events; a consolidation job
   derives/updates the life model. Cheaper auditability, safe re-derivation, matches the immutability
   rule. **Add an `events` table as the ingest sink.**
7. **Autonomy gate must be a hard architectural chokepoint, not a convention.** Make integrations'
   act-methods physically reachable only through `ActionGateway` (e.g., they require a signed
   `ActionGrant` object the gateway alone issues). **Design this before any write connector.**
8. **Structured-output reliability is a first-class concern with local models.** CLAUDE.md is silent
   on it; frontier-API assumptions don't hold locally. **Add the `structured()` validate-and-repair
   contract to `llm/` from day one.**
9. **Model runs only on the Pro — make the Air-dev story explicit.** "Runs unchanged on either Mac"
   is true for the *brain*, but the *model* is Pro-hosted. Document the config-only Air→Pro LLM
   pointing (§1.3, §9) so no one hardcodes a localhost model URL. **Documentation/config redesign.**

None of these change the product; they harden the architecture and remove foreseeable debt.

---

## 15. Definition of done (this planning phase)

The five documents exist, are internally consistent, and give a single operator an unambiguous
path: what to build, in what order, what to set up by hand, on which machine, and what the first
usable slice is. Application code begins only after Phase 0's external setup (Docker, Git, Tailscale)
is confirmed by the operator.
