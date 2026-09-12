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

Docs: [architecture](docs/architecture.md) · [demo script](docs/demo_script.md) ·
[original design spec](docs/superpowers/specs/2026-09-11-fd-tax-review-agent-design.md)

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
| Azure AI Document Intelligence (S0) | `prebuilt-layout` extraction of PDF/DOCX | F0 would analyze only the first 2 pages per document; S0 has no such limit |

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

The UI follows the real workflow: **Create engagement → Upload & process → Ask agent → Run review →
Evidence & findings**. Plain React + CSS, hash routing (`#/e/<engagement_id>/<step>`), no UI library.

- **Home** — create an engagement (company, home state, tax year → SQLite + `data/uploads/<id>/`),
  list engagements with document/review status, and index the shared reference guidance.
- **1 · Upload & process** — upload files one at a time: PDF/DOCX are indexed as citable evidence
  (document type inferred from the name or chosen explicitly); a CSV is the sales export, validated
  on arrival and stored as `sales.csv`. **Process documents** runs Document Intelligence → chunking →
  embeddings → AI Search in a FastAPI `BackgroundTask`; each file shows
  `uploaded → processing → indexed | failed` (with the error) and the page polls until done.
  **Load synthetic demo** pushes the Acme fixtures through the *same* upload/processing path.
- **2 · Ask agent** — grounded question answering (`POST /api/engagements/{id}/ask`, enabled by
  `can_ask`): the backend runs the same engagement-scoped hybrid search the review agent uses,
  asks GPT-4.1-mini to answer *only* from those passages (strict JSON), and passes the citations
  through the same citation guard. The UI shows the answer, the verified citations, the raw
  passages the model was given, and flags answers the documents could not support.
- **3 · Run review** — enabled by the backend's `can_review` (≥1 indexed document); queues the
  agent (`queued → running → done | failed`), lists past reviews with status.
- **4 · Evidence & findings** — summary, citation-guard notes, one card per flag with **Retrieved
  evidence / Computed from client data / AI analysis** kept separate, and the reviewer's decision
  (accept / reject / needs more info) persisted per flag.

Readiness is computed by the backend and returned with every engagement; the UI never guesses.
Structured JSON (questionnaire/locations) is internal fixture data loaded only by the demo button;
the deterministic tools tolerate a missing sales/questionnaire/locations file and say so.

Endpoints: `GET|POST /api/engagements`, `GET /api/engagements/{id}`,
`POST /api/engagements/{id}/documents` (multipart), `POST …/documents/process` (202),
`POST …/demo-files` (202), `GET /api/reference`, `POST /api/reference/index` (202),
`POST /api/engagements/{id}/ask` (409 if not ready), `POST /api/engagements/{id}/reviews` (202, 409 if not ready), `GET /api/engagements/{id}/reviews`,
`GET /api/reviews/{id}` (status + result + decisions), `PATCH /api/reviews/{id}/flags/{flag_id}`.

Run the backend (below), then `cd frontend && npm run dev` and open http://localhost:5173.

## Observability (Milestone 5)

Every pipeline stage is an OpenTelemetry span (`backend/app/observability/tracing.py`); attributes
carry ids and counts only - never document text, answers or secrets. Logs carry the active
`trace=`/`span=` ids so a log line and a trace can be found from each other.

| Span | Where | Key attributes |
|---|---|---|
| `ingest.document` → `di.analyze_layout`, `chunk`, `embed`, `search.delete_stale`, `search.upsert` | ingestion | `engagement_id`, `doc_id`, `doc_type`, `pages`, `chunks`, `count` |
| `search.hybrid` → `embed`, `search.query` | `search_evidence` tool (reviews and questions) | `top_k`, `doc_types`, `hits`, `top_score` |
| `review.run` → `agent.turn`×N, `tool.<name>`, `citation_guard` | review agent | `review_id`, `flags`, `tool_calls`, `turns`, `input_tokens`, `output_tokens`; per turn `response_id`, `tool_calls`; per tool `ok`, `output_bytes` |
| `ask.answer` → `search.hybrid`, `chat.complete` → `tool.<name>` | ask agent | `citations`, `structured_evidence`, `found`, tokens; `chat.complete` has `model`, `turns`, tokens |

