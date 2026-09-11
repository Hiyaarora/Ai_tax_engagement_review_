import json

from app.agent.review_context import ReviewContext
from app.agent.tool_registry import ToolRegistry, build_registry
from app.models.evidence import EvidenceHit
from app.tools.search_evidence import SearchEvidenceTool


class _FakeEmbeddings:
    def embed(self, texts):
        return [[0.1] for _ in texts]


class _FakeSearch:
    def __init__(self) -> None:
        self.engagement_ids: list[str] = []

    def hybrid_search(self, query, query_vector, *, engagement_id, doc_types=None, top_k=5):
        self.engagement_ids.append(engagement_id)
        return [
            EvidenceHit(
                chunk_id="questionnaire-p1-c1",
                doc_id="questionnaire",
                doc_type="questionnaire",
                source_name="questionnaire.pdf",
                page=1,
                excerpt="inventory_tx | Does the company hold inventory in Texas? | Yes",
                score=0.03,
            )
        ]


def _registry() -> tuple[ToolRegistry, _FakeSearch]:
    search = _FakeSearch()
    tool = SearchEvidenceTool(embeddings=_FakeEmbeddings(), search=search)  # type: ignore[arg-type]
    return build_registry(search_evidence=tool), search


def test_definitions_expose_five_function_tools_without_engagement_id(acme_data):
    registry, _ = _registry()
    defs = registry.definitions()
    assert [d["name"] for d in defs] == [
        "search_evidence",
        "analyze_sales_by_state",
        "check_economic_nexus_thresholds",
        "get_employee_locations",
        "get_questionnaire_answers",
    ]
    for d in defs:
        assert d["type"] == "function"
        assert d["description"]
        assert "engagement_id" not in d["parameters"].get("properties", {})
        assert d["parameters"]["additionalProperties"] is False


def test_dispatch_runs_deterministic_tool_on_context_engagement(acme_data):
    registry, _ = _registry()
    ctx = ReviewContext(engagement_id="acme-2025", data=acme_data)

    out = json.loads(registry.dispatch("analyze_sales_by_state", "{}", ctx))

    tx = next(s for s in out["states"] if s["state"] == "TX")
    assert tx["revenue_usd"] == 620000.0 and tx["transactions"] == 900
    assert out["source"] == "tool:analyze_sales_by_state"
    assert ctx.tool_calls == ["analyze_sales_by_state"]


def test_dispatch_search_evidence_uses_context_engagement_and_records_retrieved(acme_data):
    registry, search = _registry()
    ctx = ReviewContext(engagement_id="acme-2025", data=acme_data)

    out = json.loads(registry.dispatch("search_evidence", '{"query": "inventory in Texas"}', ctx))

    assert search.engagement_ids == ["acme-2025"]
    assert out["hits"][0]["chunk_id"] == "questionnaire-p1-c1"
    assert out["source"] == "retrieved_evidence"
    assert set(ctx.retrieved) == {"questionnaire-p1-c1"}
    assert ctx.retrieved["questionnaire-p1-c1"].page == 1


def test_model_cannot_override_engagement_via_arguments(acme_data):
    registry, search = _registry()
    ctx = ReviewContext(engagement_id="acme-2025", data=acme_data)

    out = json.loads(
        registry.dispatch("search_evidence", '{"query": "x", "engagement_id": "other-2025"}', ctx)
    )

    assert "error" in out
    assert search.engagement_ids == []  # rejected before any search ran


def test_invalid_arguments_return_an_error_payload_not_an_exception(acme_data):
    registry, _ = _registry()
    ctx = ReviewContext(engagement_id="acme-2025", data=acme_data)
    out = json.loads(registry.dispatch("search_evidence", '{"query": "", "top_k": 99}', ctx))
    assert "error" in out and "query" in out["error"]
    out = json.loads(registry.dispatch("get_questionnaire_answers", "not json", ctx))
    assert "error" in out


def test_unknown_tool_returns_error(acme_data):
    registry, _ = _registry()
    ctx = ReviewContext(engagement_id="acme-2025", data=acme_data)
    out = json.loads(registry.dispatch("delete_everything", "{}", ctx))
    assert out["error"].startswith("unknown tool")


def test_questionnaire_section_argument_is_passed_through(acme_data):
    registry, _ = _registry()
    ctx = ReviewContext(engagement_id="acme-2025", data=acme_data)
    out = json.loads(
        registry.dispatch("get_questionnaire_answers", '{"section": "Registrations"}', ctx)
    )
    assert {a["id"] for a in out["answers"]} == {
        "registered_co",
        "registered_tx",
        "registered_other",
        "marketplace",
    }
