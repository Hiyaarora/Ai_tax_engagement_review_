"""Background document processing: send uploaded documents through the ingestion pipeline.

Runs inside FastAPI ``BackgroundTasks``; progress is written to SQLite so the UI can poll.
Structured files (CSV/JSON) never come here - they were validated at upload.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import BaseModel

from app.db.engagements import EngagementStore
from app.models.evidence import SHARED_ENGAGEMENT_ID
from app.services.engagement_data import EngagementDataRepository
from app.services.ingestion import INDEXABLE_SUFFIXES, IngestionService

log = logging.getLogger(__name__)

_REFERENCE_STATUS = "reference_status"
_REFERENCE_CHUNKS = "reference_chunks"
_REFERENCE_ERROR = "reference_error"


class ReferenceStatus(BaseModel):
    indexed: bool
    status: str  # not_indexed | processing | indexed | failed
    chunks: int = 0
    error: str | None = None


class ProcessingService:
    def __init__(
        self,
        store: EngagementStore,
        files: EngagementDataRepository,
        ingestion: IngestionService,
        fixtures_root: Path,
    ) -> None:
        self._store = store
        self._files = files
        self._ingestion = ingestion
        self._fixtures_root = fixtures_root

    def process_engagement(self, engagement_id: str) -> None:
        """Index every uploaded/failed document. Each document succeeds or fails independently."""
        directory = self._files.directory(engagement_id)
        for doc in self._store.list_documents(engagement_id):
            if doc.kind != "document" or doc.status not in ("uploaded", "failed"):
                continue
            self._store.set_document_status(engagement_id, doc.file_name, "processing")
            try:
                result = self._ingestion.ingest_file(
                    directory / doc.file_name, engagement_id=engagement_id, doc_type=doc.doc_type
                )
            except Exception as exc:  # noqa: BLE001 - report per document, keep going
                log.exception("indexing failed for %s/%s", engagement_id, doc.file_name)
                self._store.set_document_status(
                    engagement_id, doc.file_name, "failed", error=f"{type(exc).__name__}: {exc}"
                )
                continue
            self._store.set_document_status(
                engagement_id,
                doc.file_name,
                "indexed",
                pages=result.pages,
                chunks=result.chunks_indexed,
            )

    def delete_engagement_chunks(self, engagement_id: str) -> int:
        """Remove the engagement's chunks from AI Search (called when it is deleted)."""
        return self._ingestion.delete_engagement(engagement_id)

    # --- shared reference guidance --------------------------------------------------------------

    def reference_status(self) -> ReferenceStatus:
        status = self._store.get_meta(_REFERENCE_STATUS) or "not_indexed"
        return ReferenceStatus(
            indexed=status == "indexed",
            status=status,
            chunks=int(self._store.get_meta(_REFERENCE_CHUNKS) or 0),
            error=self._store.get_meta(_REFERENCE_ERROR) or None,
        )

    def index_reference(self) -> None:
        shared = self._fixtures_root / "shared"
        paths = (
            sorted(p for p in shared.iterdir() if p.suffix.lower() in INDEXABLE_SUFFIXES)
            if shared.is_dir()
            else []
        )
        self._store.set_meta(_REFERENCE_STATUS, "processing")
        self._store.set_meta(_REFERENCE_ERROR, "")
        chunks = 0
        try:
            for path in paths:
                result = self._ingestion.ingest_file(
                    path, engagement_id=SHARED_ENGAGEMENT_ID, doc_type="reference"
                )
                chunks += result.chunks_indexed
        except Exception as exc:  # noqa: BLE001
            log.exception("reference indexing failed")
            self._store.set_meta(_REFERENCE_STATUS, "failed")
            self._store.set_meta(_REFERENCE_ERROR, f"{type(exc).__name__}: {exc}")
            return
        self._store.set_meta(_REFERENCE_STATUS, "indexed")
        self._store.set_meta(_REFERENCE_CHUNKS, str(chunks))
