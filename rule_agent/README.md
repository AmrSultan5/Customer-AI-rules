# Rule Intelligence — Customer Data Quality Agent

A full-stack AI assistant that reads 228 active Customer data quality rules from Excel and YAML sources, maps SAP field references to business terminology, and answers natural-language questions through a chat interface.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          React Frontend                               │
│  ┌─────────────┐  ┌─────────────────┐  ┌──────────────────────────┐  │
│  │   ChatBox   │  │   RuleBrowser   │  │        RuleCard          │  │
│  │  (left/main)│  │  (slide-in      │  │  (right sidebar — tabbed │  │
│  │             │  │   browse panel) │  │   pinned + recent rules) │  │
│  └──────┬──────┘  └────────┬────────┘  └──────────┬───────────────┘  │
└─────────┼──────────────────┼────────────────────── ┼─────────────────┘
          │ POST /api/chat   │ GET /api/rules         │ GET /api/rule/{id}
          │                  │ GET /api/rules/related/│ {id}
          ▼                  ▼                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│                          FastAPI Backend                              │
│                                                                       │
│  ┌────────────┐  ┌─────────────────┐  ┌──────────────────────────┐   │
│  │ ChatAgent  │  │ExplanationEngine│  │     LineageService        │   │
│  │ (intent    │  │ (Azure OpenAI   │  │  (workflow / lineage      │   │
│  │  routing + │  │  GPT-4o — rule  │  │   from YAML & Excel)     │   │
│  │  AI search)│  │  explanations + │  └──────────┬───────────────┘   │
│  └─────┬──────┘  │  follow-up Q&A) │             │                    │
│        │         └────────┬────────┘             │                    │
│        │                  │                      │                    │
│  ┌─────▼──────────────────▼──────────────────────▼────────────────┐  │
│  │                        DataLoader                                │  │
│  │  dim_rules_inventory.xlsx │ MDG Official Z11.xlsx │ *.yaml      │  │
│  │  custom_operations/**/*.py (indexed for context)                │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌──────────────────┐  ┌───────────────────┐  ┌──────────────────┐   │
│  │  RuleParser      │  │   SapMapper       │  │ SchemaValidator  │   │
│  │  (TABLE-FIELD    │  │  (Z11 field label │  │ (startup column  │   │
│  │   regex extract) │  │   lookup)         │  │  validation)     │   │
│  └──────────────────┘  └───────────────────┘  └──────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
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

**Filtering applied at load time:** only rows where `domain = Customer` and `is_active = 1` are kept — yielding the 228 active rules shown in the UI.

Column names are normalised to `snake_case` automatically, and flexible candidate-column detection ensures the loader is resilient to minor Excel header changes.

### 2 — Schema Validation (`schema_validator.py`)

On startup, required columns are verified in both DataFrames before the server accepts requests:

| DataFrame | Required columns |
|-----------|-----------------|
| Rules | `rule_id`, `domain`, `is_active`, `rule_logic` |
| SAP map | `sap_table`, `sap_field`, `field_label` |

If any required column is missing, the server logs an `[ERROR]` and raises a `ValueError`.

### 3 — Rule Parsing (`rule_parser.py`)

Given a rule's `technical_definition` / `rule_logic` text, a regex extracts all SAP field references matching the pattern `TABLE-FIELD` (e.g. `KNA1-KUNNR`, `VBAK-VBELN`).

```
rule_logic text  →  regex  →  ["KNA1-KUNNR", "VBAK-VBELN", ...]
```

### 4 — SAP Field Mapping (`sap_mapper.py`)

Each extracted `TABLE-FIELD` string is looked up in the Z11 sheet to retrieve:
- `business_name` — the human-readable field label
- `description` — usage notes from the CCHBC comments column
- `table` — the SAP table name

A field-only fallback is used when a full `TABLE-FIELD` key is not found.

### 5 — YAML Lineage Enrichment (`lineage_service.py` + `data_loader.py`)

For each rule, the system attempts to match a YAML pipeline in `golden/` using a two-stage lookup:

1. **Content match** (preferred) — the YAML explicitly evaluates the rule ID as an expression literal (`expression: 'RCCOMP_12.1'`).
2. **Name heuristic fallback** — the transform `name` contains fragments of the rule ID.

When a match is found, the following are extracted:
- **`workflow_steps`** — `name` or `kind` of each pipeline operation
- **`pipeline_sources`** — `object_name` values from `read_dataio` operations (upstream data tables)
- **`yaml_reference`** — the matched filename
- **`sibling_rules`** — other rule IDs evaluated in the same pipeline
- **`custom_operations`** — Python operation classes used by the pipeline, with their docstrings

`extract_rule_section_from_yaml()` further isolates the portion of a YAML file that applies to a specific rule, using comment anchors and line windows.

### 6 — Custom Operations Indexing (`data_loader.py`)

All Python files in `custom_operations/` are scanned at startup. For each file:
- The first `*Operation` class and its docstring are extracted via regex.
- The class is keyed by its dotted module path (e.g. `city_standarization.geocoords_address_conformity`).

