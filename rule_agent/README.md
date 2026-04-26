# Rule Agent

AI-powered data quality rule intelligence for Coca-Cola HBC. FastAPI backend + React/Vite frontend. Explains 228 Customer data quality rules in plain English via Azure OpenAI.

---

## ⚠️ SECURITY: Rotate Your Azure Key Immediately

If `backend/.env` previously contained an Azure OpenAI API key and that file was ever committed to git, synced via OneDrive, or shared in any way, **the key must be treated as compromised and rotated before any deployment.**

**How to rotate:**
1. Azure Portal → Your Azure OpenAI resource → **Keys and Endpoint**
2. Click **Regenerate Key 1** (or Key 2, whichever was used)
3. Update `backend/.env` with the new key
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
| `AZURE_OPENAI_ENDPOINT` | Yes | Azure OpenAI gateway URL |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | Model deployment name (e.g. `gpt-4o`) |
| `AZURE_OPENAI_API_VERSION` | Yes | API version (e.g. `2024-02-15-preview`) |
| `AZURE_OPENAI_API_KEY` | Yes | **Never commit this value** |
| `RULE_AGENT_API_TOKEN` | Production | Bearer token for all protected endpoints. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `RULE_AGENT_ENV` | No | Set to `production` to enforce token at startup. Default: `development` |
| `CORS_ORIGINS` | No | Comma-separated allowed origins. Default: `http://localhost:5173,http://127.0.0.1:5173` |
| `CHAT_RATE_LIMIT` | No | Max `/chat` requests per minute per IP. Default: `30` |
| `MAX_MESSAGE_LENGTH` | No | Max chat message characters. Default: `2000` |
| `AZURE_OPENAI_TIMEOUT` | No | LLM call timeout in seconds. Default: `30` |
| `NOMINATIM_DOMAIN` | No | Hostname:port of the internal Nominatim geocoding service. No default; geocoding is disabled if unset. |
| `NOMINATIM_VERIFY_TLS` | No | Set to `false` only on trusted internal networks. Default: `true`. |
| `NOMINATIM_CA_BUNDLE` | No | Path to a custom CA certificate bundle (PEM) for corporate PKI. |

In **production**, provision these as environment variables via your secret manager (Azure Key Vault, Kubernetes Secrets, etc.). Do **not** rely on a committed `.env` file.

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

**Protected endpoints:** `/chat`, `/rule/{id}`, `/rules`, `/rules/related/{id}`, `/tree`  
**Public endpoints:** `/health`, `/ready`

Setting `RULE_AGENT_ENV=production` with no token will abort startup with an error, preventing an accidentally open deployment.

**Auth is fail-closed for any non-`development` value of `RULE_AGENT_ENV`** (e.g. `staging`, `production`, any other string). The only mode that allows no token is `RULE_AGENT_ENV=development` (the default for local dev).

---

## Browser Storage

The frontend stores only non-sensitive rule metadata (ID, description, category, severity, table) in `localStorage` for tabs and pinned rules. Full rule data (technical rule logic, SAP fields, workflow steps) is held in memory only and re-fetched on demand. Refreshing the page or closing the browser clears the in-memory cache — tabs will re-fetch from the API when clicked.

---

## API Routing

FastAPI registers all protected routes under **both** the bare path and the `/api` prefix:

| Dev (Vite proxy) | Production |
|---|---|
| `GET /api/rules` → proxy strips prefix → FastAPI `/rules` | `GET /api/rules` → FastAPI `/api/rules` |
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
| `GET /ready` | Public | Readiness: verifies Azure config is present and rules are loaded. Returns 503 if not ready. Does **not** call Azure OpenAI. |

Use `/ready` as your Kubernetes `readinessProbe` or load-balancer health check.

---

## Running Tests

```bash
cd rule_agent/backend
pip install -r requirements-dev.txt
pytest tests/ -v
```

Tests run against a fully mocked backend (no real data files, no Azure calls). See `tests/conftest.py` for the stub setup.

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
