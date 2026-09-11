"""Review endpoints. HTTP concerns only - orchestration lives in ReviewService."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.agent.foundry_agent import AgentRunError
from app.api.dependencies import get_review_service
from app.db.reviews import ReviewSummary
from app.models.engagement import ENGAGEMENT_ID_PATTERN
from app.models.review import ReviewResult
from app.services.engagement_data import EngagementNotFoundError
from app.services.review_service import ReviewParseError, ReviewService

router = APIRouter(tags=["reviews"])

EngagementId = Annotated[str, Path(pattern=ENGAGEMENT_ID_PATTERN)]
Service = Annotated[ReviewService, Depends(get_review_service)]


@router.post(
    "/engagements/{engagement_id}/reviews",
    response_model=ReviewResult,
    status_code=status.HTTP_201_CREATED,
)
def run_review(engagement_id: EngagementId, service: Service) -> ReviewResult:
    """Run the review agent for one engagement and return the guarded, persisted result.

    Synchronous by design for this demo (typically 30-90 s). Decision support only - not tax advice.
    """
    try:
        return service.run_review(engagement_id)
    except EngagementNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown engagement {exc}") from exc
    except (AgentRunError, ReviewParseError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"review agent error: {exc}") from exc


@router.get("/engagements/{engagement_id}/reviews", response_model=list[ReviewSummary])
def list_reviews(engagement_id: EngagementId, service: Service) -> list[ReviewSummary]:
    return service.list_reviews(engagement_id)


@router.get("/reviews/{review_id}", response_model=ReviewResult)
def get_review(review_id: str, service: Service) -> ReviewResult:
    result = service.get_review(review_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown review {review_id}")
    return result