Token and latency accounting is persisted with each review (`usage`: input/output tokens, turns,
wall time, per-tool time) and returned with each answer; the UI shows it as one line under the
findings header and under each answer.

**Where traces go** (settings in `.env.example`):

| Mode | When | What you get |
|---|---|---|
| Application Insights → Foundry **Tracing** tab | `APPLICATIONINSIGHTS_CONNECTION_STRING` set, or `OTEL_USE_FOUNDRY_APP_INSIGHTS=true` and an Application Insights resource attached to the Foundry project (portal → project → *Tracing* → connect/create) | end-to-end traces per review/question next to the agent in Foundry; FastAPI/HTTP spans are added automatically by the Azure Monitor distro |
| Console | `OTEL_CONSOLE_EXPORT=true` | spans printed to stdout while developing |
| Local (default) | nothing set | spans created but not exported; zero configuration, nothing breaks |

A representative trace from a real run (synthetic Acme engagement): Document Intelligence 4-10 s
per document, embeddings ~3 s per batch, each AI Search call ~1.5 s (first call includes token
acquisition), the model ~6.6 s for a two-turn grounded answer, the sales tool 4 ms.

## Evaluation (Milestone 6)

```bash
cd backend
uv run python -m scripts.run_evals                 # live: golden set, deterministic scores
uv run python -m scripts.run_evals --judge         # + LLM-judged groundedness / relevance per flag
uv run python -m scripts.run_evals --judge --upload  # + the judge run in Foundry -> Evaluations
uv run python -m scripts.run_evals --replay backend/evals/results/<run>   # offline re-score
```

**Golden set** ([backend/evals/golden_set.jsonl](backend/evals/golden_set.jsonl)) - four controlled
variants of the synthetic Acme engagement, each a small *mutation* of the same dataset with the
flags a correct review must raise (`expected_flags`: state, category, minimum risk) and must not
(`forbidden_flags`, optionally with a tolerated level):

| Case | Change | Must flag | Must not flag |
|---|---|---|---|
| `acme-baseline` | none | TX high, WA ≥ medium, a data inconsistency | CA, NY, FL |
| `tx-registered` | client *is* registered in Texas | WA, inconsistency | TX above medium, CA, NY, FL |
| `wa-under-threshold` | WA sales below thresholds, no remote employees | TX high | WA, any inconsistency, CA, NY, FL |
| `no-inventory-tx` | no inventory or contractor in Texas | TX on economic nexus, WA | CA, NY, FL |

Each case is built as a throwaway engagement through the normal upload → process → review path
(documents generated by the same generator as the demo files), scored, saved to
`backend/evals/results/<timestamp>/`, and deleted again.

**Scores** ([evals/scoring.py](backend/evals/scoring.py), deterministic, offline): expected-flag
recall, forbidden-flag violations, citation validity (kept ÷ kept + dropped, from the citation
guard), flags left without evidence, tokens and wall time per case. `--replay` re-scores saved
results without Azure, so scoring changes are cheap to check.

**Continuous evaluation in Foundry** (`uv run python -m scripts.setup_continuous_eval`): attaches
Foundry's built-in agent evaluators (relevance, coherence, task adherence, intent resolution,
tool-call accuracy) to every completed `FDprojectAgent` response, so the *Evaluation* column of the
Tracing view and the Evaluations tab fill in automatically for reviews run from the UI. One-off
prerequisite: the project's managed identity needs the **Foundry User** role on the project
(`az role assignment create --assignee-object-id <project principalId> --assignee-principal-type
ServicePrincipal --role "Foundry User" --scope <project resource id>`; propagation takes minutes).
Tool-call-only turns are skipped; note that the built-in *task adherence* judge tends to mark a
strict-JSON final response as non-adherent — the golden-set judges below score the content itself.

