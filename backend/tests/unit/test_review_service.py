import json
from pathlib import Path

import pytest

from app.agent.foundry_agent import AgentRunOutcome
from app.agent.tool_registry import build_registry
from app.db.reviews import ReviewRepository
from app.models.evidence import EvidenceHit
from app.services.engagement_data import EngagementDataRepository, EngagementNotFoundError
from app.services.review_service import ReviewParseError, ReviewService
from app.tools.search_evidence import SearchEvidenceTool
from tests.conftest import SYNTHETIC_ROOT


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
                excerpt=(
                    "inventory_tx | Does the company hold inventory in Texas? | Yes | 3PL in Dallas"
                ),
                score=0.03,
            )
        ]


class _ScriptedRunner:
    """Calls the tools the real agent would, then returns a scripted draft."""

    agent_name = "FDprojectAgent"

    def __init__(self, final_text: str, tool_calls: list[tuple[str, str]]) -> None:
        self._final_text = final_text
        self._tool_calls = tool_calls
        self.prompts: list[str] = []

    def run(self, user_input, dispatch):
        self.prompts.append(user_input)
        for name, args in self._tool_calls:
            dispatch(name, args)
        return AgentRunOutcome(output_text=self._final_text, model="gpt-4.1-mini", turns=3)


def _draft_json(**overrides) -> str:
    draft = {
        "overall_summary": "Texas physical presence without registration.",
        "overall_risk_level": "high",
        "risk_flags": [
            {
                "id": "TX-PHYSICAL-PRESENCE",
                "title": "Inventory in Texas, not registered",
                "state": "TX",
                "category": "physical_presence",
                "risk_level": "high",
                "explanation": "Client holds inventory at a Dallas 3PL.",
                "retrieved_evidence": [
                    {
                        "chunk_id": "questionnaire-p1-c1",
                        "source_name": "questionnaire.pdf",
                        "page": 1,
                        "quote": "3PL in Dallas",
                    },
                    {
                        "chunk_id": "fabricated-p9-c9",
                        "source_name": "audit.pdf",
                        "page": 9,
                        "quote": "nope",
                    },
                ],
                "tool_findings": [
                    {"tool": "analyze_sales_by_state", "finding": "TX revenue 620,000.00"},
                    {"tool": "get_bank_statements", "finding": "invented"},
                ],
                "recommended_human_action": "Confirm registration status.",
            }
        ],
        "states_reviewed_without_flags": ["CA", "NY"],
    }
    draft.update(overrides)
    return json.dumps(draft)


def _service(tmp_path: Path, runner) -> ReviewService:
    registry = build_registry(
        search_evidence=SearchEvidenceTool(embeddings=_FakeEmbeddings(), search=_FakeSearch())  # type: ignore[arg-type]
    )
    return ReviewService(
        engagements=EngagementDataRepository(SYNTHETIC_ROOT),
        registry=registry,
        runner=runner,  # type: ignore[arg-type]
        reviews=ReviewRepository(tmp_path / "reviews.db"),
    )


def test_run_review_end_to_end_with_scripted_agent(tmp_path: Path):
    runner = _ScriptedRunner(
        _draft_json(),
        [("analyze_sales_by_state", "{}"), ("search_evidence", '{"query": "inventory in Texas"}')],
    )
    service = _service(tmp_path, runner)

    result = service.run_review("acme-2025")

    assert result.engagement_id == "acme-2025"
    assert result.review_id.startswith("rev_")
    assert result.model == "gpt-4.1-mini" and result.agent_name == "FDprojectAgent"
    assert result.tool_calls == ["analyze_sales_by_state", "search_evidence"]
    assert result.human_review_required is True
    flag = result.risk_flags[0]
    assert [c.chunk_id for c in flag.retrieved_evidence] == ["questionnaire-p1-c1"]
    assert [f.tool for f in flag.tool_findings] == ["analyze_sales_by_state"]
    assert result.citation_guard.dropped_citations == ["fabricated-p9-c9"]
    assert result.citation_guard.dropped_tool_findings == ["get_bank_statements"]
    # persisted
    assert service.get_review(result.review_id) == result
    assert [s.review_id for s in service.list_reviews("acme-2025")] == [result.review_id]


def test_prompt_contains_engagement_facts_but_no_instructions_to_bypass_tools(tmp_path: Path):
    runner = _ScriptedRunner(_draft_json(), [])
    _service(tmp_path, runner).run_review("acme-2025")
    prompt = runner.prompts[0]
    assert "acme-2025" in prompt and "Acme Widgets LLC" in prompt and "2025" in prompt
    assert "questionnaire.pdf" in prompt and "locations.docx" in prompt
    assert "SYNTHETIC" in prompt


def test_fenced_json_is_accepted(tmp_path: Path):
    runner = _ScriptedRunner("```json\n" + _draft_json() + "\n```", [])
    assert _service(tmp_path, runner).run_review("acme-2025").overall_risk_level == "high"


def test_invalid_draft_raises_parse_error_and_persists_nothing(tmp_path: Path):
    runner = _ScriptedRunner('{"overall_summary": "missing everything"}', [])
    service = _service(tmp_path, runner)
    with pytest.raises(ReviewParseError):
        service.run_review("acme-2025")
    assert service.list_reviews("acme-2025") == []


def test_unknown_engagement_is_rejected_before_calling_the_agent(tmp_path: Path):
    runner = _ScriptedRunner(_draft_json(), [])
    with pytest.raises(EngagementNotFoundError):
        _service(tmp_path, runner).run_review("../etc")
    assert runner.prompts == []
