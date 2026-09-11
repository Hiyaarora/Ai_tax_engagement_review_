from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_engagement_service,
    get_processing_service,
    get_review_service,
)
from app.db.engagements import EngagementStore
from app.db.reviews import ReviewRepository
from app.main import create_app
from app.services.engagement_data import EngagementDataRepository
from app.services.engagement_service import EngagementService
from app.services.processing_service import ReferenceStatus
from tests.conftest import SYNTHETIC_ROOT


class _FakeProcessing:
    def __init__(self) -> None:
        self.processed: list[str] = []
        self.reference_runs = 0

    def process_engagement(self, engagement_id: str) -> None:
        self.processed.append(engagement_id)

    def index_reference(self) -> None:
        self.reference_runs += 1

    def reference_status(self) -> ReferenceStatus:
        return ReferenceStatus(
            indexed=self.reference_runs > 0,
            status="indexed" if self.reference_runs else "not_indexed",
        )


class _FakeReviews:
    def __init__(self, repo: ReviewRepository) -> None:
        self.repo = repo
        self.executed: list[str] = []

    def start_review(self, engagement_id: str) -> str:
        self.repo.create_pending("rev_new", engagement_id)
        return "rev_new"

    def execute_review(self, review_id: str) -> None:
        self.executed.append(review_id)

    def get_record(self, review_id: str):
        return self.repo.get_record(review_id)

    def list_reviews(self, engagement_id: str):
        return self.repo.list_for_engagement(engagement_id)

    def list_decisions(self, review_id: str):
        return self.repo.list_decisions(review_id)

    def decide_flag(self, decision):
        self.repo.save_decision(decision)
        return decision


@pytest.fixture
def api(tmp_path: Path):
    store = EngagementStore(tmp_path / "db.sqlite")
    engagements = EngagementService(
        store=store,
        files=EngagementDataRepository(tmp_path / "uploads"),
        fixtures_root=SYNTHETIC_ROOT,
        max_upload_bytes=1_000_000,
    )
    processing = _FakeProcessing()
    reviews = _FakeReviews(ReviewRepository(tmp_path / "db.sqlite"))
    app = create_app()
    app.dependency_overrides[get_engagement_service] = lambda: engagements
    app.dependency_overrides[get_processing_service] = lambda: processing
    app.dependency_overrides[get_review_service] = lambda: reviews
    return TestClient(app), engagements, processing, reviews


def _create(client: TestClient) -> str:
    r = client.post(
        "/api/engagements",
        json={"company_name": "Acme Widgets LLC", "home_state": "co", "tax_year": 2025},
    )
    assert r.status_code == 201, r.text
    return r.json()["engagement"]["engagement_id"]


def test_create_and_list_engagements(api):
    client, *_ = api
    engagement_id = _create(client)

    listed = client.get("/api/engagements").json()
    assert [e["engagement"]["engagement_id"] for e in listed] == [engagement_id]
    detail = client.get(f"/api/engagements/{engagement_id}").json()
    assert detail["engagement"]["home_state"] == "CO"
    assert (
        detail["can_ask"] is False and detail["can_review"] is False and detail["documents"] == []
    )
    assert client.get("/api/engagements/nope-2025").status_code == 404


def test_create_validates_input(api):
    client, *_ = api
    assert (
        client.post(
            "/api/engagements", json={"company_name": "", "home_state": "CO", "tax_year": 2025}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/engagements",
            json={"company_name": "A", "home_state": "Colorado", "tax_year": 2025},
        ).status_code
        == 422
    )


def test_upload_document_and_csv(api):
    client, *_ = api
    engagement_id = _create(client)

    r = client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("Nexus Questionnaire.pdf", b"%PDF-1.7", "application/pdf")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["file_name"] == "Nexus_Questionnaire.pdf"
    assert r.json()["doc_type"] == "questionnaire" and r.json()["status"] == "uploaded"

    r = client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={
            "file": (
                "export.csv",
                b"transaction_id,date,ship_to_state,amount_usd,channel\n",
                "text/csv",
            )
        },
    )
    assert (
        r.status_code == 201
        and r.json()["file_name"] == "sales.csv"
        and r.json()["status"] == "validated"
    )

    r = client.post(
        f"/api/engagements/{engagement_id}/documents",
        data={"doc_type": "other"},
        files={"file": ("questionnaire.pdf", b"%PDF-1.7", "application/pdf")},
    )
    assert r.json()["doc_type"] == "other"  # explicit doc_type wins

    docs = client.get(f"/api/engagements/{engagement_id}").json()["documents"]
    assert sorted(d["file_name"] for d in docs) == [
        "Nexus_Questionnaire.pdf",
        "questionnaire.pdf",
        "sales.csv",
    ]


