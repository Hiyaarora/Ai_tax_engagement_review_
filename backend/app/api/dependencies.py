"""FastAPI dependencies that wire services from settings.

``get_engagement_service`` needs no Azure at all (create/upload/list work offline).
``get_processing_service`` and ``get_review_service`` build the Azure-backed pipeline lazily and
cache it, so importing the app never touches Azure. Tests override all three with fakes.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.agent.foundry_agent import FoundryAgentRunner
from app.agent.tool_registry import build_registry
from app.azure.document_intelligence import DocumentIntelligenceService
from app.azure.embeddings import EmbeddingService
from app.azure.search import SearchService
from app.config import Settings, get_settings
from app.db.engagements import EngagementStore
from app.db.reviews import ReviewRepository
from app.services.engagement_data import EngagementDataRepository
from app.services.engagement_service import EngagementService
from app.services.ingestion import IngestionService
from app.services.processing_service import ProcessingService
from app.services.review_service import ReviewService
from app.tools.search_evidence import SearchEvidenceTool


def sqlite_path(settings: Settings) -> Path:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise ValueError(f"only sqlite:/// URLs are supported, got {url!r}")
    return Path(url.removeprefix("sqlite:///"))


def uploads_root(settings: Settings) -> Path:
    return Path(settings.data_dir) / "uploads"


def fixtures_root(settings: Settings) -> Path:
    return Path(settings.data_dir) / "synthetic"


def build_engagement_service(settings: Settings) -> EngagementService:
    return EngagementService(
        store=EngagementStore(sqlite_path(settings)),
        files=EngagementDataRepository(uploads_root(settings)),
        fixtures_root=fixtures_root(settings),
        max_upload_bytes=settings.max_upload_mb * 1024 * 1024,
    )


def build_ingestion_service(settings: Settings) -> IngestionService:
    return IngestionService(
        document_intelligence=DocumentIntelligenceService.from_settings(settings),
        embeddings=EmbeddingService.from_settings(settings),
        search=SearchService.from_settings(settings),
    )


def build_processing_service(settings: Settings) -> ProcessingService:
    return ProcessingService(
        store=EngagementStore(sqlite_path(settings)),
        files=EngagementDataRepository(uploads_root(settings)),
        ingestion=build_ingestion_service(settings),
        fixtures_root=fixtures_root(settings),
    )


def build_review_service(settings: Settings) -> ReviewService:
    search_tool = SearchEvidenceTool(
        embeddings=EmbeddingService.from_settings(settings),
        search=SearchService.from_settings(settings),
    )
    return ReviewService(
        engagements=EngagementDataRepository(uploads_root(settings)),
        registry=build_registry(search_evidence=search_tool),
        runner=FoundryAgentRunner.from_settings(settings),
        reviews=ReviewRepository(sqlite_path(settings)),
    )


@lru_cache
def get_engagement_service() -> EngagementService:
    return build_engagement_service(get_settings())


@lru_cache
def get_processing_service() -> ProcessingService:
    return build_processing_service(get_settings())


@lru_cache
def get_review_service() -> ReviewService:
    return build_review_service(get_settings())
