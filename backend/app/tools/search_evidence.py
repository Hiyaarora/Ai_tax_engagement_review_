"""``search_evidence`` - the only agent tool that touches Azure AI Search.

The agent supplies the query; the *backend* supplies ``engagement_id`` from the run context, so the
model can never widen retrieval to another engagement. Returned ``chunk_id``s are the citation keys
the citation guard (Milestone 3) checks every flag against.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.azure.embeddings import EmbeddingService
from app.azure.search import SearchService
from app.models.evidence import DocType, EvidenceHit


class SearchEvidenceArgs(BaseModel):
    """Arguments the agent provides. Doubles as the JSON schema pushed to Foundry."""

    model_config = ConfigDict(extra="forbid")  # engagement_id etc. can never be smuggled in

    query: str = Field(
        min_length=1, description="Natural-language question or keywords to look up."
    )
    doc_types: list[DocType] | None = Field(
        default=None,
        description="Restrict to document types, e.g. ['questionnaire', 'reference'].",
    )
    top_k: int = Field(default=5, ge=1, le=10, description="Number of passages to return.")


class SearchEvidenceTool:
    name = "search_evidence"
    description = (
        "Search the engagement's uploaded documents and the shared SALT reference guidance. "
        "Returns passages with chunk_id, source document and page for citation."
    )

    def __init__(self, embeddings: EmbeddingService, search: SearchService) -> None:
        self._embeddings = embeddings
        self._search = search

    def run(self, args: SearchEvidenceArgs, *, engagement_id: str) -> list[EvidenceHit]:
        [query_vector] = self._embeddings.embed([args.query])
        return self._search.hybrid_search(
            args.query,
            query_vector,
            engagement_id=engagement_id,
            doc_types=args.doc_types,
            top_k=args.top_k,
        )
