import pytest
from fastapi.testclient import TestClient

from app.agent.foundry_agent import AgentRunError
from app.api.dependencies import get_review_service
from app.db.reviews import ReviewSummary
from app.main import create_app
from app.models.review import CitationGuardReport, ReviewResult
from app.services.engagement_data import EngagementNotFoundError
from app.services.review_service import ReviewParseError


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
        risk_flags=[],
        states_reviewed_without_flags=[],
    )


class _FakeService:
    def __init__(self) -> None:
        self.saved = {"rev_abc": _result()}
        self.fail_with: Exception | None = None

    def run_review(self, engagement_id: str) -> ReviewResult:
        if self.fail_with:
            raise self.fail_with
        if engagement_id != "acme-2025":
            raise EngagementNotFoundError(engagement_id)
        return self.saved["rev_abc"]

    def get_review(self, review_id: str) -> ReviewResult | None:
        return self.saved.get(review_id)

    def list_reviews(self, engagement_id: str) -> list[ReviewSummary]:
        return [
            ReviewSummary(
                review_id=r.review_id,
                engagement_id=r.engagement_id,
                created_at=r.created_at,
                overall_risk_level=r.overall_risk_level,
                flag_count=len(r.risk_flags),
                model=r.model,
            )
            for r in self.saved.values()
            if r.engagement_id == engagement_id
        ]


@pytest.fixture
def api() -> tuple[TestClient, _FakeService]:
    app = create_app()
    fake = _FakeService()
    app.dependency_overrides[get_review_service] = lambda: fake
    return TestClient(app), fake


def test_post_review_returns_result_with_disclaimer(api):
    client, _ = api
    response = client.post("/api/engagements/acme-2025/reviews")
    assert response.status_code == 201
    body = response.json()
    assert body["review_id"] == "rev_abc"
    assert body["human_review_required"] is True
    assert "not tax advice" in body["disclaimer"].lower()


def test_post_review_unknown_engagement_is_404(api):
    client, _ = api
    assert client.post("/api/engagements/nope-2025/reviews").status_code == 404


def test_post_review_agent_failure_is_502_with_reason(api):
    client, fake = api
    fake.fail_with = AgentRunError("agent response r1 failed")
    response = client.post("/api/engagements/acme-2025/reviews")
    assert response.status_code == 502
    assert "failed" in response.json()["detail"]

    fake.fail_with = ReviewParseError("bad json")
    assert client.post("/api/engagements/acme-2025/reviews").status_code == 502


def test_get_review_and_list(api):
    client, _ = api
    assert client.get("/api/reviews/rev_abc").json()["engagement_id"] == "acme-2025"
    assert client.get("/api/reviews/missing").status_code == 404
    listed = client.get("/api/engagements/acme-2025/reviews").json()
    assert [r["review_id"] for r in listed] == ["rev_abc"]


def test_invalid_engagement_id_shape_is_rejected_by_validation(api):
    client, _ = api
    assert client.post("/api/engagements/..%2Fetc/reviews").status_code in (404, 422)
