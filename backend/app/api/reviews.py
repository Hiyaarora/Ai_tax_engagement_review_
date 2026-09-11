"""Review endpoints. HTTP concerns only - orchestration lives in ReviewService."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel

from app.agent.foundry_agent import AgentRunError
from app.api.dependencies import get_review_service
from app.db.reviews import Decision, FlagDecision, ReviewSummary, UnknownFlagError
from app.models.engagement import ENGAGEMENT_ID_PATTERN
from app.models.review import ReviewResult
from app.services.engagement_data import EngagementNotFoundError
from app.services.review_service import EngagementSummary, ReviewParseError, ReviewService

router = APIRouter(tags=["reviews"])

EngagementId = Annotated[str, Path(pattern=ENGAGEMENT_ID_PATTERN)]
Service = Annotated[ReviewService, Depends(get_review_service)]


class ReviewDetail(BaseModel):
    review: ReviewResult
    decisions: list[FlagDecision]


class DecisionRequest(BaseModel):
    decision: Decision
    reviewer_note: str = ""


@router.get("/engagements", response_model=list[EngagementSummary])
def list_engagements(service: Service) -> list[EngagementSummary]:
    return service.list_engagements()


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


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
def get_review(review_id: str, service: Service) -> ReviewDetail:
    result = service.get_review(review_id)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown review {review_id}")
    return ReviewDetail(review=result, decisions=service.list_decisions(review_id))


@router.patch("/reviews/{review_id}/flags/{flag_id}", response_model=FlagDecision)
def decide_flag(
    review_id: str, flag_id: str, body: DecisionRequest, service: Service
) -> FlagDecision:
    """Record the human reviewer's decision on one flag (the required final step)."""
    try:
        return service.decide_flag(
            FlagDecision(
                review_id=review_id,
                flag_id=flag_id,
                decision=body.decision,
                reviewer_note=body.reviewer_note,
            )
        )
    except UnknownFlagError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown flag {exc}") from exc
