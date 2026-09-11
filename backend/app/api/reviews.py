"""Review endpoints. HTTP concerns only - orchestration lives in ReviewService."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, status
from pydantic import BaseModel

from app.api.dependencies import get_engagement_service, get_review_service
from app.db.reviews import (
    Decision,
    FlagDecision,
    ReviewStatus,
    ReviewSummary,
    UnknownFlagError,
)
from app.models.engagement import ENGAGEMENT_ID_PATTERN
from app.models.review import ReviewResult
from app.services.engagement_data import EngagementNotFoundError
from app.services.engagement_service import EngagementService
from app.services.review_service import ReviewService

router = APIRouter(tags=["reviews"])

EngagementId = Annotated[str, Path(pattern=ENGAGEMENT_ID_PATTERN)]
Service = Annotated[ReviewService, Depends(get_review_service)]
Engagements = Annotated[EngagementService, Depends(get_engagement_service)]


class ReviewQueued(BaseModel):
    review_id: str
    status: ReviewStatus


class ReviewDetail(BaseModel):
    """A review at any point in its lifecycle; ``review`` is set only when ``status == done``."""

    review_id: str
    engagement_id: str
    status: ReviewStatus
    error: str | None
    review: ReviewResult | None
    decisions: list[FlagDecision]


class DecisionRequest(BaseModel):
    decision: Decision
    reviewer_note: str = ""


@router.post(
    "/engagements/{engagement_id}/reviews",
    response_model=ReviewQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
def run_review(
    engagement_id: EngagementId,
    background: BackgroundTasks,
    service: Service,
    engagements: Engagements,
) -> ReviewQueued:
    """Queue the review agent for one engagement; poll GET /reviews/{id} for the result.

    Decision support only - not tax advice.
    """
    try:
        if not engagements.detail(engagement_id).can_review:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "engagement is not ready for review: index at least one document first",
            )
        review_id = service.start_review(engagement_id)
    except EngagementNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown engagement {exc}") from exc
    background.add_task(service.execute_review, review_id)
    return ReviewQueued(review_id=review_id, status="queued")


@router.get("/engagements/{engagement_id}/reviews", response_model=list[ReviewSummary])
def list_reviews(engagement_id: EngagementId, service: Service) -> list[ReviewSummary]:
    return service.list_reviews(engagement_id)


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
def get_review(review_id: str, service: Service) -> ReviewDetail:
    record = service.get_record(review_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown review {review_id}")
    return ReviewDetail(
        review_id=record.review_id,
        engagement_id=record.engagement_id,
        status=record.status,
        error=record.error,
        review=record.result,
        decisions=service.list_decisions(review_id) if record.status == "done" else [],
    )


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
