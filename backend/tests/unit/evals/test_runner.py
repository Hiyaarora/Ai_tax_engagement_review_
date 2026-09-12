import json
from pathlib import Path

from app.models.review import (
    Citation,
    CitationGuardReport,
    ReviewResult,
    RiskFlag,
    TokenUsage,
    ToolFinding,
)
from evals.judges import FlagJudgement, judge_flags, judge_rows
from evals.runner import replay, save_case_result


def _result(case_id: str, flags: list[RiskFlag]) -> ReviewResult:
    return ReviewResult(
        review_id=f"rev_{case_id}",
        engagement_id=f"eval-{case_id}",
        model="gpt-4.1-mini",
        agent_name="A",
        tool_calls=["analyze_sales_by_state"],
        citation_guard=CitationGuardReport(),
        usage=TokenUsage(input_tokens=10, output_tokens=5, turns=1, duration_ms=100),
        overall_summary="s",
        overall_risk_level="high",
        risk_flags=flags,
        states_reviewed_without_flags=["CA"],
    )


def _flag(fid: str, state: str | None, category: str, level: str) -> RiskFlag:
    return RiskFlag(
        id=fid,
        title=f"{state} risk",
        state=state,
        category=category,  # type: ignore[arg-type]
        risk_level=level,  # type: ignore[arg-type]
        explanation="Inventory at a 3PL in Dallas may create presence.",
        retrieved_evidence=[
            Citation(
                chunk_id="q-p1-c1",
                source_name="q.pdf",
                page=1,
                quote="3PL warehouse in Dallas, Texas",
            )
        ],
        tool_findings=[ToolFinding(tool="analyze_sales_by_state", finding="TX revenue 620,000.00")],
        recommended_human_action="a",
    )


def test_save_and_replay_scores_stored_results_offline(tmp_path: Path):
    good = _result(
        "acme-baseline",
        [
            _flag("TX", "TX", "physical_presence", "high"),
            _flag("WA", "WA", "economic_nexus", "medium"),
            _flag("INC", None, "data_inconsistency", "medium"),
        ],
    )
    bad = _result(
        "wa-under-threshold",
        [
            _flag("TX", "TX", "economic_nexus", "high"),
            _flag("WA", "WA", "economic_nexus", "medium"),
        ],
    )
    save_case_result(tmp_path, "acme-baseline", good)
    save_case_result(tmp_path, "wa-under-threshold", bad)

    summary, scores, report = replay(tmp_path)

    assert [s.case_id for s in scores] == ["acme-baseline", "wa-under-threshold"]
    assert scores[0].passed is True
    assert scores[1].passed is False and scores[1].forbidden_hits == [
        "WA (WA economic_nexus medium)"
    ]
    assert summary.cases == 2 and summary.passed == 1
    assert "acme-baseline | PASS" in report and "wa-under-threshold | FAIL" in report
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == report
    assert json.loads((tmp_path / "summary.json").read_text())["cases"] == 2


def test_replay_ignores_unknown_case_files(tmp_path: Path):
    (tmp_path / "not-a-case.result.json").write_text("{}")
    summary, scores, _ = replay(tmp_path)
    assert summary.cases == 0 and scores == []


def test_judge_rows_build_query_context_response_per_flag():
    result = _result("acme-baseline", [_flag("TX", "TX", "physical_presence", "high")])
    [row] = judge_rows("acme-baseline", result)
    assert row["case_id"] == "acme-baseline" and row["flag_id"] == "TX"
    assert "TX" in row["query"]
    assert (
        "3PL warehouse in Dallas, Texas" in row["context"]
        and "TX revenue 620,000.00" in row["context"]
    )
    assert row["response"] == "Inventory at a 3PL in Dallas may create presence."


def test_judge_flags_uses_injected_evaluators_and_averages():
    class _Judge:
        def __init__(self, score: float) -> None:
            self.score = score

        def __call__(self, **kwargs):
            key = "groundedness" if "context" in kwargs else "relevance"
            return {key: self.score, f"{key}_result": "pass" if self.score >= 3 else "fail"}

    rows = judge_rows(
        "acme-baseline",
        _result(
            "acme-baseline",
            [
                _flag("TX", "TX", "physical_presence", "high"),
                _flag("WA", "WA", "economic_nexus", "medium"),
            ],
        ),
    )
    judgements = judge_flags(rows, groundedness=_Judge(4.0), relevance=_Judge(5.0))
    assert [j.flag_id for j in judgements] == ["TX", "WA"]
    assert all(
        isinstance(j, FlagJudgement) and j.groundedness == 4.0 and j.relevance == 5.0
        for j in judgements
    )


def test_judge_rows_prefer_verified_passages_over_model_quotes():
    result = _result("acme-baseline", [_flag("TX", "TX", "physical_presence", "high")])
    passages = {"q-p1-c1": "| inventory_tx | Does the company hold inventory in Texas? | Yes |"}
    [row] = judge_rows("acme-baseline", result, passages=passages)
    assert "| inventory_tx |" in row["context"]  # full passage text
    assert "TX revenue 620,000.00" in row["context"]


def test_passages_sidecar_round_trips(tmp_path: Path):
    from evals.runner import load_case_passages, save_case_passages

    save_case_passages(tmp_path, "acme-baseline", {"q-p1-c1": "full text"})
    assert load_case_passages(tmp_path, "acme-baseline") == {"q-p1-c1": "full text"}
    assert load_case_passages(tmp_path, "missing") == {}
