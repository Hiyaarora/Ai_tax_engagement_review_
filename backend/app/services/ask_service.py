"""Grounded question answering over one engagement's indexed documents.

Retrieve (the same engagement-scoped hybrid search the review agent uses) -> answer from those
passages only (strict JSON) -> the same citation guard as reviews. The answer is never persisted;
reviews remain the record. Decision support only - not tax advice.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.citation_guard import guard_citations
from app.agent.review_context import ReviewContext
from app.azure.chat import ChatService
from app.models.evidence import EvidenceHit
from app.models.review import Citation, CitationGuardReport, strict_json_schema
from app.services.engagement_data import EngagementDataRepository
from app.tools.search_evidence import SearchEvidenceArgs, SearchEvidenceTool

ASK_TOP_K = 6

SYSTEM_PROMPT = """You answer a tax professional's question about ONE engagement using ONLY the
passages provided. The data is SYNTHETIC demo data. You provide decision support, not tax advice:
describe what the documents say and what a reviewer should verify; never conclude that tax is owed
or a filing is required.

Rules:
- Use only the passages. If they do not answer the question, say so plainly and set
  found_in_documents to false. Never use outside knowledge to fill gaps.
- Cite every factual statement with the chunk_id of the passage it comes from. A quote must be
  verbatim text from that passage (a backend guard removes anything it cannot verify).
- Distinguish what a client *stated* (questionnaire) from what a document *lists* (locations)
  and from reference guidance (illustrative, not law).
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
    found_in_documents: bool = Field(
        description="False when the passages do not contain the information asked for."
    )


class AskResult(BaseModel):
    engagement_id: str
    question: str
    answer: str
    found_in_documents: bool
    citations: list[Citation]
    passages: list[EvidenceHit]
    citation_guard: CitationGuardReport
    model: str
    disclaimer: str = (
        "Decision support only - not tax advice. Answer generated from SYNTHETIC documents; "
        "verify against the cited passages."
    )


def _render_passages(hits: list[EvidenceHit]) -> str:
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

    def ask(self, engagement_id: str, question: str) -> AskResult:
        question = question.strip()
        if not question:
            raise ValueError("question is empty")
        data = self._engagements.load(engagement_id)  # raises EngagementNotFoundError
        ctx = ReviewContext(engagement_id=engagement_id, data=data)

        hits = self._search.run(
            SearchEvidenceArgs(query=question, top_k=ASK_TOP_K), engagement_id=engagement_id
        )
        ctx.record_hits(hits)
        if not hits:
            return AskResult(
                engagement_id=engagement_id,
                question=question,
                answer=(
                    "No relevant passages were found in this engagement's indexed documents, "
                    "so the question cannot be answered from the evidence."
                ),
                found_in_documents=False,
                citations=[],
                passages=[],
                citation_guard=CitationGuardReport(),
                model=self._chat.deployment,
            )

        user = (
            f"Engagement: {data.company_name} ({engagement_id}), home state {data.home_state}, "
            f"tax year {data.tax_year}.\n\nQuestion: {question}\n\nPassages:\n\n"
            f"{_render_passages(hits)}"
        )
        raw = self._chat.complete_json(
            system=SYSTEM_PROMPT,
            user=user,
            schema_name="ask_draft",
            schema=strict_json_schema(AskDraft),
        )
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
        return AskResult(
            engagement_id=engagement_id,
            question=question,
            answer=draft.answer,
            found_in_documents=draft.found_in_documents,
            citations=citations,
            passages=hits,
            citation_guard=report,
            model=self._chat.deployment,
        )
