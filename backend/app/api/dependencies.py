"""FastAPI dependencies that wire real Azure-backed services from settings.

Built lazily and cached so importing the app never touches Azure; tests override
``get_review_service`` with a fake.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.agent.foundry_agent import FoundryAgentRunner
from app.agent.tool_registry import build_registry
from app.azure.embeddings import EmbeddingService
from app.azure.search import SearchService
from app.config import Settings, get_settings
from app.db.reviews import ReviewRepository
from app.services.engagement_data import EngagementDataRepository
from app.services.review_service import ReviewService
from app.tools.search_evidence import SearchEvidenceTool


def sqlite_path(settings: Settings) -> Path:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise ValueError(f"only sqlite:/// URLs are supported, got {url!r}")
    return Path(url.removeprefix("sqlite:///"))


def build_review_service(settings: Settings) -> ReviewService:
    search_tool = SearchEvidenceTool(
        embeddings=EmbeddingService.from_settings(settings),
        search=SearchService.from_settings(settings),
    )
    return ReviewService(
        engagements=EngagementDataRepository(Path(settings.data_dir) / "synthetic"),
        registry=build_registry(search_evidence=search_tool),
        runner=FoundryAgentRunner.from_settings(settings),
        reviews=ReviewRepository(sqlite_path(settings)),
    )


@lru_cache
def get_review_service() -> ReviewService:
    return build_review_service(get_settings())
