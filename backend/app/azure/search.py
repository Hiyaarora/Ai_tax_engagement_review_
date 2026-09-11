"""Azure AI Search wrapper: index definition, upsert, and hybrid (BM25 + vector) retrieval.

Every query is hard-filtered to one engagement plus the shared reference guidance, so evidence from
one engagement can never surface in another's review.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Self

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

from app.azure.credential import get_credential
from app.azure.embeddings import EMBEDDING_DIMENSIONS
from app.config import Settings
from app.models.evidence import SHARED_ENGAGEMENT_ID, EvidenceChunk, EvidenceHit

VECTOR_FIELD = "content_vector"
_VECTOR_PROFILE = "hnsw-profile"
_VECTOR_ALGORITHM = "hnsw"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_\-]+$")


def build_index_definition(index_name: str) -> SearchIndex:
    """Schema for the evidence index. Changing it requires dropping and re-creating the index."""
    return SearchIndex(
        name=index_name,
        fields=[
            SimpleField(name="chunk_id", type="Edm.String", key=True),
            SimpleField(name="engagement_id", type="Edm.String", filterable=True),
            SimpleField(name="doc_id", type="Edm.String", filterable=True),
            SimpleField(name="doc_type", type="Edm.String", filterable=True),
            SimpleField(name="source_name", type="Edm.String"),
            SimpleField(name="page", type="Edm.Int32", filterable=True),
            SearchableField(name="content", type="Edm.String"),
            SearchField(
                name=VECTOR_FIELD,
                type="Collection(Edm.Single)",
                searchable=True,
                vector_search_dimensions=EMBEDDING_DIMENSIONS,
                vector_search_profile_name=_VECTOR_PROFILE,
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[HnswAlgorithmConfiguration(name=_VECTOR_ALGORITHM)],
            profiles=[
                VectorSearchProfile(
                    name=_VECTOR_PROFILE, algorithm_configuration_name=_VECTOR_ALGORITHM
                )
            ],
        ),
    )


def _validate_id(value: str, what: str) -> str:
    if not _SAFE_ID.match(value):
        raise ValueError(f"{what} contains characters not allowed in a filter: {value!r}")
    return value


class SearchService:
    def __init__(
        self, index_client: SearchIndexClient, index_name: str, endpoint: str = ""
    ) -> None:
        self._index_client = index_client
        self.index_name = index_name
        self.endpoint = endpoint

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            index_client=SearchIndexClient(settings.azure_search_endpoint, get_credential()),
            index_name=settings.azure_search_index_name,
            endpoint=settings.azure_search_endpoint,
        )

    # --- index lifecycle ---------------------------------------------------------------------

    def index_exists(self) -> bool:
        return self.index_name in set(self._index_client.list_index_names())

    def create_index_if_missing(self) -> bool:
        """Create the evidence index. True if created, False if it already existed."""
        if self.index_exists():
            return False
        self._index_client.create_or_update_index(build_index_definition(self.index_name))
        return True

    def search_client(self) -> SearchClient:
        """Document-level client for the configured index."""
        return self._index_client.get_search_client(self.index_name)

    # --- documents ---------------------------------------------------------------------------

    def upsert_chunks(
        self, chunks: Sequence[EvidenceChunk], vectors: Sequence[Sequence[float]]
    ) -> int:
        """Upload chunks with their embeddings (merge-or-upload by chunk_id). Returns count."""
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        if not chunks:
            return 0
        documents = [
            {**chunk.model_dump(), VECTOR_FIELD: list(vector)}
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        results = self.search_client().upload_documents(documents)
        failed = [r.key for r in results if not r.succeeded]
        if failed:
            raise RuntimeError(f"{len(failed)} chunk(s) failed to index: {failed[:5]}")
        return len(documents)

    def delete_document_chunks(self, *, doc_id: str, engagement_id: str) -> int:
        """Remove every chunk of one document so a re-ingest never leaves stale passages behind."""
        _validate_id(doc_id, "doc_id")
        _validate_id(engagement_id, "engagement_id")
        client = self.search_client()
        existing: Any = client.search(
            search_text="*",
            filter=f"engagement_id eq '{engagement_id}' and doc_id eq '{doc_id}'",
            select=["chunk_id"],
        )
        keys = [{"chunk_id": r["chunk_id"]} for r in existing]
        if keys:
            client.delete_documents(keys)
        return len(keys)

    def hybrid_search(
        self,
        query: str,
        query_vector: Sequence[float],
        *,
        engagement_id: str,
        doc_types: Sequence[str] | None = None,
        top_k: int = 5,
    ) -> list[EvidenceHit]:
        """BM25 + vector search, scoped to the engagement and the shared reference guidance."""
        _validate_id(engagement_id, "engagement_id")
        filters = [
            f"(engagement_id eq '{engagement_id}' or engagement_id eq '{SHARED_ENGAGEMENT_ID}')"
        ]
        if doc_types:
            for doc_type in doc_types:
                _validate_id(doc_type, "doc_type")
            filters.append(f"search.in(doc_type, '{','.join(doc_types)}', ',')")

        results: Any = self.search_client().search(
            search_text=query,
            vector_queries=[
                VectorizedQuery(
                    vector=list(query_vector), k_nearest_neighbors=top_k, fields=VECTOR_FIELD
                )
            ],
            filter=" and ".join(filters),
            top=top_k,
            select=["chunk_id", "doc_id", "doc_type", "source_name", "page", "content"],
        )
        return [
            EvidenceHit(
                chunk_id=r["chunk_id"],
                doc_id=r["doc_id"],
                doc_type=r["doc_type"],
                source_name=r["source_name"],
                page=r["page"],
                excerpt=r["content"],
                score=r["@search.score"],
            )
            for r in results
        ]

    def ping(self) -> None:
        """Cheap authenticated call used by the connectivity check. Raises on failure."""
        self._index_client.get_service_statistics()
