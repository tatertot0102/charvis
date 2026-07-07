# TECH_STACK.md — Jarvis Technology Choices

> Every choice below is opinionated and justified, with the rejected alternative named. Governing
> constraints: **portable brain (config-driven), local-only LLM behind an abstraction, one
> `docker compose up`, no public ports, minimal debt.** When in doubt we chose the simpler thing
> that doesn't paint us into a corner.

---

## Decision summary table

| Layer | Choice | Rejected | Reason in one line |
|---|---|---|---|
| Language/runtime | Python 3.12 | Node/TS, Go | Best local-LLM + data ecosystem; Pydantic; async mature |
| Web framework | FastAPI | Flask, Django, Litestar | Async-first, Pydantic-native, auto OpenAPI, small |
| Dep/build | uv | Poetry, pip-tools, pipenv | Fastest, lockfile, reproducible, single tool |
| Database | PostgreSQL 16 + pgvector | SQLite, MySQL, Mongo, separate vector DB | Relational + vector memory in one durable store |
| ORM | SQLAlchemy 2.0 (typed) | Tortoise, SQLModel, raw SQL | Mature, typed, explicit, huge ecosystem |
| Migrations | Alembic | Autogenerate-only, hand SQL | Reviewed, reversible schema changes |
| Validation/config | Pydantic v2 + pydantic-settings | dataclasses, dynaconf | One model layer: API + config + LLM output |
| LLM abstraction | Own `LLMProvider` + LiteLLM transport | Vendor SDKs directly, LangChain | Vendor-agnostic; one dep normalizes all providers |
| Local model host | Ollama (native on Pro) | LM Studio, llama.cpp raw, vLLM | Simplest Apple-Silicon serving, Metal, OpenAI-compat |
| Embeddings | Ollama embed model → pgvector | OpenAI embeddings, sentence-transformers in-proc | Local, free, no extra service |
| Scheduler | APScheduler | Celery beat, cron, Temporal | In-process cron, no broker |
| Task queue | None (MVP) → ARQ later | Celery, RQ, Dramatiq | Background tasks suffice; ARQ is async-native later |
| Chat channel | python-telegram-bot v21 (polling) | aiogram, raw Bot API, Twilio SMS | Mature async; polling = no public port |
| Auth | Shared token → per-agent tokens; Fernet for secrets | OAuth2 server, JWT sessions | Tailscale-internal; keep it proportionate |
| Logging | structlog | stdlib logging, loguru | Structured JSON, request IDs, redaction |
| Testing | pytest + asyncio + httpx + VCR + testcontainers | unittest, live-call tests | Async, fixture-based, deterministic |
| DI | FastAPI Depends | dependency-injector, wired | Built in, sufficient |
| Frontend | React + Vite + TS + TanStack Query + Tailwind | Next.js, Vue, SvelteKit, plain | Fast internal SPA, typed, per web rules |
| Reverse proxy | None (MVP) → Caddy if needed | nginx, Traefik | Tailscale handles reachability/TLS |
| Container | Docker + Compose | Podman, k8s, bare metal | Spec mandates compose; k8s is overkill |
| Native mac agent | Python + osascript/NSWorkspace + launchd | Swift app, Hammerspoon | Thin, no build toolchain, shares Python |
| Chrome extension | Manifest V3 vanilla JS | React ext, WXT framework | Tiny surface, no bundler needed |
| Android | Tasker + Tailscale | Native app, Termux | Per spec; fastest to working signals |

---

## Backend — Python 3.12 + FastAPI

**Why Python:** the entire local-LLM tooling surface (Ollama clients, LiteLLM, embeddings,
Google/Todoist SDKs) is first-class in Python. Async support is mature. Pydantic gives one typed
model layer across HTTP, config, DB DTOs, and **LLM structured output** — which matters because
validating shaky local-model JSON is core to reliability.

