"""Grounded question answering over one engagement's indexed documents and structured sales data.

Retrieve (the same engagement-scoped hybrid search the review agent uses) -> answer from those
passages only (strict JSON) -> the same citation guard as reviews. When a question needs figures
from ``sales.csv`` the model may call the existing ``analyze_sales_by_state`` tool - the same
registry entry and dispatch the review agent uses - and must attribute those figures as tool
findings, which the guard keeps only if the tool actually ran. The answer is never persisted;
reviews remain the record. Decision support only - not tax advice.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.citation_guard import guard_citations, guard_tool_findings
from app.agent.review_context import ReviewContext
from app.agent.tool_registry import build_registry
from app.azure.chat import ChatService
from app.models.evidence import EvidenceHit
from app.models.review import (
    Citation,
    CitationGuardReport,
    TokenUsage,
    ToolFinding,
    strict_json_schema,
)
from app.observability.tracing import span
from app.services.engagement_data import SALES_FILE, EngagementDataRepository
from app.tools.search_evidence import SearchEvidenceArgs, SearchEvidenceTool

ASK_TOP_K = 6

# The only deterministic tool the ask flow exposes, and the client file it is computed from.
ASK_TOOLS: dict[str, str] = {"analyze_sales_by_state": SALES_FILE}

SYSTEM_PROMPT = """You answer a tax professional's question about ONE engagement using ONLY the
passages provided and, when the question needs sales figures, the analyze_sales_by_state tool.
The data is SYNTHETIC demo data. You provide decision support, not tax advice: describe what the
documents and data say and what a reviewer should verify; never conclude that tax is owed or a
filing is required.

Rules:
- Use only the passages and tool results. If neither answers the question, say so plainly and set
  found_in_documents to false. Never use outside knowledge to fill gaps.
- Sales figures (revenue, transaction counts, shares, thresholds) come ONLY from the
  analyze_sales_by_state tool, which is computed from the client's sales.csv. Call it whenever the
  question involves sales; never estimate or recall figures. Report each figure you use in
  tool_findings, attributed to the tool, exactly as returned (e.g. "TX revenue 620,000.00").
  A backend guard drops tool findings when the tool was not called.
- Cite every document-based statement with the chunk_id of the passage it comes from. A quote must
  be verbatim text from that passage. Never cite sales figures as a document passage.
- Distinguish what a client *stated* (questionnaire) from what a document *lists* (locations),
  from reference guidance (illustrative, not law), and from computed sales data (sales.csv).