This index is injected into rule context when answering follow-up questions, so the AI can explain what e.g. a fuzzy matching or geocoordinate operation does.

### 7 — Cross-Rule Reference Resolution (`data_loader.py`)

`get_referenced_rules(rule_id)` walks both the `dependent_on` column and `rule_logic` text to find any rule IDs that the given rule depends on or references. Each returned entry includes:
- `rule_id`, `rule_description`, `rule_logic`, `table_name_checked`
- `quality_category`, `source` (`dependent_on` or `logic`), `active` flag

These dependencies are exposed in the API response as `referenced_rules` and displayed as clickable cards in the UI.

### 8 — AI Explanation (`explanation_engine.py`)

The rule logic (and a sanitised SAP field context) is sent to **Azure OpenAI GPT-4o** with a system prompt instructing it to produce a 2–3 sentence plain-English business explanation. No SAP field names or code appear in the output.

```
rule_logic + sap_context  →  Azure OpenAI GPT-4o  →  plain English explanation
```

Results are `lru_cache`d so the same logic string is never sent twice in a session.

`call_azure_openai()` is a non-cached variant used for intent classification and follow-up Q&A, and it accepts optional conversation `history`.

### 9 — Chat Intent Routing (`chat_agent.py`)

The `/chat` endpoint receives a free-text message. The agent:

1. Tries to extract an explicit rule ID from the message (regex: `[A-Z]{2,8}_\d+(\.\d+)?`).
2. If a rule ID is found, detects intent via keyword matching:

| Keywords in message | Intent | Response |
|---------------------|--------|---------|
| sap table, which table, what table, table checked | `sap_table` | The SAP table the rule checks |
| sap column, which column, column name, column for | `sap_column` | The SAP column the rule checks |
| severity, how severe, priority level, criticality | `severity` | Severity label (Critical / High / Medium / Low) |
| description, rule description | `description` | The rule's free-text description |
| explain, what does, what is, describe, meaning | `explain` | AI plain-English explanation |
| where does, come from, source, origin, lineage | `lineage` | Module, group, data sources, pipeline steps |
| workflow, steps, pipeline, process | `workflow` | Full lineage including YAML pipeline steps and custom ops |
| sap field, fields used, what field, which field | `fields` | List of `TABLE-FIELD (Business Name)` pairs |
| show, get, display, detail, full rule | `show` | Full explanation (same as explain) |

3. If **no rule ID** is found, the agent tries several resolution strategies in order:

| Condition | Strategy |
|-----------|----------|
| "how many" + category keyword | Count active rules in that category |
| "list" / "show all" + category keyword | List up to 10 rules in that category |
| "which rules" + ALL_CAPS word | Filter rules by table or column name |
| Active rule in panel → AI classifies SEARCH vs FOLLOWUP | **FOLLOWUP**: answer using full rule context; **SEARCH**: AI catalog search by description |
| No active rule | AI catalog search by description |

4. **Follow-up Q&A** (`_answer_with_context`) uses full context: Excel row fields, YAML pipeline section for the specific rule, sibling rule IDs, custom operation docstrings, and cross-rule dependencies. Up to 20 prior conversation turns are included as history.

5. **Conversation history** — the chat endpoint accepts a `history` array of `{role, content}` pairs (max 20 entries) to support multi-turn dialogue.

### 10 — REST API (`main.py`)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | `{ status, rules_loaded }` |
| `GET` | `/rules` | Lightweight list of all 228 rules (id, category, table, description, severity) |
| `GET` | `/rules/related/{rule_id}` | Up to 4 rules sharing the same category or SAP table |
| `GET` | `/rule/{rule_id}` | Full rule object (see below) |
| `POST` | `/chat` | `{ message, context_rule_id?, history? }` → `{ response, rule_id }` |

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
  "workflow_steps": ["read_dataio", "filter", "select", ...],
  "yaml_reference": "rccomp_103_1.yaml",
  "sources": ["datamart_customer", ...],
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

The `technical_rule` field prefers raw YAML content over Excel logic when a YAML match exists.

### 11 — React Frontend

| Component | Role |
|-----------|------|
| `App.jsx` | Shell — topbar, browser toggle, sidebar toggle, tabbed rule history (pinned + up to 20 recent), `localStorage` persistence |
| `ChatBox.jsx` | Main panel — sends messages to `/api/chat` with conversation history, displays markdown responses, triggers rule load on `rule_id` |
| `RuleBrowser.jsx` | Slide-in panel — full list of all 228 rules, live search by ID / category / table / description, filter chips by quality category |
| `RuleCard.jsx` | Right sidebar — full rule detail, Business Explanation, metadata, Data Sources, Workflow Steps, SAP Fields, Technical Rule (expandable + copy), Rule References (clickable deps), Related Rules grid, Export/Download |
| `FieldTable.jsx` | Nested table inside RuleCard showing mapped SAP fields |
| `Tooltip.jsx` | Accessible hover tooltip used throughout the UI |

