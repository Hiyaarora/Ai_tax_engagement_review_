"""Ingestion pipeline: file -> Document Intelligence -> page-aware chunks -> embeddings -> Search.

Only unstructured documents (PDF, DOCX) are indexed. CSVs are structured client data and are
consumed by the deterministic tools instead (Milestone 3) - vectorising a transaction list would
invite the model to "read" numbers it should be computing.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from app.azure.document_intelligence import DocumentIntelligenceService
from app.azure.embeddings import EmbeddingService
from app.azure.search import SearchService
from app.models.evidence import DocType, EvidenceChunk
from app.services.chunking import chunk_document

INDEXABLE_SUFFIXES = {".pdf", ".docx"}
STRUCTURED_SUFFIXES = {".csv"}


class IngestionResult(BaseModel):
    doc_id: str
    source_name: str
    engagement_id: str
    doc_type: DocType
    pages: int
    chunks_indexed: int


def doc_id_for(path: Path) -> str:
    """Stable, filter-safe document id from a filename (letters, digits, '_' and '-' only)."""
    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", path.stem).strip("_")
    return re.sub(r"_+", "_", cleaned)


class IngestionService:
    embed_batch_size = 16

    def __init__(
        self,
        document_intelligence: DocumentIntelligenceService,
        embeddings: EmbeddingService,
        search: SearchService,
    ) -> None:
        self._di = document_intelligence
        self._embeddings = embeddings
        self._search = search

    def ingest_file(
        self,
        path: Path,
        *,
        engagement_id: str,
        doc_type: DocType,
        doc_id: str | None = None,
    ) -> IngestionResult:
        suffix = path.suffix.lower()
        if suffix in STRUCTURED_SUFFIXES:
            raise ValueError(
                f"{path.name} is structured data; load it for the tools, not the index"
            )
        if suffix not in INDEXABLE_SUFFIXES:
            raise ValueError(
                f"unsupported file type {suffix!r} (expected one of {sorted(INDEXABLE_SUFFIXES)})"
            )

        doc_id = doc_id or doc_id_for(path)
        parsed = self._di.analyze_layout(path.read_bytes(), source_name=path.name)
        chunks = chunk_document(
            parsed, engagement_id=engagement_id, doc_id=doc_id, doc_type=doc_type
        )
        vectors = self._embed_all(chunks)
        self._search.delete_document_chunks(doc_id=doc_id, engagement_id=engagement_id)
        indexed = self._search.upsert_chunks(chunks, vectors)
        return IngestionResult(
            doc_id=doc_id,
            source_name=path.name,
            engagement_id=engagement_id,
            doc_type=doc_type,
            pages=parsed.page_count,
            chunks_indexed=indexed,
        )

    def _embed_all(self, chunks: list[EvidenceChunk]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), self.embed_batch_size):
            batch = chunks[start : start + self.embed_batch_size]
            vectors.extend(self._embeddings.embed([c.content for c in batch]))
        return vectors