- Be concise: two to five sentences, then stop."""


class AskError(RuntimeError):
    pass


class _DraftCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(description="chunk_id of the passage, exactly as labelled.")
    quote: str = Field(description="Short verbatim excerpt (<= 300 chars) from that passage.")


class AskDraft(BaseModel):
    """What the model must return."""

    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[_DraftCitation]
    tool_findings: list[ToolFinding] = Field(
        description="Figures taken from tool results, attributed to the tool. Empty if none."
    )
    found_in_documents: bool = Field(
        description="False when neither the passages nor the tool results contain the answer."
    )


class StructuredEvidence(BaseModel):
    """A figure computed from a client data file - shown separately from document citations."""

    tool: str
    source: str = Field(description="The client file the tool computed from, e.g. sales.csv.")
    finding: str


class AskResult(BaseModel):
    engagement_id: str
    question: str
    answer: str
    found_in_documents: bool
    citations: list[Citation]
    structured_evidence: list[StructuredEvidence] = Field(default_factory=list)
    tool_calls: list[str] = Field(default_factory=list)
    passages: list[EvidenceHit]
    citation_guard: CitationGuardReport
    usage: TokenUsage = Field(default_factory=TokenUsage)
    model: str
    disclaimer: str = (
        "Decision support only - not tax advice. Answer generated from SYNTHETIC documents and "
        "data; verify against the cited passages and figures."
    )


def _render_passages(hits: list[EvidenceHit]) -> str:
    if not hits:
        return "(no relevant passages were retrieved)"
    blocks = []
    for hit in hits:
        blocks.append(
            f"[chunk_id: {hit.chunk_id}] {hit.source_name}, page {hit.page} ({hit.doc_type})\n"
            f"{hit.excerpt}"
        )
    return "\n\n---\n\n".join(blocks)


class AskService:
    def __init__(
        self,
        engagements: EngagementDataRepository,
        search_evidence: SearchEvidenceTool,
        chat: ChatService,
    ) -> None:
        self._engagements = engagements
        self._search = search_evidence
        self._chat = chat
        # Same registry (definitions + dispatch + validation) as the review agent; the ask flow
        # only offers the model the sales tool.
        self._registry = build_registry(search_evidence=search_evidence)
        self._tool_definitions = [
            {**definition, "strict": True}
            for definition in self._registry.definitions()
            if definition["name"] in ASK_TOOLS
        ]

    def ask(self, engagement_id: str, question: str) -> AskResult:
        question = question.strip()
        if not question:
            raise ValueError("question is empty")
        started = time.perf_counter()
        with span("ask.answer", engagement_id=engagement_id) as current:
            result = self._ask(engagement_id, question, ctx_started=started)
            current.set_attribute("citations", len(result.citations))
            current.set_attribute("structured_evidence", len(result.structured_evidence))
            current.set_attribute("found", result.found_in_documents)
            current.set_attribute("input_tokens", result.usage.input_tokens)
            current.set_attribute("output_tokens", result.usage.output_tokens)
            return result

    def _ask(self, engagement_id: str, question: str, *, ctx_started: float) -> AskResult:
        data = self._engagements.load(engagement_id)  # raises EngagementNotFoundError
        ctx = ReviewContext(engagement_id=engagement_id, data=data)

        hits = self._search.run(
            SearchEvidenceArgs(query=question, top_k=ASK_TOP_K), engagement_id=engagement_id
        )
        ctx.record_hits(hits)

        user = (
            f"Engagement: {data.company_name} ({engagement_id}), home state {data.home_state}, "
            f"tax year {data.tax_year}.\n\nQuestion: {question}\n\nPassages:\n\n"
            f"{_render_passages(hits)}"
        )
        completion = self._chat.complete_json(
            system=SYSTEM_PROMPT,
            user=user,
            schema_name="ask_draft",
            schema=strict_json_schema(AskDraft),
            tools=self._tool_definitions,
            dispatch=lambda name, args: self._registry.dispatch(name, args, ctx),
        )
        raw = completion.text if hasattr(completion, "text") else str(completion)
        try:
            draft = AskDraft.model_validate_json(raw)
        except ValidationError as exc:
            raise AskError(f"model output did not match AskDraft: {exc}") from exc

        report = CitationGuardReport()
        by_id = {hit.chunk_id: hit for hit in hits}
        candidates = [
            Citation(
                chunk_id=c.chunk_id,
                source_name=by_id[c.chunk_id].source_name if c.chunk_id in by_id else "",
                page=by_id[c.chunk_id].page if c.chunk_id in by_id else 0,
                quote=c.quote,
            )
            for c in draft.citations
        ]
        citations = guard_citations(candidates, ctx, report)
        findings = guard_tool_findings(draft.tool_findings, ctx, report)
        structured = [
            StructuredEvidence(tool=f.tool, source=ASK_TOOLS.get(f.tool, f.tool), finding=f.finding)
            for f in findings
        ]
        # Backend-owned: an answer counts as found only if verified evidence survived the guard
        # (a document citation or a tool figure). The model's own flag is advisory at most.
        supported = bool(citations or structured)
        return AskResult(
            engagement_id=engagement_id,
            question=question,
            answer=draft.answer,
            found_in_documents=supported,
            citations=citations,
            structured_evidence=structured,
            tool_calls=list(ctx.tool_calls),
            passages=hits,
            citation_guard=report,
            usage=TokenUsage(
                input_tokens=getattr(completion, "input_tokens", 0),
                output_tokens=getattr(completion, "output_tokens", 0),
                turns=getattr(completion, "turns", 0),
                duration_ms=int((time.perf_counter() - ctx_started) * 1000),
                tool_durations_ms=ctx.tool_durations_ms(),
            ),
            model=self._chat.deployment,
        )
