# Rule Agent

AI-powered data quality rule intelligence for Coca-Cola HBC. FastAPI backend + React/Vite frontend. A multi-knowledge-base, KB-aware assistant: it explains 228 Customer data quality rules in plain English (the original structured/hybrid knowledge base) and can also answer over retrieval-augmented document knowledge bases — including ones a user adds themselves from a Git repository. Powered by the Anthropic (Claude) API, choosing a model tier per task (Haiku for routing, Sonnet for explanations/stories, Opus for Engineer file-edits).

---

## ⚠️ SECURITY: Rotate Any Exposed API Key Immediately

If `backend/.env` previously contained an Anthropic (or older OpenAI/Azure) API key and that file was ever committed to git, synced via OneDrive, or shared in any way, **the key must be treated as compromised and rotated before any deployment.**

**How to rotate (Anthropic):**
1. [Anthropic Console](https://console.anthropic.com/) → **Settings → API Keys**
2. Revoke the exposed key and create a new one
3. Update `backend/.env` with the new key (`ANTHROPIC_API_KEY=...`)
4. Do **not** commit `backend/.env` — it is listed in `.gitignore`

---

## Quick Start (Local Development)

```bash
# 1. Backend
cd backend
cp .env.example .env          # then fill in real values
pip install -r requirements.txt
uvicorn main:app --reload     # http://localhost:8000

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev                   # http://localhost:5173
```

The Vite dev server proxies `/api/*` to `http://localhost:8000`, stripping the `/api` prefix. No extra config needed for local dev.

---

## Environment Variables

### Backend (`backend/.env`)

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key. **Never commit this value** |
| `OPENAI_API_KEY` | Yes | OpenAI API key — used for conversation title generation (`gpt-4o-mini`) **and** for RAG embeddings (`text-embedding-3-small`, see `EMBEDDINGS_MODEL`). Effectively required for any RAG / knowledge-repo feature, not just titles. |
| `DATABASE_URL` | No | SQLAlchemy async DSN for users/projects/conversations/messages + analytics. Default: local SQLite (`data/rule_agent.db`). Postgres: `postgresql+asyncpg://user:pass@host:5432/rule_agent` |
| `DATABASE_URL_SYNC` | No | Synchronous DSN used by the sync token-usage writer and the migration scripts. Derived automatically from `DATABASE_URL` (`+asyncpg`→`+psycopg`, `+aiosqlite` stripped); override only if needed. |
| `ANTHROPIC_MODEL_FAST` | No | Model for routing/intent/follow-up suggestions/persona selector. Default: `claude-haiku-4-5` |
| `ANTHROPIC_MODEL_STANDARD` | No | Model for rule explanations, analyst answers, PM stories. Default: `claude-sonnet-4-6` |
| `ANTHROPIC_MODEL_DEEP` | No | Model for Engineer persona file-edit generation. Default: `claude-opus-4-8` |
| `ACTIVE_KB` | No | Default knowledge base id (matches a `backend/kb/<id>.yaml` descriptor) served when no KB is explicitly selected, or when `ENABLE_KB_SWITCHER=false`. Default: `customer_sap` |
| `ENABLE_KB_SWITCHER` | No | Set to `false` to pin the app to `ACTIVE_KB` only, ignoring any client-requested `knowledge_base_id`. Default: `true` |
| `KB_DIR` | No | Directory of KB descriptor YAML files. Default: `backend/kb` |
| `EMBEDDINGS_MODEL` | No | OpenAI embeddings model used for RAG ingestion and query embedding. Default: `text-embedding-3-small` |
| `KB_REPO_SECRET_KEY` | Production | Secret used to derive the Fernet key that encrypts a self-service Git-repo KB's private-repo access token at rest. Unset: tokens are stored in **plaintext** (a one-time warning is logged, never the token). Set this before deploying a self-service repo feature to production. |
| `RULE_AGENT_API_TOKEN` | Production | Bearer token for all protected endpoints. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `RULE_AGENT_ENV` | No | Set to `production` to enforce token at startup. Default: `development` |
| `RULE_AGENT_ADMIN_USER` | No | Username checked by `POST /admin/login`. Default: `admin` |
| `RULE_AGENT_ADMIN_PASSWORD` | Production | Password checked by `POST /admin/login`. In dev mode (`RULE_AGENT_ENV=development`) with no password set, any username/password is accepted. |
| `RULE_AGENT_ADMIN_TOKEN` | No | Bearer token required by `/admin/*` endpoints (e.g. `POST /admin/reload`). Falls back to `RULE_AGENT_API_TOKEN` if unset. |
| `CORS_ORIGINS` | No | Comma-separated allowed origins. Default: `http://localhost:5173,http://127.0.0.1:5173` |
| `CHAT_RATE_LIMIT` | No | Max `/chat` requests per minute per IP. Default: `30` |
| `MAX_MESSAGE_LENGTH` | No | Max chat message characters. Default: `2000` |
| `MAX_PERSONA_MESSAGE_LENGTH` | No | Max characters for Engineer/PM persona messages (pasted user stories run longer than analyst questions); also the schema cap for chat history items sent back to the API. Default: `12000` |
| `NOMINATIM_DOMAIN` | No | Hostname:port of the internal Nominatim geocoding service. No default; geocoding is disabled if unset. |
| `NOMINATIM_VERIFY_TLS` | No | Set to `false` only on trusted internal networks. Default: `true`. |
| `NOMINATIM_CA_BUNDLE` | No | Path to a custom CA certificate bundle (PEM) for corporate PKI. |

In **production**, provision these as environment variables via your secret manager (Kubernetes Secrets, Vault, etc.). Do **not** rely on a committed `.env` file.

### Frontend (`frontend/.env`)

| Variable | Required | Description |
|---|---|---|
| `VITE_API_BASE_URL` | No | Backend origin for cross-domain deployments. Leave empty when frontend and backend share the same domain. |
| `VITE_API_TOKEN` | No | Bearer token embedded in the browser bundle. See warning below. |

> ⚠️ **`VITE_API_TOKEN` is embedded in the browser JS bundle at build time.** Only use it when the app is deployed behind internal access controls (corporate VPN, SSO, IP allowlist). Never expose it on a publicly accessible site.

---

## Authentication

Set `RULE_AGENT_API_TOKEN` in `backend/.env`. All protected endpoints then require:

```
Authorization: Bearer <your-token>
```

**Protected endpoints** (require the Bearer token above):

- **Knowledge bases:** `GET /kbs`, `GET /kbs/{kb_id}`
- **Chat:** `POST /chat`, `POST /chat/stream`, `POST /kb/{kb_id}/chat`, `POST /kb/{kb_id}/chat/stream`
- **Entity (rule) detail** — entity-capable KBs only (404 for a RAG-only KB): `GET /kb/{kb_id}/entity/{entity_id}`, `GET /kb/{kb_id}/entities/related/{entity_id}`
- **Custom prompt** (Settings → per-KB prompt): `PUT /kb/{kb_id}/prompt`, `POST /kb/{kb_id}/prompt/enhance`
- **Feedback:** `POST /feedback`, `POST /kb/{kb_id}/feedback`
- **Self-service Git-repo KBs** (Settings → Knowledge repositories — see [Add a Knowledge Repository](#add-a-knowledge-repository)): `POST /kb-repos`, `GET /kb-repos`, `GET /kb-repos/{repo_id}`, `POST /kb-repos/{repo_id}/resync`, `DELETE /kb-repos/{repo_id}`
- **Workspace** (also require the `X-User` header — see [Chat History & Database](#chat-history--database)): `POST /users/login`, `GET/POST /projects`, `PATCH/DELETE /projects/{id}`, `GET/POST /conversations`, `GET/PATCH/DELETE /conversations/{id}`, `GET /conversations/{id}/messages`
- **Admin** (separate `RULE_AGENT_ADMIN_TOKEN`, falls back to `RULE_AGENT_API_TOKEN`): `POST /admin/reload`

**Public endpoints:** `GET /health`, `GET /ready`, `POST /admin/login` (validates `RULE_AGENT_ADMIN_USER`/`RULE_AGENT_ADMIN_PASSWORD` and returns a session token for the admin dashboard)

Every route above is registered under both its bare path and an `/api`-prefixed path — see [API Routing](#api-routing).

Setting `RULE_AGENT_ENV=production` with no token will abort startup with an error, preventing an accidentally open deployment.

**Auth is fail-closed for any non-`development` value of `RULE_AGENT_ENV`** (e.g. `staging`, `production`, any other string). The only mode that allows no token is `RULE_AGENT_ENV=development` (the default for local dev).

---

## Browser Storage

The frontend stores only non-sensitive rule metadata (ID, description, category, severity, table) in `localStorage` for tabs and pinned rules. Full rule data (technical rule logic, SAP fields, workflow steps) is held in memory only and re-fetched on demand. Refreshing the page or closing the browser clears the in-memory cache — tabs will re-fetch from the API when clicked.

The workspace **username** (lightweight identity) is stored in `localStorage` and sent as the `X-User` header. Chat history itself lives server-side in the database, not the browser.

---

## Chat History & Database

Conversations are persisted in a SQLAlchemy-backed database (SQLite for local dev, **PostgreSQL** for production via `DATABASE_URL`). The schema is created automatically on startup.

- **Lightweight login** — a user claims a workspace by username (no password); requests carry it in the `X-User` header. `POST /users/login` get-or-creates the user.
- **Projects** group conversations and carry a short **standing-instructions** string (e.g. "scope answers to the DCC module") injected into every chat in that project.
- **Conversations** are each bound to one persona (`analyst` / `engineer` / `pm`); switching persona means a separate thread. Titles are auto-generated by `gpt-4o-mini` after the first reply.
- **Messages** (user + assistant, with rule IDs and follow-ups) are stored per conversation.

**Workspace endpoints:** `/users/login`, `/projects` (+ `/{id}`), `/conversations` (+ `/{id}`, `/{id}/messages`). All require the Bearer token and the `X-User` header.

### Migrating legacy analytics

Earlier versions stored analytics in a standalone SQLite file (`data/analytics.db`). To copy that history into the new database:

```bash
cd backend
# set DATABASE_URL to the target (Postgres) first, or leave default for SQLite
python migrate_analytics_to_pg.py          # skips tables that already have rows
python migrate_analytics_to_pg.py --force  # insert regardless
```

### Local Postgres (optional)

```bash
docker run -d --name rule-agent-pg -e POSTGRES_PASSWORD=pass -e POSTGRES_DB=rule_agent -p 5432:5432 postgres:16
# in backend/.env:
DATABASE_URL=postgresql+asyncpg://postgres:pass@localhost:5432/rule_agent
```

The synchronous DSN (used by the token-usage writer) is derived automatically; override with `DATABASE_URL_SYNC` only if needed.

---

## Knowledge Bases & RAG

The backend is knowledge-base–aware: each KB is described by a YAML descriptor in `backend/kb/*.yaml` (directory configurable via `KB_DIR`), with an `adapter` of `structured` (rule/table lookups only), `rag` (retrieval over embedded document chunks), or `hybrid` (both). Two KBs ship in this repo:

- **`customer_sap`** (`hybrid`) — the 228-rule Customer/SAP data-quality dataset described above.
- **`docs_demo`** (`rag`) — a small sample documentation KB (`backend/kb/sample_docs/`) demonstrating retrieval-augmented answering over arbitrary documents.

The in-app KB switcher (Settings) is controlled by `ENABLE_KB_SWITCHER` (default `true`) and `ACTIVE_KB` (default `customer_sap` — the KB served when the switcher is off, or when no KB is explicitly selected).

**RAG ingestion** (clone/read → chunk → embed → store) runs via a CLI:

```bash
cd backend
python -m ingest --kb docs_demo   # or --kb customer_sap, or any registered KB id
```

This calls OpenAI embeddings (`EMBEDDINGS_MODEL`, default `text-embedding-3-small`), so `OPENAI_API_KEY` is required. The same path also runs from inside the app: `POST /admin/reload?kb=<id>` re-ingests one KB on demand, and adding a Git-repo KB (below) triggers it automatically in the background.

**Vector storage** auto-selects by database dialect (`vector_store.get_vector_store`): SQLite/dev uses `NumpyVectorStore` (brute-force cosine similarity over a JSON-encoded embedding column); Postgres uses `PgVectorStore` (a native `pgvector` column queried via `<=>` with an ivfflat cosine index).

**Migrations** — the `kb_documents`, `kb_chunks`, and `kb_repos` tables auto-create at startup on any database (SQLite or Postgres) as part of normal schema init. Two extra scripts handle idempotent, Postgres-specific setup and are safe to (re-)run any time:

```bash
cd backend
python -m migrations.m0002_rag       # Postgres only: enables the pgvector extension + a native embedding_vector column/index (degrades gracefully if unavailable)
python -m migrations.m0003_kb_repos  # creates kb_repos (no-op if it already exists)
```

---

## Add a Knowledge Repository

From **Settings → Knowledge repositories**, any user can add a public or private Git repository as a brand-new retrieval-augmented knowledge base — no restart or config file needed.

1. Enter a name, the Git URL, and optionally a ref (branch/tag/commit) and `include_globs` (comma-separated; default `**/*.md`).
2. For a private repo, set visibility to `private` and paste a Personal Access Token (required in that case).
3. The repo is registered immediately with status `queued`, and ingestion (clone → chunk → embed) starts in the background.
4. Status moves `queued` → `ingesting` → `ready` (or `error`, with a sanitized detail on failure). The KB appears in the switcher only once it reaches `ready`.
5. Resync (re-ingest, e.g. after the source repo changes) or delete the KB (and its stored chunks) at any time.

Config persists in the `kb_repos` table, so a repo KB survives a backend restart — it's re-registered into the KB registry at startup, and any row still `queued`/`ingesting` when a restart interrupts it is marked `error` so the user knows to resync rather than poll forever.

**Requirements & notes:**
- `git` must be installed wherever the backend runs — ingestion shells out to it directly for the clone. The Docker image installs it (see Production Deployment → Docker below).
- Set `KB_REPO_SECRET_KEY` in production: it derives the Fernet key used to encrypt a private repo's access token at rest. Left unset, tokens are stored in **plaintext** (a one-time warning is logged, never the token itself) — acceptable for local dev, not for production.
- Endpoints (all require the Bearer token): `POST /kb-repos`, `GET /kb-repos`, `GET /kb-repos/{id}`, `POST /kb-repos/{id}/resync`, `DELETE /kb-repos/{id}`.

---

## API Routing

FastAPI registers all protected routes under **both** the bare path and the `/api` prefix:

| Dev (Vite proxy) | Production |
|---|---|
| `GET /api/kbs` → proxy strips prefix → FastAPI `/kbs` | `GET /api/kbs` → FastAPI `/api/kbs` |
| `POST /api/chat` → proxy strips prefix → FastAPI `/chat` | `POST /api/chat` → FastAPI `/api/chat` |

No Vite config changes needed; production works via the `/api` routes.

---

## Production Deployment

### Uvicorn (single server)

```bash
# Do NOT use --reload in production
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
```

### Gunicorn + Uvicorn workers (recommended for multi-core)

```bash
pip install gunicorn
gunicorn main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### Docker

```bash
cp backend/.env.example backend/.env   # fill in real values
docker compose up --build
```

The backend image also installs `git` (required at runtime by the self-service "add a Git repo" RAG ingestion feature — see [Add a Knowledge Repository](#add-a-knowledge-repository)). Set `KB_REPO_SECRET_KEY` before deploying if users will add private repos, so their access tokens are encrypted at rest instead of stored in plaintext.

Backend runs at `http://localhost:8000`. Serve the built frontend separately:

```bash
cd frontend && npm run build           # outputs to frontend/dist/
# Serve dist/ via nginx, Caddy, or any static file host
```

### Reverse Proxy (nginx) — recommended production setup

```nginx
server {
    # Serve frontend static files
    root /var/www/rule-agent/dist;
    index index.html;

    # Proxy API to backend
    location /api/ {
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }

    # Proxy health/ready probes (no /api prefix)
    location ~ ^/(health|ready)$ {
        proxy_pass http://localhost:8000;
    }

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Set `CORS_ORIGINS` to your production domain, e.g.:

```
CORS_ORIGINS=https://rule-agent.internal.example.com
```

---

## Health & Readiness Probes

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | Public | Liveness: returns 200 if the process is running and data is loaded |
| `GET /ready` | Public | Readiness: verifies `ANTHROPIC_API_KEY` is present and rules are loaded. Returns 503 if not ready. Does **not** call the LLM. |

Use `/ready` as your Kubernetes `readinessProbe` or load-balancer health check.

---

## Running Tests

```bash
cd rule_agent/backend
pip install -r requirements-dev.txt
pytest tests/ -v
```

Tests run against a fully mocked backend (no real data files, no Anthropic calls). See `tests/conftest.py` for the stub setup.

---

## Dependency Pinning

`requirements.txt` lists minimum compatible versions. `requirements-lock.txt` pins exact resolved versions for reproducible production installs.

```bash
# Install from lock file (recommended for production)
pip install -r requirements-lock.txt

# Regenerate lock file after upgrading
pip install -r requirements.txt
pip freeze > requirements-lock.txt   # review the diff before committing
```

`requirements-dev.txt` adds pytest and httpx for running tests.
