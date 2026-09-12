"""Engagement lifecycle without Azure: create, accept uploads, validate structured files, readiness.

Public uploads are PDF/DOCX (indexed as evidence) and CSV (the sales export, validated on arrival
and stored as ``sales.csv``). JSON questionnaire/locations files are *internal* structured data:
only the demo loader writes them, through the same validation path.
"""

from __future__ import annotations

import re
import secrets
import shutil
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.db.engagements import (
    DocumentRecord,
    EngagementRecord,
    EngagementStore,
    FileKind,
)
from app.db.reviews import ReviewSummary
from app.models.evidence import DocType
from app.services.engagement_data import (
    LOCATIONS_FILE,
    QUESTIONNAIRE_FILE,
    SALES_FILE,
    EngagementDataRepository,
    EngagementNotFoundError,
    read_locations,
    read_questionnaire,
    read_sales,
)
from app.services.ingestion import INDEXABLE_SUFFIXES

DEMO_ENGAGEMENT_ID = "acme-2025"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_DOC_TYPE_HINTS: dict[str, DocType] = {
    "questionnaire": "questionnaire",
    "location": "locations",
    "reference": "reference",
    "guide": "reference",
}
_STRUCTURED: dict[str, tuple[FileKind, str]] = {
    ".csv": ("sales_csv", SALES_FILE),
    QUESTIONNAIRE_FILE: ("questionnaire_json", QUESTIONNAIRE_FILE),
    LOCATIONS_FILE: ("locations_json", LOCATIONS_FILE),
}


class UploadRejectedError(ValueError):
    pass


class EngagementDetail(BaseModel):
    engagement: EngagementRecord
    documents: list[DocumentRecord]
    can_ask: bool
    can_review: bool
    latest_review: ReviewSummary | None = None


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "engagement"


def safe_file_name(name: str) -> str:
    base = Path(name).name
    stem, suffix = Path(base).stem, Path(base).suffix.lower()
    cleaned = re.sub(r"_+", "_", _UNSAFE.sub("_", stem)).strip("._")
    if not cleaned:
        raise UploadRejectedError(f"invalid file name {name!r}")
    return f"{cleaned}{suffix}"


def infer_doc_type(file_name: str) -> DocType:
    lowered = file_name.lower()
    for hint, doc_type in _DOC_TYPE_HINTS.items():
        if hint in lowered:
            return doc_type
    return "other"


