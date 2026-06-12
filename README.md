# Rule Intelligence — Customer Data Quality Agent

A full-stack AI assistant that reads 228 active Customer data quality rules from Excel and YAML sources, maps SAP field references to business terminology, and answers natural-language questions through a streaming chat interface. Includes specialist **Data Engineer** and **Project Manager** modes that analyse user stories against the real pipeline codebase.

---

## Table of Contents

1. [Features](#features)
2. [Architecture](#architecture)
3. [Full Data Workflow](#full-data-workflow)
4. [REST API Reference](#rest-api-reference)
5. [Project Structure](#project-structure)
6. [Environment Variables](#environment-variables)
7. [Setup — Local Development](#setup--local-development)
8. [Docker Deployment](#docker-deployment)
9. [Authentication & Security](#authentication--security)
10. [Chat Modes](#chat-modes)
11. [Admin Dashboard](#admin-dashboard)
12. [Analytics](#analytics)
13. [Rate Limiting](#rate-limiting)
14. [Frontend Components](#frontend-components)
15. [Sample Chat Queries](#sample-chat-queries)
16. [Adding New YAML Pipelines](#adding-new-yaml-pipelines)
17. [Schema Discovery](#schema-discovery)
18. [Troubleshooting](#troubleshooting)

---

## Features

- **Natural-language chat** — ask questions about any rule by ID or description; streaming SSE and standard JSON responses both supported
- **228 active Customer rules** — loaded at startup from Excel inventory, filtered to `domain=Customer` and `is_active=1`
- **SAP field mapping** — `TABLE-FIELD` references resolved to human-readable business labels via the Z11 map
- **YAML pipeline lineage** — per-rule workflow steps, upstream data sources, and custom operations surfaced automatically
- **Cross-rule dependency graph** — `dependent_on` column and logic-text references resolved to clickable rule cards
- **AI explanations** — OpenAI GPT-4o generates plain-English business explanations; results are session-cached
- **Follow-up Q&A** — multi-turn dialogue with up to 20 history turns; LLM classifies FOLLOWUP vs. SEARCH
- **Suggested follow-ups** — 2–3 contextual follow-up questions generated after each AI response
- **Data Engineer mode** — paste a user story and get concrete file-change instructions with before/after YAML/Python snippets and Databricks validation queries
- **Project Manager mode** — paste an issue description and get a fully structured agile story (title, acceptance criteria, technical notes, testing notes)
- **Rule browser & tree view** — slide-in panel with live search, category filter chips, and a hierarchical D3 tree/graph view
- **Pinned + recent rule tabs** — unlimited pinned rules, up to 20 recent, both persisted in `localStorage`
- **Admin dashboard** — usage analytics: top rules, daily activity, intent distribution, trending rules, and token usage
- **Bearer token auth** — required in staging/production; skipped only in explicit dev mode
- **Rate limiting** — configurable per-IP chat rate limit via `slowapi`
- **Docker-ready** — single-file `Dockerfile` with non-root user, pinned base image, and volume mount for data

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                            React Frontend                                 │
│  ┌──────────┐  ┌─────────────┐  ┌───────────┐  ┌──────────┐  ┌───────┐  │
│  │ ChatBox  │  │ RuleBrowser │  │ RuleCard  │  │ TreeView │  │ Admin │  │
│  │ (analyst │  │ (slide-in   │  │ (sidebar  │  │ GraphView│  │ Page  │  │
│  │ engineer │  │  + search)  │  │  detail)  │  │          │  │       │  │
│  │    pm)   │  └──────┬──────┘  └─────┬─────┘  └────┬─────┘  └───┬───┘  │
│  └────┬─────┘         │               │              │            │      │
└───────┼───────────────┼───────────────┼──────────────┼────────────┼──────┘
        │               │               │              │            │
   POST /api/chat  GET /api/rules  GET /api/rule/{id} GET /api/tree POST /admin/login
   POST /api/chat/stream  GET /api/rules/related/{id}             GET /admin/dashboard
        │               │               │              │            │
┌───────▼───────────────▼───────────────▼──────────────▼────────────▼──────┐
│                          FastAPI Backend                                   │
│                                                                            │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │  ChatAgent (analyst)          PersonaAgent (engineer / pm)          │   │
│  │  intent routing + streaming   3-stage: target selection →           │   │
│  │  follow-up Q&A                context assembly → streaming          │   │
│  └──────────┬───────────────────────────────┬──────────────────────── ┘   │
│             │                               │                              │
│  ┌──────────▼───────────────────────────────▼──────────────────────────┐  │
│  │  ExplanationEngine (OpenAI GPT-4o — explain + stream)                │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                          DataLoader                                   │  │
│  │  dim_rules_inventory.xlsx │ MDG Official Z11.xlsx │ *.yaml            │  │
│  │  custom_operations/**/*.py (indexed for context)                      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌────────────────┐  ┌─────────────────┐  ┌──────────────────────────┐   │
│  │  RuleParser    │  │   SapMapper     │  │     Analytics (SQLite)   │   │
│  │  (TABLE-FIELD  │  │  (Z11 field     │  │  rule views + chat events │   │
│  │   regex)       │  │   label lookup) │  │  + token usage tracking   │   │
│  └────────────────┘  └─────────────────┘  └──────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Full Data Workflow

### 1 — Startup: Data Loading (`data_loader.py`)

When the FastAPI server starts, four data sources are loaded and cached in memory:

| Source | File | Content |
|--------|------|---------|
| Rules inventory | `dim_rules_inventory.xlsx` → sheet `dim_rules_inventory` | All data quality rules |
| SAP field map | `MDG Official Z11.xlsx` → sheet `Sheet1` | TABLE-FIELD → business label |
| YAML pipelines | `golden/**/*.yaml` | Per-rule transform pipelines |
| Custom operations | `custom_operations/**/*.py` | Python operation classes with docstrings |

**Filtering at load time:** only rows where `domain = Customer` and `is_active = 1` are kept — yielding the 228 active rules shown in the UI.

Column names are normalised to `snake_case` automatically. Flexible candidate-column detection ensures the loader is resilient to minor Excel header changes.

### 2 — Schema Validation (`schema_validator.py`)

On startup, required columns are verified before the server accepts requests:

| DataFrame | Required columns |
|-----------|-----------------|
| Rules | `rule_id`, `domain`, `is_active`, `rule_logic` |
| SAP map | `sap_table`, `sap_field`, `field_label` |

If any required column is missing the server logs `[ERROR]` and raises `ValueError`, preventing a silent half-initialised state.

### 3 — Rule Parsing (`rule_parser.py`)

A regex extracts all SAP field references from a rule's `rule_logic` text:

```
rule_logic text  →  regex  →  ["KNA1-KUNNR", "VBAK-VBELN", ...]
```

### 4 — SAP Field Mapping (`sap_mapper.py`)

Each extracted `TABLE-FIELD` string is looked up in the Z11 sheet to retrieve:
- `business_name` — the human-readable field label
- `description` — usage notes from the CCHBC comments column
- `table` — the SAP table name

A field-only fallback is used when a full `TABLE-FIELD` key is not found.

### 5 — YAML Lineage Enrichment (`lineage_service.py`)

For each rule, the system attempts to match a YAML pipeline in `golden/` using a two-stage lookup:

1. **Content match** (preferred) — the YAML explicitly evaluates the rule ID as an expression literal (`expression: 'RCCOMP_103.1'`).
2. **Name heuristic fallback** — the transform `name` contains fragments of the rule ID.

When a match is found, the following are extracted:
- **`workflow_steps`** — `name` or `kind` of each pipeline operation
- **`pipeline_sources`** — `object_name` values from `read_dataio` operations
- **`yaml_reference`** — the matched filename
- **`sibling_rules`** — other rule IDs evaluated in the same pipeline
- **`custom_operations`** — Python operation classes used, with their docstrings

`extract_rule_section_from_yaml()` further isolates the portion of a YAML file that applies to a specific rule using comment anchors and line windows.

### 6 — Custom Operations Indexing (`data_loader.py`)

All Python files in `custom_operations/` are scanned at startup. For each file, the first `*Operation` class and its docstring are extracted via regex and keyed by dotted module path (e.g. `city_standarization.geocoords_address_conformity`). This index is injected into AI context when answering follow-up questions.

### 7 — Cross-Rule Reference Resolution (`data_loader.py`)

`get_referenced_rules(rule_id)` walks both the `dependent_on` column and `rule_logic` text to find all rule IDs that the given rule depends on or references. Each entry includes rule ID, description, logic, table, quality category, severity, source (`dependent_on` or `logic`), and active flag.

### 8 — AI Explanation (`explanation_engine.py`)

Rule logic and sanitised SAP field context are sent to **OpenAI GPT-4o** with a system prompt producing a plain-English business explanation scaled to complexity. Results are `lru_cache`d so the same logic string is never sent twice in a session.

`call_openai_async()` is a non-cached async variant used for intent classification, target selection (persona modes), and follow-up Q&A.

`call_openai_stream()` is an async streaming variant used by the `/chat/stream` endpoint — it yields delta chunks as they arrive from the API. Both sync and async token usage is logged to the `token_events` analytics table.

### 9 — Chat Intent Routing (`chat_agent.py`)

The `/chat` and `/chat/stream` endpoints receive a free-text message. The agent:

1. Tries to extract an explicit rule ID (regex: `[A-Z]{2,8}_\d+(\.\d+)?`).
2. If a rule ID is found, classifies intent via LLM with keyword fallback:

| Intent | Triggers | Response |
|--------|----------|---------|
| `sap_table` | "which table", "what table", "table checked" | SAP table the rule checks |
| `sap_column` | "which column", "column name", "column for" | SAP column the rule checks |
| `severity` | "severity", "how severe", "criticality" | Severity label (Critical/High/Medium/Low) |
| `description` | "description", "what's the description" | Rule's free-text description |
| `explain` | "explain", "what does", "what is", "describe" | AI plain-English explanation |
| `lineage` | "where does", "come from", "source", "lineage" | Module, group, data sources, pipeline steps |
| `workflow` | "workflow", "steps", "pipeline", "process" | Full lineage including YAML steps and custom ops |
| `fields` | "sap field", "fields used", "which field" | List of `TABLE-FIELD (Business Name)` pairs |
| `show` | "show", "get", "display", "full rule" | Full explanation (same as explain) |

3. If **no rule ID** is found, the agent tries resolution strategies in order:

| Condition | Strategy |
|-----------|----------|
| "how many" + category keyword | Count active rules in that category |
| "list" / "show all" + category keyword | List up to 10 rules in that category |
| "which rules" + ALL_CAPS word | Filter rules by SAP table or column name |
| Active rule in panel → AI classifies SEARCH vs FOLLOWUP | **FOLLOWUP**: answer using full rule context; **SEARCH**: AI catalog search |
| No active rule | AI catalog search by description |

4. **Follow-up Q&A** (`_answer_with_context`) uses full context: Excel row fields, YAML pipeline section, sibling rule IDs, custom operation docstrings, and cross-rule dependencies. Up to 20 prior conversation turns are included.

5. **Second retrieval hop** — for explain/show intents, sibling and dependency rule metadata is expanded so the LLM has rich context for co-evaluated rules.

6. **Conversational messages** (thanks, ok, bye, etc.) receive a short acknowledgement without calling the LLM.

### 10 — Persona Agent (`persona_agent.py`)

When `mode` is `"engineer"` or `"pm"`, the request is handed to the persona agent instead of `chat_agent`. It runs a three-stage pipeline:

**Stage 1 — Target selection (1 LLM call):** A compact one-line catalog of all 228 rules and all YAML pipelines is sent to the LLM. It returns a JSON object nominating up to 5 rule IDs, 3 pipeline names, and 4 custom op module keys relevant to the user's text. Any rule IDs explicitly mentioned by regex are pre-seeded and always included. All selections are post-validated against the real in-memory indexes (hallucinated names are dropped).

**Stage 2 — Context assembly (no LLM):** The nominated items are loaded from disk/cache within a 28 000-character budget. For each rule: the full inventory Excel row plus the YAML section for that rule. For each pipeline: raw YAML content. For each custom op: docstring and source code. Databricks source table names are surfaced for validation queries.

**Stage 3 — Streaming response (1 LLM call):** The assembled context is sent to a mode-specific system prompt. The engineer prompt produces a structured `## Summary / ## Files to change / ### <file> / ## Databricks validation` answer. The PM prompt produces `## Title / As a… / ## Description / ## Acceptance Criteria / ## Technical Notes / ## Testing Notes`.

`status` SSE events (`{"type":"status","text":"..."}`) are emitted while stages 1 and 2 run so the frontend can show progress.

### 11 — Analytics (`analytics.py`)

Every rule view, chat event, and LLM token usage is persisted asynchronously to a local **SQLite** database (`data/analytics.db`). Writes are fire-and-forget — failures are silently absorbed so analytics never disrupts the main request path.

The `/admin/dashboard` endpoint aggregates:
- Total and unique rule views, views today, views this week
- Top 15 most-viewed rules
- Daily activity chart (last 30 days)
- Intent distribution from chat events
- Trending rules (most active days in last 30 days)
- Cumulative token usage (prompt, completion, total)

---

## REST API Reference

### Public endpoints (no auth required)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness probe. Returns `{"status":"ok","rules_loaded":<N>}`. Never calls OpenAI. |
| `GET` | `/ready` | Readiness probe. Checks required env vars and that rules are loaded. Returns `503` if not ready. |
| `POST` | `/admin/login` | Exchange username/password for a session token. See [Admin Dashboard](#admin-dashboard). |

### Protected endpoints (Bearer token required in non-dev mode)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/rules` | Lightweight list of all 228 rules (id, category, table, description, severity) |
| `GET` | `/rules/related/{rule_id}` | Up to 4 rules sharing the same category or SAP table |
| `GET` | `/rules/impact/{rule_id}` | Deterministic impact graph: dependent rules, pipelines (and their co-located rules), custom operations (and which other pipelines share them), same-table/column rules, and the exact file paths a change would touch. No LLM involved. |
| `GET` | `/rule/{rule_id}` | Full rule object (see schema below) |
| `POST` | `/chat` | Standard (non-streaming) chat — `{ message, context_rule_id?, history?, mode? }` → `{ response, rule_id, suggested_followups }`. Analyst mode only; persona modes require `/chat/stream`. |
| `POST` | `/chat/stream` | Streaming SSE chat — same request body; yields `data:` events (see below). Supports all three modes. |
| `POST` | `/validate/yaml` | Paste-back check for an edited pipeline YAML — `{ yaml_text }` → `{ valid, errors, warnings, summary }`. Validates structure plus custom-op paths, rule IDs, and source tables against the repository indexes. |
| `POST` | `/feedback` | Record a thumbs up/down on an assistant answer — `{ rating: "up"\|"down", mode, rule_id? }` → `{ ok: true }`. |
| `GET` | `/tree` | Hierarchical tree of all rules grouped by sub-domain → category → rule |

All protected routes are also available under the `/api/` prefix (e.g. `/api/rules`, `/api/chat`).

**`GET /rule/{rule_id}` response shape:**

```json
{
  "rule_id": "RCCOMP_103.1",
  "business_explanation": "...",
  "technical_rule": "...",
  "sap_fields": [
    { "field": "KNA1-KUNNR", "business_name": "Customer Number", "description": "...", "table": "KNA1" }
  ],
  "origin": "Customer / Completeness / ...",
  "workflow_steps": ["read_dataio", "filter", "select"],
  "yaml_reference": "rccomp_103_1.yaml",
  "sources": ["datamart_customer"],
  "description": "...",
  "quality_category": "Completeness",
  "severity": "High",
  "table_checked": "KNA1",
  "column_checked": "KUNNR",
  "referenced_rules": [
    {
      "rule_id": "RCACTI_1",
      "source": "dependent_on",
      "active": true,
      "description": "...",
      "quality_category": "Completeness",
      "severity": "High"
    }
  ]
}
```

**`POST /chat` and `POST /chat/stream` request body:**

```json
{
  "message": "Explain rule RCCOMP_103.1",
  "context_rule_id": "RCCOMP_103.1",
  "mode": "analyst",
  "history": [
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `message` | string | required | The user's question or user story. Max 2 000 chars in analyst mode; max 12 000 chars in engineer/pm mode. |
| `context_rule_id` | string \| null | `null` | Rule currently open in the sidebar. Anchors follow-up questions and persona target selection. |
| `mode` | `"analyst"` \| `"engineer"` \| `"pm"` | `"analyst"` | Chat mode. `analyst` = rule Q&A; `engineer` = concrete file-change instructions; `pm` = agile story generation. Persona modes only on `/chat/stream`. |
| `history` | array | `[]` | Prior conversation turns (max 20). |

**`POST /chat/stream` SSE event types:**

```
data: {"type": "status", "text": "Identifying affected rules and pipelines…"}  ← persona stages only
data: {"type": "chunk",  "text": "..."}                                         ← one or more text delta chunks
data: {"type": "done",   "rule_id": "...", "suggested_followups": [...]}        ← terminal event
```

### Admin endpoints (admin token required)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/dashboard` | Aggregated analytics for the Rule Health Dashboard (includes answer-feedback totals) |
| `POST` | `/admin/reload` | Re-read the rule inventory Excel, `golden/` YAML pipelines, and custom operations from disk. The fresh data is validated **before** the caches are swapped — a broken file returns `503` and the app keeps serving the previous data. |
| `GET` | `/admin/probe-llm` | Admin-only LLM connectivity check. Calls OpenAI; returns `{"llm":"ok"}` or `503 {"llm":"degraded"}`. |

---

## Project Structure

```
rule_agent/
├── Dockerfile                   # Backend container build
├── backend/
│   ├── main.py                  # FastAPI app, auth, rate limiting, all endpoints
│   ├── data_loader.py           # Excel/YAML/custom-ops loading & caching
│   ├── schema_validator.py      # Startup column validation
│   ├── rule_parser.py           # TABLE-FIELD regex extraction
│   ├── sap_mapper.py            # Z11 field label lookup
│   ├── lineage_service.py       # YAML-based lineage index
│   ├── explanation_engine.py    # OpenAI GPT-4o wrapper (explain + stream + token tracking)
│   ├── chat_agent.py            # Analyst intent routing, streaming, follow-up Q&A
│   ├── persona_agent.py         # Engineer / PM 3-stage persona pipeline
│   ├── analytics.py             # SQLite analytics (rule views + chat events + token usage)
│   ├── discover_schema.py       # Dev utility: print all column names + YAML keys
│   ├── requirements.txt         # Direct dependencies
│   ├── requirements-lock.txt    # Pinned lockfile for reproducible installs
│   ├── .env                     # Credentials (not committed — see Environment Variables)
│   └── data/
│       ├── dim_rules_inventory.xlsx
│       ├── MDG Official Z11.xlsx
│       ├── analytics.db         # Auto-created at runtime
│       ├── golden/              # YAML pipeline files (one per rule/group)
│       └── custom_operations/   # Python operation classes (indexed for AI context)
│           ├── address_fuzzy_matching/
│           ├── city_standarization/
│           ├── data_quality/
│           ├── geopy/
│           ├── machine_learning/
│           ├── postal_code/
│           ├── text_normalization/
│           └── ...
└── frontend/
    ├── vite.config.js           # Vite dev server + /api proxy
    ├── package.json
    └── src/
        ├── main.jsx
        ├── api.js               # Axios client; injects Bearer token header
        ├── App.jsx              # Shell, tabs, pinned rules, localStorage
        └── components/
            ├── ChatBox.jsx      # Chat panel with streaming SSE + mode switcher
            ├── RuleBrowser.jsx  # Slide-in rule list with search + category filter
            ├── RuleCard.jsx     # Right sidebar — full rule detail + export
            ├── TreeView.jsx     # Hierarchical D3 tree of all rules
            ├── GraphView.jsx    # D3 force-directed graph of rule relationships
            ├── FieldTable.jsx   # SAP field table inside RuleCard
            ├── Tooltip.jsx      # Accessible hover tooltip
            ├── AdminPage.jsx    # Admin login page
            ├── AdminDashboard.jsx # Rule Health Dashboard with charts
            └── ErrorBoundary.jsx  # React error boundary for graceful UI failures
```

---

## Environment Variables

Create `rule_agent/backend/.env` or export these in your shell before starting the server.

### Required

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key |
| `RULE_AGENT_API_TOKEN` | **Required in production/staging.** Bearer token for all protected endpoints. Generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model name (e.g. `gpt-4o`, `gpt-4o-mini`) |
| `RULE_AGENT_ENV` | `production` | Set to `development` to skip auth enforcement when no token is configured |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed origins. **Must not be `*` in production** (startup will fail) |
| `MAX_MESSAGE_LENGTH` | `2000` | Maximum chat message length in analyst mode (characters) |
| `MAX_PERSONA_MESSAGE_LENGTH` | `12000` | Maximum message length in engineer/pm mode — user stories can be long |
| `CHAT_RATE_LIMIT` | `30` | Max chat requests per minute per IP address |
| `RULE_AGENT_ADMIN_TOKEN` | Same as `RULE_AGENT_API_TOKEN` | Bearer token for admin endpoints |
| `RULE_AGENT_ADMIN_USER` | `admin` | Admin login username |
| `RULE_AGENT_ADMIN_PASSWORD` | *(empty)* | Admin login password. Required in production; any credentials accepted in dev when empty |
| `NOMINATIM_DOMAIN` | *(empty)* | `hostname:port` of an internal Nominatim geocoding service. Required only if using geolocator custom operations. |
| `NOMINATIM_VERIFY_TLS` | `true` | Set to `false` only on trusted internal networks with a controlled CA |
| `NOMINATIM_CA_BUNDLE` | *(empty)* | Path to a custom CA bundle (PEM) for corporate PKI; also respects `REQUESTS_CA_BUNDLE` |

### Example `.env`

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

RULE_AGENT_ENV=production
RULE_AGENT_API_TOKEN=your-32-char-token-here
CORS_ORIGINS=https://your-frontend.example.com

RULE_AGENT_ADMIN_USER=admin
RULE_AGENT_ADMIN_PASSWORD=your-admin-password-here

CHAT_RATE_LIMIT=30
MAX_MESSAGE_LENGTH=2000
MAX_PERSONA_MESSAGE_LENGTH=12000
```

---

## Setup — Local Development

### 1. Place data files

```
rule_agent/backend/data/
├── dim_rules_inventory.xlsx
├── MDG Official Z11.xlsx
└── golden/
    ├── rccomp_103_1.yaml
    └── ...
```

### 2. Configure environment variables

Copy `.env.example` to `rule_agent/backend/.env` and fill in your credentials.

For local development without auth enforcement:

```env
RULE_AGENT_ENV=development
# RULE_AGENT_API_TOKEN can be omitted in development mode
```

### 3. Backend

```bash
cd rule_agent/backend
pip install -r requirements-lock.txt
uvicorn main:app --reload
```

Backend runs at `http://localhost:8000`. On startup it logs:
- Number of active Customer rules loaded
- Column normalisation warnings
- Number of YAML transforms and custom operation modules indexed
- Schema validation pass/fail

### 4. Frontend

```bash
cd rule_agent/frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`. The Vite dev server proxies all `/api/*` requests to `localhost:8000`, stripping the `/api` prefix.

### 5. Bearer token in the frontend (non-dev)

If auth is enabled, set the token in the browser's `localStorage` before making API calls, or configure `RULE_AGENT_ENV=development` for local work without authentication.

---

## Docker Deployment

### Build

```bash
cd rule_agent
docker build -t rule-agent-backend .
```

### Run

```bash
docker run -p 8000:8000 \
  --env-file backend/.env \
  -v $(pwd)/backend/data:/app/data:ro \
  rule-agent-backend
```

The data directory is mounted read-only at `/app/data`. The `analytics.db` file is written inside the container at `/app/data/analytics.db` — use a writable mount or a named volume if you want to persist it:

```bash
docker run -p 8000:8000 \
  --env-file backend/.env \
  -v $(pwd)/backend/data:/app/data \
  rule-agent-backend
```

### Production workers

The default `CMD` starts 2 uvicorn workers. For higher concurrency use gunicorn:

```bash
docker run -p 8000:8000 \
  --env-file backend/.env \
  -v $(pwd)/backend/data:/app/data \
  rule-agent-backend \
  gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000
```

### Frontend build

```bash
cd rule_agent/frontend
npm run build          # outputs to dist/
```

Serve the `dist/` directory with any static host (Nginx, Caddy, Vercel, etc.). Configure your host to serve `index.html` for all non-asset paths (SPA routing).

In production, set the Vite `VITE_API_BASE` env var (or configure a reverse proxy) so `/api/*` requests from the built frontend reach your backend host.

---

## Authentication & Security

### Bearer token

All endpoints except `/health`, `/ready`, and `/admin/login` require:

```
Authorization: Bearer <RULE_AGENT_API_TOKEN>
```

In **development mode** (`RULE_AGENT_ENV=development`) with no token configured, auth is skipped entirely. Any other environment value (including `staging`, `production`) requires a token — the server refuses to start without one.

### Admin login

`POST /admin/login` (or `/api/admin/login`):

```json
{ "username": "admin", "password": "your-admin-password" }
```

Returns `{ "ok": true, "token": "<RULE_AGENT_ADMIN_TOKEN>" }` on success.

Use the returned token as a Bearer token to call `/admin/dashboard` and `/admin/probe-llm`.

### CORS

In production, `CORS_ORIGINS` must be set to your frontend origin(s). The server refuses to start if `CORS_ORIGINS=*` is set in production mode.

### Message limits

- Analyst chat messages are capped at `MAX_MESSAGE_LENGTH` characters (default 2 000), enforced at both the API schema level and inside the streaming endpoint before the generator starts.
- Engineer/PM messages are capped at `MAX_PERSONA_MESSAGE_LENGTH` (default 12 000) to accommodate pasted user stories.
- Conversation history is capped at 20 entries server-side; each history item is truncated to 8 000 characters before being passed to the agent.

---

## Chat Modes

The `mode` field on every chat request selects the agent pipeline:

### `analyst` (default)

Standard rule Q&A. Ask anything about a specific rule or search the catalog with natural language. Supports all intent types (explain, lineage, severity, SAP fields, etc.) and multi-turn follow-up dialogue. Available on both `/chat` and `/chat/stream`.

### `engineer`

**Data Engineer mode.** Paste a user story or change request. The agent:
1. Selects the relevant rules, YAML pipeline files, and custom Python operations via a targeted LLM call over compact catalogs.
2. Assembles grounded repository context (YAML sections, custom op source code, Databricks source table names) within a 28 000-character budget.
3. Streams a structured response:
   - `## Summary` — what changes and which rules are affected
   - `## Files to change` — exact file paths as bullet list
   - `### <file>` sections — before/after fenced code snippets for each file
   - `## Databricks validation` — a `%sql` cell and a PySpark cell using only real source tables from context

Only available on `/chat/stream`. Status events are emitted while retrieval runs.

### `pm`

**Project Manager mode.** Describe an issue or business need. The agent produces a fully structured agile user story:
- `## Title` + *As a… / I want… / so that…*
- `## Description` — 2–4 sentences of business context
- `## Acceptance Criteria` — Given/When/Then bullets
- `## Technical Notes` — affected rule IDs (bold, clickable), exact file paths, custom ops
- `## Testing Notes` — plain-language verification steps

Only available on `/chat/stream`. If the request is too vague for acceptance criteria, the agent asks one clarifying question instead of guessing.

### Status events during persona retrieval

While stages 1 and 2 run, the stream emits `status` events so the frontend can show a progress indicator:

```
data: {"type": "status", "text": "Identifying affected rules and pipelines…"}
data: {"type": "status", "text": "Reading pipeline definitions…"}
data: {"type": "chunk",  "text": "## Summary\n..."}
...
data: {"type": "done",   "rule_id": null, "suggested_followups": [...]}
```

---

## Admin Dashboard

Navigate to `/admin` in the frontend. You will be presented with a login form.

After authenticating, the **Rule Health Dashboard** displays:
- **Overview cards** — total rules, total views, unique rules accessed, coverage %, views today, views this week, chat queries with a rule context, total tokens used
- **Top 15 rules** — most-viewed rules with view counts
- **Daily activity chart** — rule views per day over the last 30 days
- **Intent distribution** — which chat intents (explain, lineage, severity, etc.) are used most
- **Trending rules** — rules viewed on the most distinct days in the last 30 days
- **Recent views** — last 10 rule view events with timestamps

The dashboard auto-refreshes every 60 seconds. A manual refresh button is also available.

---

## Analytics

Analytics are stored in `data/analytics.db` (SQLite, auto-created at runtime).

| Table | Columns | Populated by |
|-------|---------|--------------|
| `rule_views` | `rule_id`, `viewed_at` | Every `GET /rule/{rule_id}` call (async, fire-and-forget) |
| `chat_events` | `rule_id`, `intent`, `occurred_at` | Every `POST /chat` or `POST /chat/stream` call |
| `token_events` | `prompt_tokens`, `completion_tokens`, `total_tokens`, `model`, `call_type`, `occurred_at` | Every OpenAI API call (explain, stream, persona) |
| `feedback_events` | `rating`, `mode`, `rule_id`, `occurred_at` | Every thumbs up/down click on an assistant answer (`POST /feedback`) |

All analytics writes are non-blocking — a failure to write never returns an error to the user.

---

## Rate Limiting

Chat endpoints (`/chat` and `/chat/stream`) are rate-limited per client IP address.

| Variable | Default | Description |
|----------|---------|-------------|
| `CHAT_RATE_LIMIT` | `30` | Max requests per minute per IP |

On limit exceeded, the API returns:

```json
HTTP 429
{ "detail": "Too many requests. Please wait before trying again." }
```

---

## Frontend Components

| Component | Role |
|-----------|------|
| `App.jsx` | Shell — topbar, browser toggle, sidebar toggle, tabbed rule history (pinned + up to 20 recent), `localStorage` persistence |
| `ChatBox.jsx` | Main panel — mode switcher (analyst / engineer / pm), sends messages to `/api/chat/stream` (SSE streaming), displays markdown responses, shows status banners during persona retrieval. Per-code-block copy buttons, thumbs up/down feedback, Databricks-notebook download (engineer answers), Copy-for-Jira / copy-markdown (PM stories), and a Validate YAML button (engineer mode) |
| `RuleBrowser.jsx` | Slide-in panel — full list of all 228 rules, live search by ID / category / table / description, filter chips by quality category |
| `RuleCard.jsx` | Right sidebar — full rule detail, business explanation, metadata, data sources, workflow steps, SAP fields, technical rule (expandable + copy), rule references (clickable deps), related rules grid, export/download |
| `TreeView.jsx` | Hierarchical D3 tree — sub-domain → category → rule, click any node to load the rule |
| `GraphView.jsx` | D3 force-directed graph — visualises rule relationships and dependencies |
| `FieldTable.jsx` | Nested table inside RuleCard showing mapped SAP fields |
| `Tooltip.jsx` | Accessible hover tooltip used throughout the UI |
| `YamlValidator.jsx` | Modal for the engineer paste-back check — paste an edited `golden/` pipeline YAML and validate it against the repository (`POST /validate/yaml`) before committing |
| `AdminPage.jsx` | Login form for the admin dashboard; stores session token in `sessionStorage` |
| `AdminDashboard.jsx` | Rule Health Dashboard — charts, tables, overview cards including token usage and answer feedback, plus a Reload Data button (`POST /admin/reload`) |
| `ErrorBoundary.jsx` | React error boundary; catches unexpected component errors and shows a fallback UI |

**Tab management:**
- **Pinned rules** — appear at the top of the sidebar tab list, persist across reloads, unlimited count
- **Recent rules** — up to 20, appended as rules are loaded, persisted in `localStorage`
- Rules can be pinned/unpinned per-tab; closing moves them out of history

**Vite proxy** — all frontend API calls use the `/api/` prefix. Vite strips it and forwards to `localhost:8000`:

```
/api/rules           → GET  http://localhost:8000/rules
/api/rule/RCCOMP_1   → GET  http://localhost:8000/rule/RCCOMP_1
/api/chat            → POST http://localhost:8000/chat
/api/chat/stream     → POST http://localhost:8000/chat/stream
/api/tree            → GET  http://localhost:8000/tree
/api/admin/dashboard → GET  http://localhost:8000/admin/dashboard
```

---

## Sample Chat Queries

```
# Analyst mode — rule-specific queries
Explain rule RCCOMP_103.1
What SAP fields are used in RCACTI_1?
What table does RCCOMP_106.1 check?
What is the severity of RCCONF_22_7?
Where does rule RCCOMP_108.1 come from?
Workflow of rule RCCOMP_108.1
Show rule RCCONF_22_7

# Analyst mode — catalog search (no rule ID needed)
How many completeness rules are there?
List all conformity rules
Which rules check KNA1?
Find a rule that validates phone numbers
Is there a rule for email validation?
How many rules are there in total?

# Analyst mode — follow-up questions (with a rule open in the sidebar)
What does "order block" mean in this context?
Why does this rule check the credit limit?
What other rules run in the same pipeline?
How critical is this rule?
Which upstream data sources does this rule depend on?

# Engineer mode (paste as message with mode: "engineer")
As a data engineer, I need to update the email validation rule RCCOMP_103.1
to also check the secondary email field SMTP_ADDR2. The rule currently only
checks SMTP_ADDR. Update the YAML pipeline and the inventory row accordingly.

# PM mode (paste as message with mode: "pm")
Customers are failing the postal code check RCVAL_55 even when their address
is correct because the rule doesn't handle the new 4-digit postcode format
introduced in Belgium last quarter.
```

---

## Adding New YAML Pipelines

1. Drop the `.yaml` file into `backend/data/golden/` (any subdirectory).

2. Ensure it has the standard transform structure:

   ```yaml
   transform:
     name: your_rule_name
     operations:
       - kind: read_dataio
         params:
           object_name: source_datamart
       - kind: select
         params:
           columns:
             FIELD_A: field_a_alias
   ```

3. To link the YAML to a specific rule ID, add an expression literal anywhere in the pipeline:

   ```yaml
   expression: "'RCCOMP_103.1'"
   ```

4. Restart the backend — YAML files and custom operation classes are auto-discovered on startup.

---

## Schema Discovery

To inspect all column names before running the app:

```bash
cd rule_agent/backend
python discover_schema.py
```

Prints all column names, the first 3 rows of each Excel sheet, and the top-level keys from every YAML file. Useful when columns are renamed or a new data source is added.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `RULE_AGENT_API_TOKEN must be set` | Set `RULE_AGENT_API_TOKEN` in `.env`, or set `RULE_AGENT_ENV=development` for local work |
| `Refusing to start with wildcard CORS` | Set `CORS_ORIGINS` to your specific frontend origin instead of `*` |
| `OPENAI_API_KEY must be set` | Add `OPENAI_API_KEY` to `backend/.env` or export it before starting uvicorn |
| `Rule not found` | Rule may be inactive or non-Customer; check `is_active=1` and `domain=Customer` in the Excel |
| `No lineage columns found` | Expected columns (`module`, `group`, `rule_responsibility`, etc.) are missing from the Excel — lineage will return empty |
| Schema validation fails on startup | Run `python discover_schema.py` to see actual column names; update candidate lists in `data_loader.py` if needed |
| YAML file skipped | YAML syntax error (e.g. unhashable key); check the `[WARNING] Skipping` log line |
| Rule not matched to its YAML | The YAML has no expression literal for the rule ID; add `expression: "'RULE_ID'"` inside the pipeline |
| Port 8000 in use | `lsof -ti:8000 \| xargs kill` (macOS/Linux) or `netstat -ano \| findstr 8000` (Windows) |
| Frontend 404 on `/api/...` | Ensure the backend is running on port 8000 before `npm run dev` |
| Explanation says "Unable to generate" | OpenAI API key invalid or model name wrong; check `[ERROR]` logs |
| `/admin/probe-llm` returns `"llm":"degraded"` | OpenAI is unreachable from the server; verify network/firewall and `OPENAI_API_KEY` |
| `/ready` returns 503 | `OPENAI_API_KEY` is not set or no rules loaded; check the `issues` array in the response |
| Follow-up Q&A gives wrong answer | Try asking with an explicit rule ID in the message to anchor the context |
| Custom ops not shown in lineage | The YAML `kind` must contain the `governance_data_quality_processes.custom_operations.` prefix |
| Engineer mode returns generic answer | No rules/pipelines matched the user story; include an explicit rule ID or pipeline name in the message |
| Engineer/PM mode not available on `/chat` | Persona modes (`engineer`, `pm`) require `/chat/stream` — use the streaming endpoint |
| Admin dashboard shows all zeros | No rules have been viewed yet, or `analytics.db` was deleted; data populates as users interact |
| Admin login rejected in production | Set `RULE_AGENT_ADMIN_USER` and `RULE_AGENT_ADMIN_PASSWORD` in `.env` |
| Rate limit hit in development | Increase `CHAT_RATE_LIMIT` in `.env` or restart the server to reset counters |
| Geocoding custom ops return `config_error` | Set `NOMINATIM_DOMAIN` in `.env` to point at your internal Nominatim instance |
