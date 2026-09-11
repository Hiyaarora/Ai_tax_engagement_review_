"""Ingest documents into the evidence index.

Usage (from backend/):
  uv run python -m scripts.ingest_documents --demo                 # every engagement + shared docs
  uv run python -m scripts.ingest_documents --engagement acme-2025 # one engagement's documents
  uv run python -m scripts.ingest_documents --file x.pdf --engagement acme-2025 --doc-type other

Documents are read from data/synthetic/engagements/<id>/ (doc type inferred from the file stem:
``questionnaire`` / ``locations``) and data/synthetic/shared/ (indexed as ``reference`` under the
shared id). The sales CSV is deliberately not indexed - it is tool data.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.azure.document_intelligence import DocumentIntelligenceService
from app.azure.embeddings import EmbeddingService
from app.azure.search import SearchService
from app.config import get_settings
from app.models.evidence import SHARED_ENGAGEMENT_ID, DocType
from app.services.engagement_data import EngagementDataRepository
from app.services.ingestion import INDEXABLE_SUFFIXES, IngestionService

SYNTHETIC_ROOT = Path(__file__).resolve().parents[2] / "data/synthetic"
_DOC_TYPE_BY_STEM: dict[str, DocType] = {"questionnaire": "questionnaire", "locations": "locations"}


def doc_type_for(path: Path) -> DocType:
    return _DOC_TYPE_BY_STEM.get(path.stem.lower(), "other")


def build_service() -> IngestionService:
    settings = get_settings()
    return IngestionService(
        document_intelligence=DocumentIntelligenceService.from_settings(settings),
        embeddings=EmbeddingService.from_settings(settings),
        search=SearchService.from_settings(settings),
    )


def engagement_jobs(
    repo: EngagementDataRepository, engagement_id: str
) -> list[tuple[Path, str, DocType]]:
    return [(p, engagement_id, doc_type_for(p)) for p in repo.document_paths(engagement_id)]


def shared_jobs(root: Path) -> list[tuple[Path, str, DocType]]:
    shared = root / "shared"
    if not shared.is_dir():
        return []
    return [
        (p, SHARED_ENGAGEMENT_ID, "reference")
        for p in sorted(shared.iterdir())
        if p.suffix.lower() in INDEXABLE_SUFFIXES
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="ingest all engagements + shared docs")
    parser.add_argument("--engagement")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--doc-type", choices=["questionnaire", "locations", "reference", "other"])
    args = parser.parse_args(argv)

    repo = EngagementDataRepository(SYNTHETIC_ROOT)
    jobs: list[tuple[Path, str, DocType]]
    if args.demo:
        jobs = shared_jobs(SYNTHETIC_ROOT)
        for engagement_id in repo.list_ids():
            jobs += engagement_jobs(repo, engagement_id)
    elif args.file and args.engagement and args.doc_type:
        jobs = [(args.file, args.engagement, args.doc_type)]
    elif args.engagement:
        jobs = engagement_jobs(repo, args.engagement)
    else:
        parser.error("use --demo, --engagement <id>, or --file/--engagement/--doc-type")

    service = build_service()
    for path, engagement_id, doc_type in jobs:
        result = service.ingest_file(path, engagement_id=engagement_id, doc_type=doc_type)
        print(
            f"{result.source_name}: engagement={result.engagement_id} type={result.doc_type} "
            f"pages={result.pages} chunks={result.chunks_indexed}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
