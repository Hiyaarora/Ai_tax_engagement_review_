# F&D Tax Engagement Review Agent

A production-style AI application that reviews a **synthetic** tax engagement — SALT nexus questionnaire,
sales transaction CSV, employee/office locations, and reference guidance — and produces potential tax-risk
flags, each backed by cited evidence and deterministic analysis of the client data.

> **Decision support only — not tax advice.** All data is synthetic. Every finding requires review by a
> qualified professional. The system never fabricates evidence and always separates retrieved facts,
> computed results, and AI analysis.

## What it demonstrates

| Capability | How |
|---|---|
| Microsoft Foundry | Hosted prompt agent `FDprojectAgent` (definition versioned in repo), run via the Responses API |
| Azure OpenAI | GPT-4.1-mini (reasoning) + text-embedding-3-small (embeddings) |
| RAG | Azure AI Search hybrid (BM25 + vector) retrieval scoped per engagement |
| Document Intelligence | `prebuilt-layout` extraction of PDFs/DOCX with page-level citations |
| AI agent + Python tools | One agent; deterministic Python function tools executed by the backend |
| FastAPI / React | REST backend, minimal TypeScript UI with human-in-the-loop decisions |
| Evaluation & observability | Golden-set evals in Foundry; OpenTelemetry traces per run |

## Architecture

```
React (Vite) ──REST/JSON──> FastAPI ──┬──> Azure Document Intelligence   (ingestion)
                                      ├──> Azure AI Search (fd-evidence)  (RAG)
                                      └──> Microsoft Foundry project
                                             • GPT-4.1-mini, text-embedding-3-small
                                             • Agent FDprojectAgent + function tools
                                             • Tracing / Evaluations
```

Full design: [docs/superpowers/specs/2026-09-11-fd-tax-review-agent-design.md](docs/superpowers/specs/2026-09-11-fd-tax-review-agent-design.md)

## Repository layout

```
backend/    FastAPI app (uv, Python 3.12)   app/api, azure (SDK wrappers), services, agent, tools, db; scripts/; tests/
frontend/   React + TypeScript (Vite, npm)  src/api, components, types.ts
data/       synthetic/ demo files (committed); uploads + SQLite (ignored)
docs/       design specs and architecture notes
```

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) — `DefaultAzureCredential` uses your `az login` identity locally

## Azure prerequisites

All Azure access is **keyless**. Nothing in this repo or in `.env` is a secret; the code authenticates
with `DefaultAzureCredential`, which resolves to your Azure CLI login locally and to Managed Identity
when deployed.

| Resource | Purpose | Notes |
|---|---|---|
| Microsoft Foundry project | GPT-4.1-mini (`FOUNDRY_CHAT_DEPLOYMENT`) and text-embedding-3-small (`FOUNDRY_EMBEDDING_DEPLOYMENT`); hosts the agent | Inference uses the resource-level `{resource}/openai/v1` route, derived from the project endpoint (the project-scoped route returns 404) |
| Azure AI Search (Basic) | RAG index `fd-evidence` (hybrid BM25 + vector) | RBAC auth — enable *Role-based access control* on the service |
| Azure AI Document Intelligence (F0) | `prebuilt-layout` extraction of PDF/DOCX | F0 analyzes only the first 2 pages per document; synthetic demo files are kept to ≤2 pages |

Your signed-in identity needs these roles (portal → resource → *Access control (IAM)*):

- Foundry project / AI Services resource: **Azure AI User** (or Cognitive Services OpenAI User)
- Azure AI Search: **Search Index Data Contributor** + **Search Service Contributor**
- Document Intelligence: **Cognitive Services User**

### Local authentication

```bash
az login
az account show          # confirm the subscription that owns the resources above
```

Then copy `.env.example` to `backend/.env` and fill in the endpoints (no keys). Verify connectivity:

```bash
cd backend
uv run python -m scripts.check_azure
```

```
[ OK ] document_intelligence  ok (412 ms)
[ OK ] embeddings             ok (903 ms)
[ OK ] search                 ok (188 ms)
```

The same check is exposed at `GET /api/health/azure` (makes real Azure calls; `GET /api/health` stays
offline and only reports what is configured).

## Synthetic data, index and ingestion (Milestone 2)

All demo data is generated from one Python dataset ([backend/scripts/synthetic/dataset.py](backend/scripts/synthetic/dataset.py))
into one directory per engagement, so the numbers in every file agree and are deliberately
inconsistent with each other in ways a reviewer should catch (Texas inventory but no Texas
registration; "no employees outside Colorado" vs. two remote employees in Washington; Texas and
Washington over the illustrative thresholds; California/New York under them).

```
data/synthetic/engagements/acme-2025/
  questionnaire.pdf, locations.docx      indexed as citable evidence (Document Intelligence -> AI Search)
  sales.csv, questionnaire.json,
  locations.json, engagement.json        structured system-of-record data for the deterministic tools
data/synthetic/shared/salt_reference_guide.pdf   indexed under engagement_id "shared"
```

```bash
cd backend
uv run python -m scripts.synthetic.generate       # -> data/synthetic/*.pdf, *.docx, *.csv (committed)
uv run python -m scripts.create_search_index      # idempotent; schema in app/azure/search.py
uv run python -m scripts.ingest_documents --demo  # DI layout -> chunks -> embeddings -> AI Search
uv run python -m scripts.query_evidence "Does the company hold inventory in Texas?"
```

Every query is filtered to `engagement_id eq '<id>' or engagement_id eq 'shared'`. The sales CSV
and JSON files are **not** indexed - they feed the deterministic tools.

