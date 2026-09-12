"""Engagement, upload, and processing endpoints. HTTP concerns only."""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Path,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.api.dependencies import (
    get_ask_service,
    get_engagement_service,
    get_processing_service,
    get_review_service,
)
from app.db.engagements import DocumentRecord
from app.models.engagement import ENGAGEMENT_ID_PATTERN
from app.models.evidence import DocType
from app.services.ask_service import AskError, AskResult, AskService
from app.services.engagement_data import EngagementNotFoundError
from app.services.engagement_service import (
    EngagementDetail,
    EngagementService,
    UploadRejectedError,
)
from app.services.processing_service import ProcessingService, ReferenceStatus
from app.services.review_service import ReviewService

router = APIRouter(tags=["engagements"])

EngagementId = Annotated[str, Path(pattern=ENGAGEMENT_ID_PATTERN)]
Engagements = Annotated[EngagementService, Depends(get_engagement_service)]
Processing = Annotated[ProcessingService, Depends(get_processing_service)]
Reviews = Annotated[ReviewService, Depends(get_review_service)]
Ask = Annotated[AskService, Depends(get_ask_service)]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class CreateEngagementRequest(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    home_state: str = Field(pattern=r"^[A-Za-z]{2}$")
    tax_year: int = Field(ge=2000, le=2100)


class ProcessAccepted(BaseModel):
    engagement_id: str
    queued: int


class DemoLoaded(BaseModel):
    engagement_id: str
    documents: list[DocumentRecord]
    queued: int


def _detail(
    engagements: EngagementService, reviews: ReviewService, engagement_id: str
) -> EngagementDetail:
    try:
        summaries = reviews.list_reviews(engagement_id)
        return engagements.detail(engagement_id, latest_review=summaries[0] if summaries else None)
    except EngagementNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown engagement {exc}") from exc


@router.get("/engagements", response_model=list[EngagementDetail])
def list_engagements(engagements: Engagements, reviews: Reviews) -> list[EngagementDetail]:
    return [
        _detail(engagements, reviews, e.engagement.engagement_id) for e in engagements.list_all()
    ]


@router.post("/engagements", response_model=EngagementDetail, status_code=status.HTTP_201_CREATED)
def create_engagement(body: CreateEngagementRequest, engagements: Engagements) -> EngagementDetail:
    return engagements.create(
        company_name=body.company_name, home_state=body.home_state, tax_year=body.tax_year
    )


@router.get("/engagements/{engagement_id}", response_model=EngagementDetail)
def get_engagement(
    engagement_id: EngagementId, engagements: Engagements, reviews: Reviews
) -> EngagementDetail:
    return _detail(engagements, reviews, engagement_id)


@router.delete("/engagements/{engagement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_engagement(
    engagement_id: EngagementId,
    engagements: Engagements,
    processing: Processing,
    reviews: Reviews,
) -> None:
    """Remove an engagement: uploaded files, reviews and decisions, and its search-index chunks."""
    try:
        engagements.get(engagement_id)
    except EngagementNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown engagement {exc}") from exc
    processing.delete_engagement_chunks(engagement_id)
    reviews.delete_for_engagement(engagement_id)
    engagements.delete(engagement_id)


@router.post(
    "/engagements/{engagement_id}/documents",
    response_model=DocumentRecord,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    engagement_id: EngagementId,
    engagements: Engagements,
    file: UploadFile,
    doc_type: Annotated[DocType | None, Form()] = None,
) -> DocumentRecord:
    """Upload one PDF/DOCX (indexed as evidence) or CSV (sales export, validated on arrival)."""
    content = await file.read()
    try:
        return engagements.save_upload(
            engagement_id, file.filename or "upload", content, doc_type=doc_type
        )
    except EngagementNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown engagement {exc}") from exc
    except UploadRejectedError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _queue_processing(
    background: BackgroundTasks,
    engagements: EngagementService,
    processing: ProcessingService,
    engagement_id: str,
) -> int:
    pending = [
        d
        for d in engagements.detail(engagement_id).documents
        if d.kind == "document" and d.status in ("uploaded", "failed")
    ]
    if pending:
        background.add_task(processing.process_engagement, engagement_id)
    return len(pending)


@router.post(
    "/engagements/{engagement_id}/documents/process",
    response_model=ProcessAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
def process_documents(
    engagement_id: EngagementId,
    background: BackgroundTasks,
    engagements: Engagements,
    processing: Processing,
) -> ProcessAccepted:
    """Index uploaded/failed documents in the background; poll the engagement for status."""
    try:
        queued = _queue_processing(background, engagements, processing, engagement_id)
    except EngagementNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown engagement {exc}") from exc
    return ProcessAccepted(engagement_id=engagement_id, queued=queued)


@router.post(
    "/engagements/{engagement_id}/demo-files",
    response_model=DemoLoaded,
    status_code=status.HTTP_202_ACCEPTED,
)
def load_demo_files(
    engagement_id: EngagementId,
    background: BackgroundTasks,
    engagements: Engagements,
    processing: Processing,
) -> DemoLoaded:
    """Load the synthetic Acme fixtures through the normal upload path, then queue processing."""
    try:
        documents = engagements.load_demo(engagement_id)
    except EngagementNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown engagement {exc}") from exc
    queued = _queue_processing(background, engagements, processing, engagement_id)
    return DemoLoaded(engagement_id=engagement_id, documents=documents, queued=queued)


@router.get("/reference", response_model=ReferenceStatus)
def reference_status(processing: Processing) -> ReferenceStatus:
    return processing.reference_status()


@router.post("/reference/index", status_code=status.HTTP_202_ACCEPTED)
def index_reference(background: BackgroundTasks, processing: Processing) -> dict[str, str]:
    background.add_task(processing.index_reference)
    return {"status": "processing"}


@router.post("/engagements/{engagement_id}/ask", response_model=AskResult)
def ask_engagement(
    engagement_id: EngagementId, body: AskRequest, engagements: Engagements, ask: Ask
) -> AskResult:
    """Grounded answer from the engagement's indexed documents, with verified citations."""
    if not body.question.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "question is empty")
    try:
        if not engagements.detail(engagement_id).can_ask:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "index at least one document before asking questions"
            )
        return ask.ask(engagement_id, body.question)
    except EngagementNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown engagement {exc}") from exc
    except AskError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"answer error: {exc}") from exc
