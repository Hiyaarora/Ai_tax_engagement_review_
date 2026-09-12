from app.models.review import (
    Citation,
    CitationGuardReport,
    ReviewResult,
    RiskFlag,
    TokenUsage,
)
from evals.cases import EvalCase, ExpectedFlag, ForbiddenFlag
from evals.scoring import CaseScore, render_markdown, score_review, summarize


def _flag(fid: str, state: str | None, category: str, level: str, citations: int = 1) -> RiskFlag:
    return RiskFlag(
        id=fid,
        title=fid,
        state=state,
        category=category,  # type: ignore[arg-type]
        risk_level=level,  # type: ignore[arg-type]
        explanation="e",
        retrieved_evidence=[
            Citation(chunk_id=f"c-p1-c{i}", source_name="q.pdf", page=1, quote="q")
            for i in range(citations)
        ],
        tool_findings=[],
        recommended_human_action="a",
    )


def _result(flags: list[RiskFlag], dropped: int = 0, no_evidence: int = 0) -> ReviewResult:
    return ReviewResult(
        review_id="rev_1",
        engagement_id="acme-2025",
        model="gpt-4.1-mini",
        agent_name="A",
        tool_calls=[],
        citation_guard=CitationGuardReport(
            dropped_citations=[f"ghost-{i}" for i in range(dropped)],
            flags_without_evidence=[f"F{i}" for i in range(no_evidence)],
        ),
        usage=TokenUsage(input_tokens=1000, output_tokens=200, turns=3, duration_ms=40000),
        overall_summary="s",
        overall_risk_level="high",
        risk_flags=flags,
        states_reviewed_without_flags=[],
    )


CASE = EvalCase(
    case_id="t",
    description="d",
    expected_flags=[
        ExpectedFlag(
            state="TX",
            categories_any=["physical_presence", "economic_nexus"],
            min_risk_level="high",
        ),
        ExpectedFlag(state=None, categories_any=["data_inconsistency"], min_risk_level="low"),
    ],
    forbidden_flags=[ForbiddenFlag(state="CA"), ForbiddenFlag(state="WA", max_risk_level="medium")],
)


def test_perfect_review_passes_with_full_recall_and_no_violations():
    result = _result(
        [
            _flag("TX-1", "TX", "physical_presence", "high"),
            _flag("INC", None, "data_inconsistency", "medium"),
        ]
    )
    score = score_review(CASE, result)
    assert isinstance(score, CaseScore)
    assert score.expected_hit == 2 and score.missed == []
    assert score.forbidden_hits == [] and score.passed is True
    assert score.citation_validity == 1.0


def test_missed_expectation_and_risk_level_below_minimum_fail():
    result = _result(
        [_flag("TX-1", "TX", "physical_presence", "medium")]
    )  # too low, and no inconsistency
    score = score_review(CASE, result)
    assert score.expected_hit == 0
    assert sorted(score.missed) == [
        "TX:physical_presence|economic_nexus>=high",
        "any:data_inconsistency>=low",
    ]
    assert score.passed is False


def test_forbidden_state_and_tolerated_level():
    result = _result(
        [
            _flag("TX-1", "TX", "economic_nexus", "high"),
            _flag("INC", None, "data_inconsistency", "low"),
            _flag("CA-1", "CA", "economic_nexus", "low"),  # forbidden outright
            _flag("WA-1", "WA", "physical_presence", "medium"),  # tolerated (<= medium)
        ]
    )
    score = score_review(CASE, result)
    assert score.forbidden_hits == ["CA-1 (CA economic_nexus low)"]
    assert score.passed is False


def test_forbidden_level_exceeded_is_a_violation():
    result = _result(
        [
            _flag("TX-1", "TX", "economic_nexus", "high"),
            _flag("INC", None, "data_inconsistency", "low"),
            _flag("WA-1", "WA", "registration", "high"),
        ]
    )
    assert score_review(CASE, result).forbidden_hits == ["WA-1 (WA registration high)"]


def test_citation_validity_and_evidence_counts_come_from_the_guard_report():
    result = _result(
        [_flag("TX-1", "TX", "economic_nexus", "high", citations=3)], dropped=1, no_evidence=1
    )
    score = score_review(CASE, result)
    assert score.citation_validity == 0.75  # 3 kept / (3 kept + 1 dropped)
    assert score.flags_without_evidence == 1
    assert score.usage.input_tokens == 1000


def test_summarize_and_markdown():
    ok = score_review(
        CASE,
        _result(
            [
                _flag("TX-1", "TX", "economic_nexus", "high"),
                _flag("INC", None, "data_inconsistency", "low"),
            ]
        ),
    )
    bad = score_review(CASE, _result([_flag("CA-1", "CA", "economic_nexus", "low")]))
    summary = summarize([ok, bad])
    assert summary.cases == 2 and summary.passed == 1
    assert summary.expected_recall == 0.5  # 2 of 4 expectations hit
    assert summary.forbidden_violations == 1
    assert summary.total_tokens == 2400
    md = render_markdown(summary, [ok, bad])
    assert "| t |" in md and "PASS" in md and "FAIL" in md
    assert "Expected-flag recall" in md