def test_upload_rejections(api):
    client, *_ = api
    engagement_id = _create(client)
    r = client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400 and "PDF, DOCX or CSV" in r.json()["detail"]
    r = client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("questionnaire.json", b"[]", "application/json")},
    )
    assert r.status_code == 400  # JSON is internal, not a user upload
    r = client.post(
        "/api/engagements/ghost-2025/documents",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 404


def test_process_queues_background_indexing(api):
    client, _, processing, _ = api
    engagement_id = _create(client)
    client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )

    r = client.post(f"/api/engagements/{engagement_id}/documents/process")

    assert r.status_code == 202
    assert r.json() == {"engagement_id": engagement_id, "queued": 1}
    assert processing.processed == [engagement_id]  # BackgroundTasks ran after the response


def test_process_with_nothing_to_do_is_still_202_with_zero_queued(api):
    client, _, processing, _ = api
    engagement_id = _create(client)
    r = client.post(f"/api/engagements/{engagement_id}/documents/process")
    assert r.status_code == 202 and r.json()["queued"] == 0
    assert processing.processed == []


def test_load_demo_uploads_fixtures_and_queues_processing(api):
    client, _, processing, _ = api
    engagement_id = _create(client)

    r = client.post(f"/api/engagements/{engagement_id}/demo-files")

    assert r.status_code == 202, r.text
    names = sorted(d["file_name"] for d in r.json()["documents"])
    assert names == [
        "locations.docx",
        "locations.json",
        "questionnaire.json",
        "questionnaire.pdf",
        "sales.csv",
    ]
    assert processing.processed == [engagement_id]


def test_reference_status_and_index(api):
    client, _, processing, _ = api
    assert client.get("/api/reference").json()["indexed"] is False
    assert client.post("/api/reference/index").status_code == 202
    assert processing.reference_runs == 1
    assert client.get("/api/reference").json()["indexed"] is True


def test_run_review_requires_readiness_then_queues(api):
    client, engagements, _, reviews = api
    engagement_id = _create(client)
    client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )

    assert (
        client.post(f"/api/engagements/{engagement_id}/reviews").status_code == 409
    )  # not indexed yet

    engagements.store.set_document_status(engagement_id, "a.pdf", "indexed", pages=1, chunks=1)
    r = client.post(f"/api/engagements/{engagement_id}/reviews")

    assert r.status_code == 202
    assert r.json() == {"review_id": "rev_new", "status": "queued"}
    assert reviews.executed == ["rev_new"]
    detail = client.get("/api/reviews/rev_new").json()
    assert detail["status"] == "queued" and detail["review"] is None and detail["decisions"] == []
    listed = client.get(f"/api/engagements/{engagement_id}/reviews").json()
    assert listed[0]["status"] == "queued"
    assert (
        client.get(f"/api/engagements/{engagement_id}").json()["latest_review"]["review_id"]
        == "rev_new"
    )


class _FakeAsk:
    def __init__(self) -> None:
        self.questions: list[tuple[str, str]] = []

    def ask(self, engagement_id: str, question: str):
        from app.models.review import CitationGuardReport
        from app.services.ask_service import AskResult

        self.questions.append((engagement_id, question))
        return AskResult(
            engagement_id=engagement_id,
            question=question,
            answer="Yes.",
            found_in_documents=True,
            citations=[],
            passages=[],
            citation_guard=CitationGuardReport(),
            model="gpt-4.1-mini",
        )


def test_ask_requires_readiness_then_answers(api):
    from app.api.dependencies import get_ask_service

    client, engagements, _, _ = api
    fake = _FakeAsk()
    client.app.dependency_overrides[get_ask_service] = lambda: fake
    engagement_id = _create(client)

    assert (
        client.post(f"/api/engagements/{engagement_id}/ask", json={"question": "x"}).status_code
        == 409
    )

    client.post(
        f"/api/engagements/{engagement_id}/documents",
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )
    engagements.store.set_document_status(engagement_id, "a.pdf", "indexed", pages=1, chunks=1)
    r = client.post(
        f"/api/engagements/{engagement_id}/ask", json={"question": "Inventory in Texas?"}
    )

    assert r.status_code == 200, r.text
    assert r.json()["answer"] == "Yes." and "not tax advice" in r.json()["disclaimer"].lower()
    assert fake.questions == [(engagement_id, "Inventory in Texas?")]
    assert (
        client.post(f"/api/engagements/{engagement_id}/ask", json={"question": "  "}).status_code
        == 422
    )
    assert client.post("/api/engagements/ghost-2025/ask", json={"question": "x"}).status_code == 404
