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
| Microsoft Foundry | Hosted agent `FDprojectAgent` with threads, runs, tracing, evaluations |
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
   - Stage 2 — synthetic data, chunking, index creation, embeddings, `search_evidence`
3. **Agent loop** — deterministic tools, Foundry run/tool dispatch, `ReviewResult` schema, citation guard, SQLite
4. **Review UI** — upload, run review, flags with evidence, human accept/reject
5. **Observability** — OpenTelemetry traces into Foundry
6. **Evaluation** — golden set, groundedness/relevance, flag recall, citation validity
7. **Polish** — docs, demo script
