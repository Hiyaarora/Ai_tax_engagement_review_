"""Citation guard: the agent may only cite what this run actually retrieved or computed.

Rules
* A citation whose ``chunk_id`` was not returned by ``search_evidence`` in this run is removed.
* A surviving citation's ``source_name`` and ``page`` are taken from the retrieved hit, not from
  the model, so a real chunk cannot be attributed to the wrong document or page.
* A quote that does not appear in the retrieved chunk is cleared. Matching ignores case,
  whitespace and punctuation (so a table row quoted without its ``|`` separators still counts),
  but the words must appear contiguously - a paraphrase or invention does not.
* A tool finding attributed to a tool that was not called in this run is removed.
* Flags left with no evidence at all are kept for the human reviewer but reported.

Nothing is ever added - the guard only removes or corrects.
"""

from __future__ import annotations

import re

from app.agent.review_context import ReviewContext
from app.models.review import (
    Citation,
    CitationGuardReport,
    ReviewDraft,
    RiskFlag,
    ToolFinding,
    UnverifiedQuote,
)


def _normalise(text: str) -> str:
    """Lowercase alphanumeric words joined by single spaces; punctuation and pipes dropped."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _guard_citation(
    citation: Citation, ctx: ReviewContext, report: CitationGuardReport
) -> Citation | None:
    hit = ctx.retrieved.get(citation.chunk_id)
    if hit is None:
        report.dropped_citations.append(citation.chunk_id)
        return None
    quote = citation.quote
    if quote and _normalise(quote) not in _normalise(hit.excerpt):
        report.unverified_quotes.append(UnverifiedQuote(chunk_id=citation.chunk_id, quote=quote))
        quote = ""
    if citation.source_name != hit.source_name or citation.page != hit.page:
        report.corrected_citations.append(citation.chunk_id)
    return Citation(chunk_id=hit.chunk_id, source_name=hit.source_name, page=hit.page, quote=quote)


def _guard_finding(
    finding: ToolFinding, ctx: ReviewContext, report: CitationGuardReport
) -> ToolFinding | None:
    if finding.tool not in ctx.tool_calls:
        report.dropped_tool_findings.append(finding.tool)
        return None
    return finding


def guard_citations(
    citations: list[Citation], ctx: ReviewContext, report: CitationGuardReport
) -> list[Citation]:
    """Apply the citation rules to any list of citations (reviews and grounded answers alike)."""
    return [c for c in (_guard_citation(c, ctx, report) for c in citations) if c]


def _guard_flag(flag: RiskFlag, ctx: ReviewContext, report: CitationGuardReport) -> RiskFlag:
    citations = guard_citations(flag.retrieved_evidence, ctx, report)
    findings = [f for f in (_guard_finding(f, ctx, report) for f in flag.tool_findings) if f]
    if not citations and not findings:
        report.flags_without_evidence.append(flag.id)
    return flag.model_copy(update={"retrieved_evidence": citations, "tool_findings": findings})


def apply_citation_guard(
    draft: ReviewDraft, ctx: ReviewContext
) -> tuple[ReviewDraft, CitationGuardReport]:
    report = CitationGuardReport()
    flags = [_guard_flag(flag, ctx, report) for flag in draft.risk_flags]
    return draft.model_copy(update={"risk_flags": flags}), report