class EngagementService:
    def __init__(
        self,
        store: EngagementStore,
        files: EngagementDataRepository,
        fixtures_root: Path,
        max_upload_bytes: int,
    ) -> None:
        self.store = store
        self._files = files
        self._fixtures_root = fixtures_root
        self._max_upload_bytes = max_upload_bytes

    # --- engagements --------------------------------------------------------------------------

    def create(self, *, company_name: str, home_state: str, tax_year: int) -> EngagementDetail:
        engagement_id = f"{slugify(company_name)}-{tax_year}-{secrets.token_hex(2)}"
        record = EngagementRecord(
            engagement_id=engagement_id,
            company_name=company_name.strip(),
            home_state=home_state.strip().upper(),
            tax_year=tax_year,
        )
        self.store.create(record)
        self._files.write_metadata(
            engagement_id,
            company_name=record.company_name,
            home_state=record.home_state,
            tax_year=record.tax_year,
        )
        return self.detail(engagement_id)

    def get(self, engagement_id: str) -> EngagementRecord:
        record = self.store.get(engagement_id)
        if record is None:
            raise EngagementNotFoundError(engagement_id)
        return record

    def list_all(self) -> list[EngagementDetail]:
        return [self.detail(e.engagement_id) for e in self.store.list_all()]

    def detail(
        self, engagement_id: str, latest_review: ReviewSummary | None = None
    ) -> EngagementDetail:
        engagement = self.get(engagement_id)
        documents = self.store.list_documents(engagement_id)
        indexed = any(d.kind == "document" and d.status == "indexed" for d in documents)
        return EngagementDetail(
            engagement=engagement,
            documents=documents,
            can_ask=indexed,
            can_review=indexed,
            latest_review=latest_review,
        )

    # --- uploads ------------------------------------------------------------------------------

    def save_upload(
        self,
        engagement_id: str,
        original_name: str,
        content: bytes,
        *,
        doc_type: DocType | None,
        allow_internal: bool = False,
    ) -> DocumentRecord:
        self.get(engagement_id)
        directory = self._files.directory(engagement_id)
        if len(content) > self._max_upload_bytes:
            raise UploadRejectedError(
                f"file too large ({len(content)} bytes > {self._max_upload_bytes})"
            )
        cleaned = safe_file_name(original_name)
        suffix = Path(cleaned).suffix.lower()

        if suffix in INDEXABLE_SUFFIXES:
            record = DocumentRecord(
                engagement_id=engagement_id,
                file_name=cleaned,
                original_name=original_name,
                kind="document",
                doc_type=doc_type or infer_doc_type(cleaned),
            )
        elif suffix == ".csv" or (allow_internal and cleaned in _STRUCTURED):
            kind, stored_name = _STRUCTURED[suffix if suffix == ".csv" else cleaned]
            record = DocumentRecord(
                engagement_id=engagement_id,
                file_name=stored_name,
                original_name=original_name,
                kind=kind,
                doc_type="other",
            )
        else:
            raise UploadRejectedError(
                f"unsupported file type {suffix or cleaned!r}; upload PDF, DOCX or CSV"
            )

        (directory / record.file_name).write_bytes(content)
        self.store.upsert_document(record)
        if record.kind != "document":
            self._validate_structured(engagement_id, directory, record)
        return self._document(engagement_id, record.file_name)

    def _validate_structured(
        self, engagement_id: str, directory: Path, record: DocumentRecord
    ) -> None:
        readers = {
            "sales_csv": read_sales,
            "questionnaire_json": read_questionnaire,
            "locations_json": read_locations,
        }
        try:
            readers[record.kind](directory / record.file_name)
            self.store.set_document_status(engagement_id, record.file_name, "validated")
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            self.store.set_document_status(
                engagement_id, record.file_name, "failed", error=_explain(record.kind, exc)
            )

    def _document(self, engagement_id: str, file_name: str) -> DocumentRecord:
        return next(d for d in self.store.list_documents(engagement_id) if d.file_name == file_name)

    # --- demo ---------------------------------------------------------------------------------

    def load_demo(self, engagement_id: str) -> list[DocumentRecord]:
        """Copy the synthetic Acme fixtures in through the normal upload path."""
        source = self._fixtures_root / "engagements" / DEMO_ENGAGEMENT_ID
        records = []
        for path in sorted(source.iterdir()):
            if path.name == "engagement.json" or not path.is_file():
                continue
            records.append(
                self.save_upload(
                    engagement_id,
                    path.name,
                    path.read_bytes(),
                    doc_type=None,
                    allow_internal=True,
                )
            )
        return records

    def shared_reference_paths(self) -> list[Path]:
        shared = self._fixtures_root / "shared"
        if not shared.is_dir():
            return []
        return sorted(p for p in shared.iterdir() if p.suffix.lower() in INDEXABLE_SUFFIXES)

    # --- deletion -----------------------------------------------------------------------------

    def delete(self, engagement_id: str) -> None:
        """Remove the engagement's files and rows. Raises EngagementNotFoundError if unknown."""
        self.get(engagement_id)
        try:
            shutil.rmtree(self._files.directory(engagement_id), ignore_errors=True)
        except EngagementNotFoundError:
            pass  # directory already gone; still remove the rows
        self.store.delete(engagement_id)


def _explain(kind: FileKind, exc: Exception) -> str:
    expected = {
        "sales_csv": "columns transaction_id,date,ship_to_state,amount_usd,channel",
        "questionnaire_json": "a JSON list of {id, section, question, answer, note}",
        "locations_json": "a JSON list of {city, state, site_type, headcount, note}",
    }[kind]
    return f"could not read file (expected {expected}): {str(exc)[:300]}"
