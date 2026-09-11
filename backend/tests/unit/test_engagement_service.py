from pathlib import Path

import pytest

from app.db.engagements import EngagementStore
from app.services.engagement_data import EngagementDataRepository
from app.services.engagement_service import (
    EngagementService,
    UploadRejectedError,
)
from tests.conftest import SYNTHETIC_ROOT


@pytest.fixture
def service(tmp_path: Path) -> EngagementService:
    return EngagementService(
        store=EngagementStore(tmp_path / "db.sqlite"),
        files=EngagementDataRepository(tmp_path / "uploads"),
        fixtures_root=SYNTHETIC_ROOT,
        max_upload_bytes=1_000_000,
    )


def test_create_generates_a_safe_id_and_writes_metadata(service: EngagementService, tmp_path: Path):
    detail = service.create(company_name="Acme Widgets, LLC!", home_state="co", tax_year=2025)

    assert detail.engagement.engagement_id.startswith("acme-widgets-llc-2025-")
    assert detail.engagement.home_state == "CO"
    assert (
        tmp_path / "uploads" / "engagements" / detail.engagement.engagement_id / "engagement.json"
    ).exists()
    assert detail.documents == [] and detail.can_ask is False and detail.can_review is False
    assert service.list_all()[0].engagement.engagement_id == detail.engagement.engagement_id


def test_upload_pdf_is_stored_and_registered_as_uploaded(
    service: EngagementService, tmp_path: Path
):
    eng = service.create(company_name="Acme", home_state="CO", tax_year=2025).engagement

    doc = service.save_upload(
        eng.engagement_id, "Nexus Questionnaire (final).pdf", b"%PDF-1.7", doc_type=None
    )

    assert doc.file_name == "Nexus_Questionnaire_final.pdf"
    assert doc.original_name == "Nexus Questionnaire (final).pdf"
    assert doc.kind == "document" and doc.status == "uploaded"
    assert doc.doc_type == "questionnaire"  # inferred from the name
    assert (
        tmp_path / "uploads" / "engagements" / eng.engagement_id / doc.file_name
    ).read_bytes() == b"%PDF-1.7"


def test_explicit_doc_type_wins_over_inference(service: EngagementService):
    eng = service.create(company_name="Acme", home_state="CO", tax_year=2025).engagement
    doc = service.save_upload(eng.engagement_id, "questionnaire.pdf", b"%PDF", doc_type="other")
    assert doc.doc_type == "other"


def test_csv_upload_is_saved_as_sales_csv_and_validated_immediately(service: EngagementService):
    eng = service.create(company_name="Acme", home_state="CO", tax_year=2025).engagement
    good = b"transaction_id,date,ship_to_state,amount_usd,channel\nT1,2025-01-01,TX,10.00,website\n"

    doc = service.save_upload(eng.engagement_id, "my_sales_export.csv", good, doc_type=None)

    assert doc.file_name == "sales.csv" and doc.kind == "sales_csv" and doc.status == "validated"
    assert doc.original_name == "my_sales_export.csv"


def test_bad_csv_is_kept_but_marked_failed_with_reason(service: EngagementService):
    eng = service.create(company_name="Acme", home_state="CO", tax_year=2025).engagement
    doc = service.save_upload(eng.engagement_id, "sales.csv", b"foo,bar\n1,2\n", doc_type=None)
    assert doc.status == "failed" and doc.error and "transaction_id" in doc.error


@pytest.mark.parametrize("name", ["notes.txt", "data.json", "image.png", "archive.zip", ".pdf"])
def test_unsupported_uploads_are_rejected(service: EngagementService, name: str):
    eng = service.create(company_name="Acme", home_state="CO", tax_year=2025).engagement
    with pytest.raises(UploadRejectedError):
        service.save_upload(eng.engagement_id, name, b"x", doc_type=None)


def test_oversized_upload_is_rejected(service: EngagementService):
    eng = service.create(company_name="Acme", home_state="CO", tax_year=2025).engagement
    with pytest.raises(UploadRejectedError, match="too large"):
        service.save_upload(eng.engagement_id, "big.pdf", b"x" * 1_000_001, doc_type=None)


def test_upload_to_unknown_engagement_fails(service: EngagementService):
    from app.services.engagement_data import EngagementNotFoundError

    with pytest.raises(EngagementNotFoundError):
        service.save_upload("ghost-2025", "a.pdf", b"x", doc_type=None)


def test_load_demo_copies_fixtures_through_the_upload_path(
    service: EngagementService, tmp_path: Path
):
    eng = service.create(company_name="Acme", home_state="CO", tax_year=2025).engagement

    docs = service.load_demo(eng.engagement_id)

    by_name = {d.file_name: d for d in docs}
    assert set(by_name) == {
        "questionnaire.pdf",
        "locations.docx",
        "sales.csv",
        "questionnaire.json",
        "locations.json",
    }
    assert (
        by_name["questionnaire.pdf"].status == "uploaded"
        and by_name["questionnaire.pdf"].doc_type == "questionnaire"
    )
    assert by_name["locations.docx"].doc_type == "locations"
    assert by_name["sales.csv"].status == "validated"
    assert (
        by_name["questionnaire.json"].kind == "questionnaire_json"
        and by_name["questionnaire.json"].status == "validated"
    )
    directory = tmp_path / "uploads" / "engagements" / eng.engagement_id
    assert (directory / "questionnaire.json").exists()
    # The tools can now read the engagement exactly as they read the fixtures.
    data = EngagementDataRepository(tmp_path / "uploads").load(eng.engagement_id)
    assert len(data.transactions) == 3075 and len(data.questionnaire) == 10


def test_readiness_is_backend_owned(service: EngagementService):
    eng = service.create(company_name="Acme", home_state="CO", tax_year=2025).engagement
    service.save_upload(eng.engagement_id, "q.pdf", b"%PDF", doc_type=None)
    assert service.detail(eng.engagement_id).can_ask is False

    service.store.set_document_status(eng.engagement_id, "q.pdf", "indexed", pages=1, chunks=2)

    detail = service.detail(eng.engagement_id)
    assert detail.can_ask is True and detail.can_review is True
    assert detail.documents[0].chunks == 2