**LLM judges** ([evals/judges.py](backend/evals/judges.py), optional): Groundedness and Relevance
from the Azure AI Evaluation SDK, keyless on the same GPT-4.1-mini deployment. For every flag the
judge sees the reviewer's question, the evidence the flag actually cites (verified quotes + tool
figures) and the flag's explanation - so a high score means "the analysis is supported by what it
cites", not "the model sounds confident". `--upload` runs the same rows through `evaluate()` so
the run appears in the Foundry **Evaluations** tab next to the traces.

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

## Known limitations

- **Structured questionnaire / locations data is not extracted from the PDF/DOCX.** The
  deterministic tools read `questionnaire.json` / `locations.json`, which today exist only as
  synthetic fixtures (loaded by the demo path). For a user-created engagement the review still
  runs — the tools report "not provided" and the agent works from the indexed documents and the
  sales CSV. Extraction (Document Intelligence custom model or a structured-output pass) is the
  natural next step and was deliberately kept out of the critical path.
- **Single-tenant, no end-user login.** All Azure access is keyless via `DefaultAzureCredential`;
  the web app itself has no authentication (Entra ID via MSAL would be the next step).
- **Synchronous questions, polled reviews, no streaming.** Reviews take 30–60 s; the UI polls.
- **Thresholds are illustrative.** `reference_data/thresholds.json` and the reference guide are
  synthetic and labelled as such; nothing here is a statement of any state's law.
- **One review agent, one prompt agent version at a time.** The agent definition is versioned in
  the repo and pushed with `scripts/sync_agent.py`; there is no A/B of prompt versions.
- **SQLite and local files.** Fine for a single instance; swapping to Postgres/Blob is a
  repository-level change.
- **Latency is measured, not optimised.** Document Intelligence dominates ingestion; each AI Search
  round-trip is ~1.5 s; a review is ~3 model turns. All clients now have timeouts and retry budgets.

## Interview talking points

1. *Why a hosted Foundry agent plus local tools?* The agent, its versions, tracing and evaluations
   live in Foundry; the tools run next to the data. The 2.x Responses-API loop
   (`function_call` → `function_call_output`) is ~60 lines and fully unit-tested with fakes.
2. *How do you stop hallucinated evidence?* The citation guard (chunk must have been retrieved in
   this run; source/page from the index; verbatim quotes; tool findings only from tools that ran)
   plus strict JSON output and Pydantic re-validation. The guard reports what it changed.
3. *Why isn't the CSV in the vector index?* Numbers are computed, not read: pure Python tools,
   attributed as `tool:<name>`, exposed to both the review agent and the ask flow.
4. *How do you know it works?* A golden set of dataset variants with expected/forbidden flags,
   deterministic scoring, LLM-judged groundedness on the actual cited passages, and traces for
   every stage. The eval loop already caught and fixed one evidence gap.
5. *What would production add?* Entra ID login, streaming, structured-data extraction, Postgres,
   a larger golden set, and CI running the offline tests plus a nightly live eval.

## Milestones

1. **Scaffold** — structure, FastAPI, React, config, health endpoint, tests ✅
2. **Provision + ingest + RAG** — AI Search (Basic), Document Intelligence, embeddings deployment, synthetic data, ingestion pipeline, `search_evidence`
   - Stage 1 ✅ Azure resources provisioned; keyless SDK wrappers; connectivity check (`scripts/check_azure.py`, `/api/health/azure`)
   - Stage 2 ✅ synthetic data generator, page-aware chunking, `fd-evidence` index, ingestion pipeline, `search_evidence` tool
3. **Agent loop** — deterministic tools, Foundry agent + tool dispatch, `ReviewResult` schema, citation guard, SQLite, review API ✅
4. **Review UI** — create → upload/process (background) → ask (grounded Q&A) → run review (background) → findings with decisions ✅
5. **Observability** — OpenTelemetry spans per stage, log/trace correlation, token + latency accounting in the UI, Application Insights → Foundry Tracing ✅
6. **Evaluation** — golden set of dataset variants, deterministic recall/violations/citation validity, LLM-judged groundedness & relevance, Foundry Evaluations upload ✅
7. **Polish** — architecture doc, demo script, known limitations, client timeouts ✅
