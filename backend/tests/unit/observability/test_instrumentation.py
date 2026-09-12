"""Spans and usage accounting emitted by the real pipeline code, with Azure clients faked."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.agent.foundry_agent import FoundryAgentRunner
from app.agent.review_context import ReviewContext
from app.agent.tool_registry import build_registry
from app.azure.chat import ChatService
from app.azure.document_intelligence import ParsedBlock, ParsedDocument, ParsedPage
from app.db.reviews import ReviewRepository
from app.models.evidence import EvidenceHit
from app.observability.tracing import use_in_memory_tracing
from app.services.engagement_data import EngagementDataRepository
from app.services.ingestion import IngestionService
from app.services.review_service import ReviewService
from app.tools.search_evidence import SearchEvidenceTool
from tests.conftest import SYNTHETIC_ROOT


@pytest.fixture
def spans() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    use_in_memory_tracing(exporter)
    yield exporter
    exporter.clear()


def _names(exporter: InMemorySpanExporter) -> list[str]:
    return [s.name for s in exporter.get_finished_spans()]


def _by_name(exporter: InMemorySpanExporter, name: str):
    return next(s for s in exporter.get_finished_spans() if s.name == name)


class _FakeEmbeddings:
    def embed(self, texts):
        return [[0.1] for _ in texts]


class _FakeSearch:
    def hybrid_search(self, query, query_vector, *, engagement_id, doc_types=None, top_k=5):
        return [
            EvidenceHit(
                chunk_id="questionnaire-p1-c1",
                doc_id="questionnaire",
                doc_type="questionnaire",
                source_name="questionnaire.pdf",
                page=1,
                excerpt="inventory in Texas? Yes",
                score=0.031,
            )
        ]

    def delete_document_chunks(self, *, doc_id, engagement_id):
        return 0

    def upsert_chunks(self, chunks, vectors):
        return len(chunks)


class _FakeDI:
    def analyze_layout(self, content, *, source_name):
        return ParsedDocument(
            source_name=source_name,
            model_id="prebuilt-layout",
            pages=[ParsedPage(page_number=1, blocks=[ParsedBlock(kind="paragraph", text="hello")])],
        )


# --- search_evidence tool -------------------------------------------------------------------------


def test_search_evidence_emits_search_hybrid_span_with_hit_stats(spans, acme_data):
    from app.tools.search_evidence import SearchEvidenceArgs

    tool = SearchEvidenceTool(embeddings=_FakeEmbeddings(), search=_FakeSearch())  # type: ignore[arg-type]
    tool.run(SearchEvidenceArgs(query="inventory in Texas", top_k=3), engagement_id="acme-2025")

    s = _by_name(spans, "search.hybrid")
    assert s.attributes["engagement_id"] == "acme-2025"
    assert s.attributes["top_k"] == 3 and s.attributes["hits"] == 1
    assert s.attributes["top_score"] == pytest.approx(0.031)
    assert "query" not in s.attributes  # never the question text
    children = [
        c.name
        for c in spans.get_finished_spans()
        if c.parent and c.parent.span_id == s.context.span_id
    ]
    assert children == ["embed", "search.query"]


# --- tool dispatch --------------------------------------------------------------------------------


def test_dispatch_emits_tool_span_and_records_timing(spans, acme_data):
    registry = build_registry(search_evidence=None)
    ctx = ReviewContext(engagement_id="acme-2025", data=acme_data)

    registry.dispatch("analyze_sales_by_state", "{}", ctx)
    registry.dispatch("no_such_tool", "{}", ctx)

    ok = _by_name(spans, "tool.analyze_sales_by_state")
    assert ok.attributes["engagement_id"] == "acme-2025" and ok.attributes["ok"] is True
    assert ok.attributes["output_bytes"] > 0
    bad = _by_name(spans, "tool.no_such_tool")
    assert bad.attributes["ok"] is False
    assert [name for name, _ in ctx.tool_timings] == ["analyze_sales_by_state"]
    assert ctx.tool_timings[0][1] >= 0


# --- ingestion ------------------------------------------------------------------------------------


def test_ingest_emits_document_span_with_stage_children(spans, tmp_path: Path):
    pdf = tmp_path / "q.pdf"
    pdf.write_bytes(b"%PDF")
    service = IngestionService(
        document_intelligence=_FakeDI(), embeddings=_FakeEmbeddings(), search=_FakeSearch()
    )  # type: ignore[arg-type]

    service.ingest_file(pdf, engagement_id="acme-2025", doc_type="questionnaire")

    names = _names(spans)
    assert names[-1] == "ingest.document"  # parent finishes last
    assert {"chunk", "embed", "search.delete_stale", "search.upsert"} <= set(names)
    doc = _by_name(spans, "ingest.document")
    assert doc.attributes["doc_id"] == "q" and doc.attributes["pages"] == 1
    assert doc.attributes["chunks"] == 1
    assert _by_name(spans, "embed").attributes["count"] == 1
    children = [
        s
        for s in spans.get_finished_spans()
        if s.parent and s.parent.span_id == doc.context.span_id
    ]
    assert len(children) >= 4


# --- chat / model calls ---------------------------------------------------------------------------


def _resp(rid, output, text="", usage=(10, 5)):
    return SimpleNamespace(
        id=rid,
        status="completed",
        output=output,
        output_text=text,
        model="gpt-4.1-mini",
        usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1]),
    )


def test_chat_complete_returns_usage_and_emits_span(spans):
    scripted = [
        _resp(
            "r1", [SimpleNamespace(type="function_call", call_id="c1", name="t", arguments="{}")]
        ),
        _resp("r2", [], text='{"answer": "x"}', usage=(20, 7)),
    ]
    responses = SimpleNamespace(create=lambda **kw: scripted.pop(0))
    chat = ChatService(
        client=SimpleNamespace(responses=responses, base_url="x"), deployment="gpt-4.1-mini"
    )  # type: ignore[arg-type]

    result = chat.complete_json(
        system="s", user="u", schema_name="n", schema={}, tools=[{}], dispatch=lambda n, a: "{}"
    )

    assert result.text == '{"answer": "x"}'
    assert (result.input_tokens, result.output_tokens, result.turns) == (30, 12, 2)
    s = _by_name(spans, "chat.complete")
    assert s.attributes["model"] == "gpt-4.1-mini"
    assert s.attributes["turns"] == 2 and s.attributes["input_tokens"] == 30
    assert s.attributes["output_tokens"] == 12
    assert s.attributes["gen_ai.operation.name"] == "chat"
    assert s.attributes["gen_ai.usage.input_tokens"] == 30
    assert s.attributes["gen_ai.response.model"] == "gpt-4.1-mini"


def test_agent_runner_emits_a_span_per_turn(spans):
    scripted = [
        _resp(
            "r1", [SimpleNamespace(type="function_call", call_id="c1", name="t", arguments="{}")]
        ),
        _resp("r2", [], text="{}"),
    ]
    responses = SimpleNamespace(create=lambda **kw: scripted.pop(0))
    runner = FoundryAgentRunner(SimpleNamespace(responses=responses), agent_name="A")  # type: ignore[arg-type]

    runner.run("go", lambda n, a: "{}")

    turns = [s for s in spans.get_finished_spans() if s.name == "agent.turn"]
    assert [t.attributes["turn"] for t in turns] == [1, 2]
    assert turns[0].attributes["tool_calls"] == 1 and turns[1].attributes["tool_calls"] == 0
    assert turns[0].attributes["response_id"] == "r1"


# --- review: spans + usage persisted --------------------------------------------------------------


class _ScriptedRunner:
    agent_name = "FDprojectAgent"

    def run(self, user_input, dispatch):
        from app.agent.foundry_agent import AgentRunOutcome

        dispatch("analyze_sales_by_state", "{}")
        dispatch("search_evidence", json.dumps({"query": "inventory in Texas"}))
        return AgentRunOutcome(
            output_text=json.dumps(
                {
                    "overall_summary": "s",
                    "overall_risk_level": "high",
                    "risk_flags": [
                        {
                            "id": "TX-1",
                            "title": "t",
                            "state": "TX",
                            "category": "physical_presence",
                            "risk_level": "high",
                            "explanation": "e",
                            "retrieved_evidence": [
                                {
                                    "chunk_id": "questionnaire-p1-c1",
                                    "source_name": "questionnaire.pdf",
                                    "page": 1,
                                    "quote": "Yes",
                                },
                                {
                                    "chunk_id": "ghost-p1-c0",
                                    "source_name": "g.pdf",
                                    "page": 1,
                                    "quote": "x",
                                },
                            ],
                            "tool_findings": [
                                {
                                    "tool": "analyze_sales_by_state",
                                    "finding": "TX revenue 620,000.00",
                                }
                            ],
                            "recommended_human_action": "a",
                        }
                    ],
                    "states_reviewed_without_flags": ["CA"],
                }
            ),
            model="gpt-4.1-mini",
            turns=3,
            input_tokens=1200,
            output_tokens=340,
        )


def test_review_emits_review_span_and_persists_usage(spans, tmp_path: Path):
    registry = build_registry(
        search_evidence=SearchEvidenceTool(embeddings=_FakeEmbeddings(), search=_FakeSearch())  # type: ignore[arg-type]
    )
    service = ReviewService(
        engagements=EngagementDataRepository(SYNTHETIC_ROOT),
        registry=registry,
        runner=_ScriptedRunner(),  # type: ignore[arg-type]
        reviews=ReviewRepository(tmp_path / "r.db"),
    )

    result = service.run_review("acme-2025")

    assert result.usage.input_tokens == 1200 and result.usage.output_tokens == 340
    assert result.usage.turns == 3 and result.usage.duration_ms >= 0
    assert set(result.usage.tool_durations_ms) == {"analyze_sales_by_state", "search_evidence"}
    assert service.get_review(result.review_id).usage == result.usage  # type: ignore[union-attr]

    review_span = _by_name(spans, "review.run")
    assert review_span.attributes["review_id"] == result.review_id
    assert review_span.attributes["flags"] == 1 and review_span.attributes["input_tokens"] == 1200
    guard = _by_name(spans, "citation_guard")
    assert guard.attributes["dropped_citations"] == 1
    assert {"tool.analyze_sales_by_state", "tool.search_evidence", "search.hybrid"} <= set(
        _names(spans)
    )
