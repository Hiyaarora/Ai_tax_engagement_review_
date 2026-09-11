from pathlib import Path

import pytest

from app.db.engagements import (
    DocumentRecord,
    EngagementRecord,
    EngagementStore,
    UnknownDocumentError,
)


@pytest.fixture
def store(tmp_path: Path) -> EngagementStore:
    return EngagementStore(tmp_path / "db.sqlite")


def _engagement(engagement_id: str = "acme-2025-ab12") -> EngagementRecord:
    return EngagementRecord(
        engagement_id=engagement_id,
        company_name="Acme Widgets LLC",
        home_state="CO",
        tax_year=2025,
    )


def test_create_get_and_list_engagements(store: EngagementStore):
    store.create(_engagement())
    store.create(_engagement("beta-2025-cd34"))

    assert (
        store.get("acme-2025-ab12") == store.list_all()[0]
        or store.get("acme-2025-ab12") in store.list_all()
    )
    assert {e.engagement_id for e in store.list_all()} == {"acme-2025-ab12", "beta-2025-cd34"}
    assert store.get("nope") is None
    assert store.get("acme-2025-ab12").created_at is not None  # type: ignore[union-attr]


def test_duplicate_engagement_id_is_rejected(store: EngagementStore):
    store.create(_engagement())
    with pytest.raises(ValueError):
        store.create(_engagement())


def test_upsert_document_replaces_same_file_name_and_resets_status(store: EngagementStore):
    store.create(_engagement())
    doc = DocumentRecord(
        engagement_id="acme-2025-ab12",
        file_name="questionnaire.pdf",
        kind="document",
        doc_type="questionnaire",
    )
    store.upsert_document(doc)
    store.set_document_status("acme-2025-ab12", "questionnaire.pdf", "indexed", pages=2, chunks=3)
    store.upsert_document(doc)  # re-upload

    [saved] = store.list_documents("acme-2025-ab12")
    assert saved.status == "uploaded" and saved.pages is None and saved.chunks is None


def test_document_status_transitions_and_error_are_recorded(store: EngagementStore):
    store.create(_engagement())
    store.upsert_document(
        DocumentRecord(
            engagement_id="acme-2025-ab12", file_name="a.pdf", kind="document", doc_type="other"
        )
    )
    store.set_document_status("acme-2025-ab12", "a.pdf", "processing")
    assert store.list_documents("acme-2025-ab12")[0].status == "processing"
    store.set_document_status("acme-2025-ab12", "a.pdf", "failed", error="DI timeout")
    doc = store.list_documents("acme-2025-ab12")[0]
    assert doc.status == "failed" and doc.error == "DI timeout"
    with pytest.raises(UnknownDocumentError):
        store.set_document_status("acme-2025-ab12", "missing.pdf", "indexed")


def test_documents_are_scoped_per_engagement(store: EngagementStore):
    store.create(_engagement())
    store.create(_engagement("beta-2025-cd34"))
    store.upsert_document(
        DocumentRecord(
            engagement_id="acme-2025-ab12", file_name="a.pdf", kind="document", doc_type="other"
        )
    )
    assert store.list_documents("beta-2025-cd34") == []


def test_meta_key_value(store: EngagementStore):
    assert store.get_meta("reference_status") is None
    store.set_meta("reference_status", "indexed")
    store.set_meta("reference_status", "failed")
    assert store.get_meta("reference_status") == "failed"
