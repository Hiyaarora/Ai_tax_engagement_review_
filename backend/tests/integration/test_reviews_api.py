from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_review_service
from app.db.reviews import ReviewRepository
from app.main import create_app
from app.models.review import CitationGuardReport, ReviewResult, RiskFlag


def _result(review_id: str = "rev_abc") -> ReviewResult:
    return ReviewResult(
        review_id=review_id,
        engagement_id="acme-2025",
        model="gpt-4.1-mini",
        agent_name="FDprojectAgent",
        tool_calls=[],
        citation_guard=CitationGuardReport(),
        overall_summary="s",
        overall_risk_level="high",
        risk_flags=[
            RiskFlag(
                id="TX-1",
                title="t",
                state="TX",
                category="physical_presence",
                risk_level="high",
                explanation="e",
                retrieved_evidence=[],
                tool_findings=[],
                recommended_human_action="a",
            )
        ],
        states_reviewed_without_flags=[],
    )


class _RepoBackedService:
    """Reads/decisions go to a real repository; nothing here calls Azure."""

    def __init__(self, repo: ReviewRepository) -> None:
        self.repo = repo

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
    repo = ReviewRepository(tmp_path / "r.db")
    repo.save(_result("rev_abc"))
    repo.create_pending("rev_queued", "acme-2025")
    repo.create_pending("rev_bad", "acme-2025")
    repo.mark_failed("rev_bad", "AgentRunError: max_turns")
    app = create_app()
    app.dependency_overrides[get_review_service] = lambda: _RepoBackedService(repo)
    return TestClient(app)


def test_get_done_review_includes_result_and_disclaimer(api: TestClient):
    body = api.get("/api/reviews/rev_abc").json()
    assert body["status"] == "done" and body["error"] is None
    assert body["review"]["review_id"] == "rev_abc"
    assert body["review"]["human_review_required"] is True
    assert "not tax advice" in body["review"]["disclaimer"].lower()
    assert body["decisions"] == []


def test_get_queued_and_failed_reviews_expose_status_without_result(api: TestClient):
    queued = api.get("/api/reviews/rev_queued").json()
    assert queued["status"] == "queued" and queued["review"] is None
    failed = api.get("/api/reviews/rev_bad").json()
    assert (
        failed["status"] == "failed" and "max_turns" in failed["error"] and failed["review"] is None
    )
    assert api.get("/api/reviews/missing").status_code == 404


def test_list_reviews_with_status(api: TestClient):
    listed = api.get("/api/engagements/acme-2025/reviews").json()
    assert {r["review_id"]: r["status"] for r in listed} == {
        "rev_abc": "done",
        "rev_queued": "queued",
        "rev_bad": "failed",
    }


def test_patch_decision_round_trip_and_validation(api: TestClient):
    r = api.patch(
        "/api/reviews/rev_abc/flags/TX-1", json={"decision": "accepted", "reviewer_note": "ok"}
    )
    assert r.status_code == 200 and r.json()["decision"] == "accepted"
    assert api.get("/api/reviews/rev_abc").json()["decisions"][0]["flag_id"] == "TX-1"
    assert (
        api.patch("/api/reviews/rev_abc/flags/TX-1", json={"decision": "maybe"}).status_code == 422
    )
    assert (
        api.patch("/api/reviews/rev_abc/flags/NOPE", json={"decision": "rejected"}).status_code
        == 404
    )
    assert (
        api.patch("/api/reviews/rev_queued/flags/TX-1", json={"decision": "rejected"}).status_code
        == 404
    )
