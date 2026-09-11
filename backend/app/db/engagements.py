"""SQLite store for engagements and their uploaded files (stdlib sqlite3, no ORM).

Files themselves live under ``data/uploads/<engagement_id>/``; this store tracks what was uploaded
and where each file is in the pipeline (``uploaded -> processing -> indexed | failed``).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.models.engagement import ENGAGEMENT_ID_PATTERN
from app.models.evidence import DocType

_SCHEMA = """
CREATE TABLE IF NOT EXISTS engagements (
    engagement_id TEXT PRIMARY KEY,
    company_name  TEXT NOT NULL,
    home_state    TEXT NOT NULL,
    tax_year      INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    engagement_id TEXT NOT NULL REFERENCES engagements (engagement_id),
    file_name     TEXT NOT NULL,
    original_name TEXT NOT NULL,
    kind          TEXT NOT NULL,
    doc_type      TEXT NOT NULL,
    status        TEXT NOT NULL,
    pages         INTEGER,
    chunks        INTEGER,
    error         TEXT,
    updated_at    TEXT NOT NULL,
    PRIMARY KEY (engagement_id, file_name)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

FileKind = Literal["document", "sales_csv", "questionnaire_json", "locations_json"]
DocumentStatus = Literal["uploaded", "processing", "indexed", "validated", "failed"]


class UnknownDocumentError(LookupError):
    pass


class EngagementRecord(BaseModel):
    engagement_id: str = Field(pattern=ENGAGEMENT_ID_PATTERN)
    company_name: str = Field(min_length=1, max_length=200)
    home_state: str = Field(pattern=r"^[A-Z]{2}$")
    tax_year: int = Field(ge=2000, le=2100)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DocumentRecord(BaseModel):
    engagement_id: str
    file_name: str
    original_name: str = ""
    kind: FileKind
    doc_type: DocType
    status: DocumentStatus = "uploaded"
    pages: int | None = None
    chunks: int | None = None
    error: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _now() -> str:
    return datetime.now(UTC).isoformat()


class EngagementStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            conn.row_factory = sqlite3.Row
            yield conn
            conn.commit()
        finally:
            conn.close()

    # --- engagements --------------------------------------------------------------------------

    def create(self, engagement: EngagementRecord) -> None:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO engagements VALUES (?, ?, ?, ?, ?)",
                    (
                        engagement.engagement_id,
                        engagement.company_name,
                        engagement.home_state,
                        engagement.tax_year,
                        engagement.created_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"engagement {engagement.engagement_id} already exists") from exc

    def get(self, engagement_id: str) -> EngagementRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM engagements WHERE engagement_id = ?", (engagement_id,)
            ).fetchone()
        return EngagementRecord(**dict(row)) if row else None

    def list_all(self) -> list[EngagementRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM engagements ORDER BY created_at DESC").fetchall()
        return [EngagementRecord(**dict(row)) for row in rows]

    # --- documents ----------------------------------------------------------------------------

    def upsert_document(self, doc: DocumentRecord) -> None:
        """Register an upload. Re-uploading a file name replaces the row and resets its status."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO documents"
                " (engagement_id, file_name, original_name, kind, doc_type, status, pages, chunks,"
                "  error, updated_at)"
                " VALUES (?, ?, ?, ?, ?, 'uploaded', NULL, NULL, NULL, ?)",
                (
                    doc.engagement_id,
                    doc.file_name,
                    doc.original_name or doc.file_name,
                    doc.kind,
                    doc.doc_type,
                    _now(),
                ),
            )

    def set_document_status(
        self,
        engagement_id: str,
        file_name: str,
        status: DocumentStatus,
        *,
        pages: int | None = None,
        chunks: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE documents SET status = ?, pages = ?, chunks = ?, error = ?, updated_at = ?"
                " WHERE engagement_id = ? AND file_name = ?",
                (status, pages, chunks, error, _now(), engagement_id, file_name),
            )
            if cursor.rowcount == 0:
                raise UnknownDocumentError(f"{engagement_id}/{file_name}")

    def list_documents(self, engagement_id: str) -> list[DocumentRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE engagement_id = ? ORDER BY file_name",
                (engagement_id,),
            ).fetchall()
        return [DocumentRecord(**dict(row)) for row in rows]

    # --- meta (small global flags, e.g. shared reference index status) --------------------------

    def get_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
