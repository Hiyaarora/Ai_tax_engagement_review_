"""Ingest documents into the evidence index.

Usage (from backend/):
  uv run python -m scripts.ingest_documents --demo
  uv run python -m scripts.ingest_documents --file ../data/synthetic/x.pdf
      --engagement acme-2025 --doc-type questionnaire

``--demo`` ingests the synthetic engagement: questionnaire + locations under 'acme-2025' and the
reference guide under the shared id. The sales CSV is deliberately not indexed (tool data).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from app.azure.document_intelligence import DocumentIntelligenceService
from app.azure.embeddings import EmbeddingService
from app.azure.search import SearchService
from app.config import get_settings
from app.models.evidence import SHARED_ENGAGEMENT_ID, DocType
from app.services.ingestion import IngestionService

SYNTHETIC_DIR = Path(__file__).resolve().parents[2] / "data/synthetic"
DEMO_ENGAGEMENT_ID = "acme-2025"

# (file name, engagement id, doc type)
DEMO_MANIFEST: list[tuple[str, str, DocType]] = [
    ("acme_nexus_questionnaire.pdf", DEMO_ENGAGEMENT_ID, "questionnaire"),
    ("acme_employee_locations.docx", DEMO_ENGAGEMENT_ID, "locations"),
    ("salt_reference_guide.pdf", SHARED_ENGAGEMENT_ID, "reference"),
]


def build_service() -> IngestionService:
    settings = get_settings()
    return IngestionService(
        document_intelligence=DocumentIntelligenceService.from_settings(settings),
        embeddings=EmbeddingService.from_settings(settings),
        search=SearchService.from_settings(settings),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="ingest the synthetic demo engagement")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--engagement")
    parser.add_argument("--doc-type", choices=["questionnaire", "locations", "reference", "other"])
    args = parser.parse_args(argv)

    if args.demo:
        jobs = [(SYNTHETIC_DIR / name, eng, dt) for name, eng, dt in DEMO_MANIFEST]
    elif args.file and args.engagement and args.doc_type:
        jobs = [(args.file, args.engagement, args.doc_type)]
    else:
        parser.error("use --demo, or all of --file, --engagement and --doc-type")

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
