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
backend/    FastAPI app (uv, Python 3.12)   app/api, services, agent, tools, db, observability; tests/
frontend/   React + TypeScript (Vite, npm)  src/api, components, types.ts
data/       synthetic/ demo files (committed); uploads + SQLite (ignored)
docs/       design specs and architecture notes
```

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- Azure CLI (`az login`) — needed from Milestone 2 onward for `DefaultAzureCredential`

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

## Milestones

1. **Scaffold** — structure, FastAPI, React, config, health endpoint, tests ✅
2. **Provision + ingest + RAG** — AI Search (Basic), Document Intelligence, embeddings deployment, synthetic data, ingestion pipeline, `search_evidence`
3. **Agent loop** — deterministic tools, Foundry run/tool dispatch, `ReviewResult` schema, citation guard, SQLite
4. **Review UI** — upload, run review, flags with evidence, human accept/reject
5. **Observability** — OpenTelemetry traces into Foundry
6. **Evaluation** — golden set, groundedness/relevance, flag recall, citation validity
7. **Polish** — docs, demo script