**Tab management:**
- **Pinned rules** — appear at the top of the sidebar tab list, persist across reloads, unlimited count.
- **Recent rules** — up to 20, appended as rules are loaded, also persisted in `localStorage`.
- Rules can be pinned/unpinned per-tab; closing moves them out of history.

**Vite proxy** — all frontend API calls use the `/api/` prefix. Vite strips it and forwards to `localhost:8000`:

```
/api/rules         → GET http://localhost:8000/rules
/api/rule/RCCOMP_1 → GET http://localhost:8000/rule/RCCOMP_1
/api/chat          → POST http://localhost:8000/chat
```

---

## Project Structure

```
rule_agent/
├── backend/
│   ├── main.py                  # FastAPI app + all endpoints
│   ├── data_loader.py           # Excel/YAML/custom-ops loading & caching
│   ├── schema_validator.py      # Startup column validation
│   ├── rule_parser.py           # TABLE-FIELD regex extraction
│   ├── sap_mapper.py            # Z11 field label lookup
│   ├── lineage_service.py       # YAML-based lineage index
│   ├── explanation_engine.py    # Azure OpenAI GPT-4o wrapper
│   ├── chat_agent.py            # Intent routing + AI search + follow-up Q&A
│   ├── discover_schema.py       # Utility: print all column names + YAML keys
│   ├── requirements.txt
│   ├── .env                     # Azure OpenAI credentials (not committed)
│   └── data/
│       ├── dim_rules_inventory.xlsx
│       ├── MDG Official Z11.xlsx
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
        ├── App.jsx              # Shell, tabs, pinned rules, localStorage
        └── components/
            ├── ChatBox.jsx
            ├── RuleBrowser.jsx
            ├── RuleCard.jsx
            ├── FieldTable.jsx
            └── Tooltip.jsx
```

---

## Setup

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

Create `rule_agent/backend/.env`:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-key-here
AZURE_OPENAI_DEPLOYMENT=cch-gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-15-preview
```

Or export them in your shell:

```bash
export AZURE_OPENAI_ENDPOINT=https://...
export AZURE_OPENAI_API_KEY=...
```

### 3. Backend

```bash
cd rule_agent/backend
pip install -r requirements.txt
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

Frontend runs at `http://localhost:5173`. The Vite dev server proxies all `/api/*` requests to `localhost:8000` (stripping the `/api` prefix).

---

## Sample Chat Queries

```
# Rule-specific queries
Explain rule RCCOMP_103.1
What SAP fields are used in RCACTI_1?
What table does RCCOMP_106.1 check?
What is the severity of RCCONF_22_7?
Where does rule RCCOMP_108.1 come from?
Workflow of rule RCCOMP_108.1
Show rule RCCONF_22_7

# Catalog search (no rule ID needed)
How many completeness rules are there?
List all conformity rules
Which rules check KNA1?
Find a rule that validates phone numbers
Is there a rule for email validation?

# Follow-up questions (with a rule open in the sidebar)
What does "order block" mean in this context?
Why does this rule check the credit limit?
What other rules run in the same pipeline?
```

---

## Schema Discovery

To inspect all column names before running the app:

```bash
cd rule_agent/backend
python discover_schema.py
```

Prints all column names, the first 3 rows of each Excel sheet, and the top-level keys from every YAML file.

---

## How to Add New YAML Pipelines

1. Drop the `.yaml` file into `backend/data/golden/` (any subdirectory).
2. Ensure it has the structure:
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

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY must be set` | Add both vars to `backend/.env` or export them before starting uvicorn |
| `Rule not found` | Rule may be inactive or non-Customer; check `is_active=1` and `domain=Customer` in the Excel |
| `No lineage columns found` | Expected columns (`module`, `group`, `rule_responsibility`, etc.) are missing from the Excel — lineage will return empty |
| Schema validation fails on startup | Run `python discover_schema.py` to see actual column names; update candidate lists in `data_loader.py` if needed |
| YAML file skipped | YAML syntax error (e.g. unhashable key); check the `[WARNING] Skipping` log line |
| Rule not matched to its YAML | The YAML has no expression literal for the rule ID; add `expression: "'RULE_ID'"` inside the pipeline |
| Port 8000 in use | `lsof -ti:8000 \| xargs kill` (macOS/Linux) or `netstat -ano \| findstr 8000` (Windows) |
| Frontend 404 on `/api/...` | Ensure backend is running on port 8000 before `npm run dev`; all frontend calls use the `/api/` prefix |
| Explanation says "Unable to generate" | Azure OpenAI credentials invalid or deployment name wrong; check the `[ERROR]` log |
| Follow-up Q&A gives wrong answer | The active rule's context window may be truncated; try asking with an explicit rule ID in the message |
| Custom ops not shown in lineage | The YAML `kind` must contain the full `governance_data_quality_processes.custom_operations.` prefix |