Pipeline notes: Document Intelligence lists table cells both as paragraphs and inside tables, so the
parser drops paragraphs that fall inside a table span and keeps DI's reading order; chunks never
cross a page and default to ~1000 characters so one questionnaire section is one citable chunk.

## The review agent (Milestone 3)

```bash
cd backend
uv run python -m scripts.sync_agent           # push instructions + tool schemas + output schema to FDprojectAgent
uv run python -m scripts.run_review           # live review of acme-2025 (~40-60 s), or:
curl -X POST http://localhost:8000/api/engagements/acme-2025/reviews
```

How a review runs (`app/services/review_service.py`):

```
ReviewContext(engagement_id, data)            # backend fixes the engagement; the model never chooses it
   └─ FoundryAgentRunner.run(prompt, dispatch) # OpenAI Responses API + agent_reference (Foundry 2.x)
        ├─ function_call  ─► ToolRegistry.dispatch(name, args, ctx) ─► function_call_output
        │     search_evidence            (RAG; records retrieved chunk_ids in ctx)
        │     analyze_sales_by_state     (deterministic)
        │     check_economic_nexus_thresholds
        │     get_employee_locations
        │     get_questionnaire_answers
        └─ final JSON  ─► ReviewDraft (strict schema, Pydantic) ─► citation guard ─► ReviewResult ─► SQLite
```

Guarantees worth knowing:

- **Tool contracts are the schema.** Each tool's Pydantic args model (`extra="forbid"`) generates the JSON
  schema pushed to Foundry *and* validates arguments at dispatch. `engagement_id` is not an argument.
- **The LLM never does arithmetic.** Totals, counts and threshold comparisons come from `app/tools/*`
  (pure Python, unit-tested against the committed synthetic data) and are attributed as `tool:<name>`.
- **Citation guard** (`app/agent/citation_guard.py`): a citation survives only if its `chunk_id` was
  retrieved in *this* run; source/page are overwritten from the index; quotes not found verbatim in
  the chunk are cleared; tool findings from tools not called are dropped. Nothing is ever added.
  The `citation_guard` block in every result says exactly what was changed.
- **Structured output**: `ReviewDraft` is enforced by Foundry (strict JSON schema) and re-validated with
  Pydantic. `human_review_required` is a `Literal[True]` the model cannot set.

Endpoints: `GET /api/engagements`, `POST /api/engagements/{id}/reviews` (synchronous, returns
`ReviewResult`), `GET /api/engagements/{id}/reviews`, `GET /api/reviews/{review_id}` (result +
decisions), `PATCH /api/reviews/{review_id}/flags/{flag_id}` (reviewer decision).

## The review UI (Milestone 4)

Two pages, plain React + CSS, hash routing, no UI library:

- **Engagements** (`#/`) — company, home state, indexed documents, past reviews, and **Run review**
  (synchronous; the page shows progress for the 30–90 s the agent takes, then opens the result).
- **Review** (`#/reviews/<id>`) — overall summary and risk level, the citation-guard notes, and one
  card per flag. Each card keeps the three kinds of information in separate, colour-coded regions —
  **Retrieved evidence** (source, page, `chunk_id`, verbatim quote), **Computed from client data**
  (tool name + figure) and **AI analysis** — followed by the recommended human action and the
  reviewer's decision (**Accept / Reject / Needs more info** + note), persisted via
  `PATCH /api/reviews/{id}/flags/{flag_id}`. A counter shows how many flags still need a decision.

Run the backend (below), then `cd frontend && npm run dev` and open http://localhost:5173.

## Run the backend

```bash
cd backend
cp ../.env.example .env        # optional for Milestone 1; endpoints can stay empty
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

- Health: http://localhost:8000/api/health
- OpenAPI docs: http://localhost:8000/docs

Tests and lint:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy
```

## Run the frontend

```bash
cd frontend
npm install
npm run dev                    # http://localhost:5173, proxies /api -> http://localhost:8000
```

Tests, typecheck/build, lint:

```bash
npm test
npm run build
npm run lint
```

## Configuration and secrets

All configuration is read from environment variables via `pydantic-settings` (`backend/app/config.py`).
`.env.example` lists every key. **No API keys anywhere** — every Azure call authenticates with
`DefaultAzureCredential` (your `az login` identity locally, Managed Identity when deployed).
Azure SDK clients are wrapped once in `backend/app/azure/` (`credential.py`, `document_intelligence.py`,
`embeddings.py`, `search.py`, `connectivity.py`); business logic never constructs SDK clients directly.

## Milestones

1. **Scaffold** — structure, FastAPI, React, config, health endpoint, tests ✅
2. **Provision + ingest + RAG** — AI Search (Basic), Document Intelligence, embeddings deployment, synthetic data, ingestion pipeline, `search_evidence`
   - Stage 1 ✅ Azure resources provisioned; keyless SDK wrappers; connectivity check (`scripts/check_azure.py`, `/api/health/azure`)
   - Stage 2 ✅ synthetic data generator, page-aware chunking, `fd-evidence` index, ingestion pipeline, `search_evidence` tool
3. **Agent loop** — deterministic tools, Foundry agent + tool dispatch, `ReviewResult` schema, citation guard, SQLite, review API ✅
4. **Review UI** — engagements, run review, flag cards with evidence separated from analysis, human decisions ✅
5. **Observability** — OpenTelemetry traces into Foundry
6. **Evaluation** — golden set, groundedness/relevance, flag recall, citation validity
7. **Polish** — docs, demo script