**Why FastAPI:** async-first, Pydantic-native request/response validation (satisfies "validate at
every boundary"), automatic OpenAPI (free contract for the dashboard + agents), dependency
injection via `Depends` (no extra DI framework), small and unopinionated about the rest.

- **Rejected — Node/TypeScript:** great for the dashboard, but the local-LLM/embeddings/Google
  ecosystem is weaker and we'd fight sync/async SDK gaps. We keep TS where it shines: the frontend.
- **Rejected — Django:** batteries we don't want (admin, templating, sync ORM core); heavier for an
  API-only async brain. We take Django's good idea (migrations) via Alembic.
- **Rejected — Litestar/Flask:** Litestar is fine but smaller community; Flask is sync-first and
  we'd bolt on async. FastAPI is the safe, well-trodden async choice.

---

## Dependency & build — uv

**Why:** 10–100× faster installs than pip/Poetry, a real lockfile (`uv.lock`) for reproducible
Air→Pro deploys, manages the Python version too, single static binary. Reproducibility directly
serves the portability rule.

- **Rejected — Poetry:** slower, historically flaky resolver, heavier.
- **Rejected — pip + requirements.txt:** no lockfile/resolution guarantees → deploy drift.

---

## Database — PostgreSQL 16 + pgvector

**Why Postgres from day one:** we already run Docker, so there's no setup savings from SQLite — only
a future migration tax and the loss of concurrency and server-grade durability for an always-on
system. **pgvector** lets us store the life-model working-memory embeddings *in the same database*
as the relational data, so memory search is a SQL query, not a second service.

**What it stores:** captures, events (append-only ingest log), projects, priorities, people,
waiting-items, calendar/email cache, autonomy actions + approval queue, corrections/playbooks, and
`vector` columns for memory recall.

- **Rejected — SQLite:** single-writer, weak concurrency for a 24/7 service, and the CLAUDE.md
  "acceptable early" path leads to a painful migration + no pgvector. Skip it.
- **Rejected — separate vector DB (Chroma/Qdrant/Pinecone):** an extra service to run, deploy, and
  back up for a single-user memory store that pgvector handles comfortably at this scale. Add one
  only if recall volume ever outgrows Postgres (it won't for one person).
- **Rejected — MySQL/Mongo:** Mongo loses relational integrity we want for people/waiting-on; MySQL
  lacks Postgres's extension ecosystem (pgvector, JSONB richness).

---

## ORM & migrations — SQLAlchemy 2.0 + Alembic

**Why:** SQLAlchemy 2.0's typed, modern API pairs with mypy; it's the most battle-tested Python ORM
and works cleanly with async (`asyncpg`). **Alembic** gives reviewed, reversible migrations with a
`downgrade()` — essential for the per-phase rollback strategy.

- **Rejected — SQLModel:** convenient (Pydantic+SQLAlchemy) but thinner and leakier at the edges;
  we prefer explicit SQLAlchemy models + separate Pydantic schemas for clear boundaries.
- **Rejected — Tortoise/Peewee:** smaller ecosystems, weaker async/migration story.
- **Rejected — raw SQL only:** no type safety, hand-rolled migrations, more foot-guns.

---

## LLM abstraction — own `LLMProvider` interface, LiteLLM as transport

This is the project's defining decision (per the amendment). **Application code depends only on our
`LLMProvider` protocol** (`complete(messages, tools)`, `embed(texts)`, `structured(schema, ...)`).
The rest of the system never knows which model is running.

**Why LiteLLM under the hood:** one dependency already speaks Ollama, LM Studio, any
OpenAI-compatible server, OpenAI, and Anthropic, and normalizes tool-calling and errors across them.
We wrap it so *LiteLLM itself is swappable* — if it ever disappoints, we replace the adapter, not the
app. Provider selection is `.env` (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `LLM_EMBED_MODEL`).

**Structured output contract:** `structured()` requests JSON/tool schema, validates with Pydantic,
does **one** bounded repair retry on failure, then raises. Local models need this guardrail; we never
let malformed output silently reach the life model.

- **Rejected — vendor SDKs sprinkled through the code:** vendor lock, exactly what the amendment
  forbids.
- **Rejected — LangChain/LlamaIndex as the core framework:** heavy abstractions, churn, and they'd
  become the thing everything depends on. We want a 30-line interface we control. (We may borrow a
  small utility, but not the framework.)
- **Rejected — hand-rolled httpx per provider:** we'd reinvent retries, streaming, tool-call
  normalization. LiteLLM does it; we keep the seam thin.

---

## Local model host — Ollama, native on the Pro

**Why:** easiest first-class local serving on Apple Silicon, uses the Metal GPU, exposes an
**OpenAI-compatible** API (so it slots straight into the adapter), trivial model management
(`ollama pull`), and unloads idle models to save RAM. Runs as a native macOS service (not in the
container) because **Docker on macOS cannot access the Mac GPU** — a containerized model would be
CPU-only and slow.

**Model selection guidance (set in MACHINE_SETUP per the Pro's RAM):** a **tool-use-capable**
instruct model — e.g. Qwen2.5 (7B/14B) or Llama 3.x — sized so the model + Postgres + brain live
comfortably in unified memory. Embeddings via a small local model (e.g. `nomic-embed-text`).

- **Rejected — containerized LLM (Compose `ollama` profile):** no Mac GPU access → too slow for
  interactive chat. We keep the profile as an escape hatch (e.g., Linux host later) but default to
  native.
- **Rejected — LM Studio as the server:** GUI-centric; fine for experimentation, less ideal as a
  headless always-on service. It remains supported via the OpenAI-compat adapter if preferred.
- **Rejected — raw llama.cpp / MLX by hand:** more plumbing (model conversion, server flags) for no
  gain over Ollama at this stage.

---

## Scheduler — APScheduler (task queue deferred)

**Why:** the brain needs cron-like jobs (daily rundown, weekly review, monitor loops, nightly
life-model consolidation, token refresh). APScheduler runs these **in-process** with no broker —
right-sized for a single always-on service.

**Task queue — none for MVP, ARQ later.** FastAPI background tasks handle "do this after responding"
(e.g., send a Telegram ack, kick a fetch). When we genuinely need durable, retried, out-of-request
work (Phase 4+ sends, large syncs), add **ARQ** (async-native, Redis-backed, tiny).

- **Rejected — Celery:** sync-first, heavy config, a broker + workers to operate; overkill now and
  awkward with async. ARQ is the async-era replacement when the need is real.
- **Rejected — Temporal/cron:** Temporal is enterprise-scale overkill; system cron can't see app
  state and breaks portability.

---

## Chat channel — python-telegram-bot v21, long-polling

**Why Telegram (per spec):** instant reliable two-way text over data, no carrier/SMS friction.
**Why python-telegram-bot v21:** the most mature async Telegram lib. **Why long-polling:** the bot
*pulls* updates from Telegram, so **no inbound public port** is needed — this is what makes "no
public ports" actually hold. All of it sits behind our `TextChannel` interface so SMS-via-Android or
a web chat can replace it later without touching the conversation layer.

- **Rejected — webhooks:** require a public HTTPS endpoint → violates the no-public-ports rule.
- **Rejected — aiogram:** good, but PTB has broader docs/stability; either would work behind the
  interface.
- **Rejected — Twilio SMS as the first channel:** cost, carrier friction, and setup weight vs. a free
  Telegram bot.

---

## Auth & secrets

**MVP:** a single shared bearer token in `.env`, required on every endpoint even over Tailscale
(defense in depth). **Hardening:** the auth dependency is designed to accept **multiple named
per-agent tokens** so mac-agent, chrome-ext, and Android get distinct credentials without a refactor;
combine with Tailscale ACLs.

**OAuth tokens** (Google, etc.) are stored **Fernet-encrypted at rest** in Postgres — never
plaintext, never in code, never logged (structlog redaction). Key lives in `.env`.

- **Rejected — full OAuth2/JWT session server:** disproportionate for a single-operator,
  Tailscale-internal system. We keep auth simple but not naive.

---

## Logging — structlog

**Why:** structured JSON logs with request IDs and easy field redaction (critical so tokens/PII never
leak into logs). Plays well with async and future log shipping.

- **Rejected — stdlib logging alone:** unstructured, painful redaction. **loguru:** nice but less
  standard for structured pipelines.

---

## Testing — pytest + pytest-asyncio + httpx + VCR + testcontainers

**Why:** async-native; `httpx.AsyncClient` drives FastAPI in-process; **VCR cassettes** record
Google/Telegram responses so CI is deterministic and offline; **testcontainers** (or a Compose test
DB) gives a real Postgres for integration tests. A **`FakeLLMProvider`** implements our interface so
**no test hits a real model** — the direct payoff of the abstraction. Coverage via pytest-cov toward
the 80% target.

- **Rejected — hitting live APIs in tests:** flaky, slow, rate-limited, non-deterministic.

---

## Dependency injection — FastAPI `Depends`

**Why:** FastAPI's `Depends` already gives per-request DB sessions, auth, and service wiring with
typing. Adding a DI container would be ceremony for no benefit.

- **Rejected — dependency-injector / wired:** overkill; more abstraction than a single service needs.

---

## Frontend — React + Vite + TypeScript + TanStack Query + Tailwind

**Why:** the dashboard is an internal SPA served over Tailscale that only calls the brain API — no
SSR/SEO needs. **Vite** = fast dev/build; **TypeScript** = typed contract against the OpenAPI;
**TanStack Query** = server-state caching / stale-while-revalidate without duplicating server state
into a client store (per web patterns); **Tailwind + CSS custom-property tokens** = fast, consistent,
and compatible with the anti-template design bar and compositor-friendly animation rules.

- **Rejected — Next.js:** SSR/routing/server-components we don't need for a LAN dashboard; more to
  operate. **Vue/Svelte:** fine, but React best matches the user's web ruleset and component
  patterns. **Plain JS:** loses typing against the API.

---

## Reverse proxy — none for MVP

**Why:** Tailscale provides secure reachability (and TLS via MagicDNS/HTTPS if wanted). The brain
binds the Tailscale interface directly. Introduce **Caddy** only if we later need external TLS
termination or host-based routing.

- **Rejected — nginx/Traefik now:** another service for zero current benefit.

---

## Container strategy — Docker + Compose

**Why (per spec):** `docker compose up` brings up `brain` + `db`. Images are identical Air→Pro; only
`.env` differs. The **LLM (Ollama) runs natively on the Pro**, not in Compose, for GPU access; the
brain reaches it via `LLM_BASE_URL` (host or Tailscale IP). An optional `ollama` Compose profile
exists for non-Mac hosts.

- **Rejected — Kubernetes:** absurd overkill for two Macs and a phone. **Bare metal (no container):**
  loses the portability/one-command promise.

---

## Native agents

- **mac-agent — Python + osascript/NSWorkspace, kept alive by launchd.** Thin: reports running apps
  and executes open-app/open-URL/close-tab actions; all reasoning stays in the brain. Python so it
  shares the repo's language and has no separate build step. *Rejected — a Swift app:* build/signing
  overhead for a dumb reporter.
- **chrome-extension — Manifest V3, vanilla JS.** Pushes active tabs + history to `/ingest`. No
  bundler for such a small surface. *Rejected — React/WXT:* unnecessary tooling.
- **android — Tasker + Tailscale (per spec).** Profiles for location, battery, SMS read/send,
  notification forwarding, each POSTing to the brain's Tailscale address. Dumb POSTers; brain does
  the thinking. *Rejected — a native Android app:* far more work for the same signals.

---

## Memory system (how "it knows me" is stored)

- **Structured memory** in Postgres tables: `projects`, `priorities`, `people`, `patterns`,
  `waiting_items`, `corrections`. Source of truth for planner/conversation.
- **Working memory** = a periodically-regenerated compact summary (text) the LLM reads each turn, so
  we don't blow the context window with raw rows.
- **Semantic recall** = embeddings (local embed model) in **pgvector** columns for "find relevant
  past context." One store, no extra service.
- **Ingest = append-only `events` log** → a nightly consolidation job derives/updates structured
  memory. Immutable intake, auditable, safely re-derivable (matches the immutability rule).

- **Rejected — a dedicated agent-memory framework (e.g., mem0/LangMem):** more dependency and
  opacity than a single-user store needs; our tables + pgvector are transparent and sufficient.

---

## LLM framework — deliberately none

We use **no orchestration framework** (LangChain/LlamaIndex/CrewAI) as a core dependency. The
"agent" logic (intent → plan → gated action) is explicit application code we can read, test, and
debug, sitting on the thin `LLMProvider` seam. This avoids framework churn and hidden control flow.

- **Rejected — LangChain et al.:** heavy, fast-moving, and they'd become the layer everything depends
  on — the opposite of the clean abstraction we're mandated to keep.

---

## Cross-cutting: why these choices serve the mandate

- **Portability:** every environment difference (LLM provider/URL/model, DB DSN, tokens, hosts) is in
  `.env`; images are identical Air→Pro.
- **Local-only AI:** Ollama on the Pro + our provider seam; cloud providers are opt-in config, never
  assumed.
- **Minimal debt:** Postgres-from-day-one, uv lockfiles, Alembic reversibility, one deployable, no
  premature queue/proxy/framework.
- **Safety:** structured-output validation, Fernet-encrypted tokens, structlog redaction, and the
  single autonomy chokepoint (see EXECUTION_PLAN §14.7).
