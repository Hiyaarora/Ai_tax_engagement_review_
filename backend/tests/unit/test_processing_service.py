from pathlib import Path

import pytest

from app.db.engagements import EngagementStore
from app.services.engagement_data import EngagementDataRepository
from app.services.engagement_service import EngagementService
from app.services.ingestion import IngestionResult
from app.services.processing_service import ProcessingService
from tests.conftest import SYNTHETIC_ROOT


class _FakeIngestion:
    def __init__(self, fail_on: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.fail_on = fail_on or set()

    def ingest_file(
        self, path: Path, *, engagement_id: str, doc_type: str, doc_id: str | None = None
    ):
        self.calls.append((path.name, engagement_id, doc_type))
        if path.name in self.fail_on:
            raise RuntimeError(f"DI exploded on {path.name}")
        return IngestionResult(
            doc_id=path.stem,
            source_name=path.name,
            engagement_id=engagement_id,
            doc_type=doc_type,  # type: ignore[arg-type]
            pages=2,
            chunks_indexed=3,
        )


@pytest.fixture
def setup(tmp_path: Path):
    store = EngagementStore(tmp_path / "db.sqlite")
    files = EngagementDataRepository(tmp_path / "uploads")
    engagements = EngagementService(
        store=store, files=files, fixtures_root=SYNTHETIC_ROOT, max_upload_bytes=10**7
    )
    ingestion = _FakeIngestion()
    processing = ProcessingService(
        store=store, files=files, ingestion=ingestion, fixtures_root=SYNTHETIC_ROOT
    )  # type: ignore[arg-type]
    return engagements, processing, ingestion, store


def test_process_indexes_uploaded_documents_and_records_pages_and_chunks(setup):
    engagements, processing, ingestion, store = setup
    eng = engagements.create(company_name="Acme", home_state="CO", tax_year=2025).engagement
    engagements.save_upload(eng.engagement_id, "questionnaire.pdf", b"%PDF", doc_type=None)
    engagements.save_upload(
        eng.engagement_id,
        "sales.csv",
        b"transaction_id,date,ship_to_state,amount_usd,channel\n",
        doc_type=None,
    )

    processing.process_engagement(eng.engagement_id)

    assert ingestion.calls == [("questionnaire.pdf", eng.engagement_id, "questionnaire")]
    docs = {d.file_name: d for d in store.list_documents(eng.engagement_id)}
    assert docs["questionnaire.pdf"].status == "indexed"
    assert docs["questionnaire.pdf"].pages == 2 and docs["questionnaire.pdf"].chunks == 3
    assert docs["sales.csv"].status == "validated"  # structured files are never sent to DI


def test_failed_document_is_marked_failed_and_others_still_process(setup):
    engagements, processing, ingestion, store = setup
    ingestion.fail_on = {"bad.pdf"}
    eng = engagements.create(company_name="Acme", home_state="CO", tax_year=2025).engagement
    engagements.save_upload(eng.engagement_id, "bad.pdf", b"%PDF", doc_type=None)
    engagements.save_upload(eng.engagement_id, "good.pdf", b"%PDF", doc_type=None)

    processing.process_engagement(eng.engagement_id)

    docs = {d.file_name: d for d in store.list_documents(eng.engagement_id)}
    assert docs["bad.pdf"].status == "failed" and "DI exploded" in (docs["bad.pdf"].error or "")
    assert docs["good.pdf"].status == "indexed"


def test_process_skips_already_indexed_documents_but_retries_failed_ones(setup):
    engagements, processing, ingestion, store = setup
    eng = engagements.create(company_name="Acme", home_state="CO", tax_year=2025).engagement
    engagements.save_upload(eng.engagement_id, "a.pdf", b"%PDF", doc_type=None)
    engagements.save_upload(eng.engagement_id, "b.pdf", b"%PDF", doc_type=None)
    store.set_document_status(eng.engagement_id, "a.pdf", "indexed", pages=1, chunks=1)
    store.set_document_status(eng.engagement_id, "b.pdf", "failed", error="earlier")

    processing.process_engagement(eng.engagement_id)

    assert [c[0] for c in ingestion.calls] == ["b.pdf"]


def test_index_reference_guidance_sets_meta_status(setup):
    _, processing, ingestion, store = setup
    processing.index_reference()
    assert [c[1:] for c in ingestion.calls] == [("shared", "reference")]
    assert store.get_meta("reference_status") == "indexed"
    assert processing.reference_status().indexed is True

    ingestion.fail_on = {"salt_reference_guide.pdf"}
    processing.index_reference()
    assert processing.reference_status().indexed is False
    assert "DI exploded" in (processing.reference_status().error or "")
