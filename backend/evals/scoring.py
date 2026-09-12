"""Deterministic scoring of a review against a golden case.

No LLM judge here: the golden set says which (state, category, minimum risk) flags a correct
review must raise and which it must not, and the citation guard already tells us how many of the
agent's citations were real. That gives recall, false-flag violations, citation validity and cost
per review - reproducible, offline, and cheap to run on every prompt change.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.review import ReviewResult, RiskFlag, TokenUsage
from evals.cases import EvalCase, ExpectedFlag, ForbiddenFlag

_LEVEL = {"low": 0, "medium": 1, "high": 2}


def _describe_expected(e: ExpectedFlag) -> str:
    cats = "|".join(e.categories_any) if e.categories_any else "any"
    return f"{e.state or 'any'}:{cats}>={e.min_risk_level}"


def _matches_expected(flag: RiskFlag, e: ExpectedFlag) -> bool:
    if e.state is not None and flag.state != e.state:
        return False
    if e.categories_any and flag.category not in e.categories_any:
        return False
    return _LEVEL[flag.risk_level] >= _LEVEL[e.min_risk_level]


def _violates_forbidden(flag: RiskFlag, f: ForbiddenFlag) -> bool:
    if f.state is not None and flag.state != f.state:
        return False
    if f.state is None and not f.categories_any:
        return False  # a bare "state: null" would forbid everything; require a category
    if f.categories_any and flag.category not in f.categories_any:
        return False
    if f.max_risk_level is not None and _LEVEL[flag.risk_level] <= _LEVEL[f.max_risk_level]:
        return False
    return True


class CaseScore(BaseModel):
    case_id: str
    review_id: str
    flags_total: int
    expected_total: int
    expected_hit: int
    missed: list[str] = Field(default_factory=list)
    forbidden_hits: list[str] = Field(default_factory=list)
    citation_validity: float = Field(description="kept citations / (kept + dropped); 1.0 if none")
    flags_without_evidence: int
    usage: TokenUsage
    passed: bool


def score_review(case: EvalCase, result: ReviewResult) -> CaseScore:
    flags = result.risk_flags
    missed = [
        _describe_expected(e)
        for e in case.expected_flags
        if not any(_matches_expected(flag, e) for flag in flags)
    ]
    forbidden_hits = [
        f"{flag.id} ({flag.state or 'any'} {flag.category} {flag.risk_level})"
        for flag in flags
        if any(_violates_forbidden(flag, f) for f in case.forbidden_flags)
    ]
    kept = sum(len(flag.retrieved_evidence) for flag in flags)
    dropped = len(result.citation_guard.dropped_citations)
    validity = kept / (kept + dropped) if (kept + dropped) else 1.0
    return CaseScore(
        case_id=case.case_id,
        review_id=result.review_id,
        flags_total=len(flags),
        expected_total=len(case.expected_flags),
        expected_hit=len(case.expected_flags) - len(missed),
        missed=missed,
        forbidden_hits=forbidden_hits,
        citation_validity=validity,
        flags_without_evidence=len(result.citation_guard.flags_without_evidence),
        usage=result.usage,
        passed=not missed and not forbidden_hits,
    )


class Summary(BaseModel):
    cases: int
    passed: int
    expected_recall: float
    forbidden_violations: int
    mean_citation_validity: float
    total_tokens: int
    mean_duration_ms: int


def summarize(scores: list[CaseScore]) -> Summary:
    expected_total = sum(s.expected_total for s in scores)
    expected_hit = sum(s.expected_hit for s in scores)
    return Summary(
        cases=len(scores),
        passed=sum(1 for s in scores if s.passed),
        expected_recall=(expected_hit / expected_total) if expected_total else 1.0,
        forbidden_violations=sum(len(s.forbidden_hits) for s in scores),
        mean_citation_validity=(
            sum(s.citation_validity for s in scores) / len(scores) if scores else 1.0
        ),
        total_tokens=sum(s.usage.input_tokens + s.usage.output_tokens for s in scores),
        mean_duration_ms=(
            int(sum(s.usage.duration_ms for s in scores) / len(scores)) if scores else 0
        ),
    )


def render_markdown(summary: Summary, scores: list[CaseScore]) -> str:
    lines = [
        "# Review evaluation",
        "",
        f"- Cases passed: **{summary.passed} / {summary.cases}**",
        f"- Expected-flag recall: **{summary.expected_recall:.0%}**",
        f"- Forbidden-flag violations: **{summary.forbidden_violations}**",
        f"- Mean citation validity: **{summary.mean_citation_validity:.0%}**",
        f"- Tokens (all cases): {summary.total_tokens:,}"
        f" · mean duration {summary.mean_duration_ms / 1000:.0f} s",
        "",
        "| Case | Result | Flags | Expected hit | Missed | Forbidden hits"
        " | Citation validity | Tokens | Time |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in scores:
        lines.append(
            f"| {s.case_id} | {'PASS' if s.passed else 'FAIL'} | {s.flags_total} | "
            f"{s.expected_hit}/{s.expected_total} | {', '.join(s.missed) or '-'} | "
            f"{', '.join(s.forbidden_hits) or '-'} | {s.citation_validity:.0%} | "
            f"{s.usage.input_tokens + s.usage.output_tokens:,} |"
            f" {s.usage.duration_ms / 1000:.0f} s |"
        )
    return "\n".join(lines) + "\n"
