"""Run the search_evidence tool from the command line (retrieval check).

Usage (from backend/):
  uv run python -m scripts.query_evidence "inventory in Texas"
      [--engagement acme-2025] [--doc-types questionnaire reference] [--top-k 5]
"""

from __future__ import annotations

import argparse

from app.azure.embeddings import EmbeddingService
from app.azure.search import SearchService
from app.config import get_settings
from app.tools.search_evidence import SearchEvidenceArgs, SearchEvidenceTool


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--engagement", default="acme-2025")
    parser.add_argument("--doc-types", nargs="*")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)

    settings = get_settings()
    tool = SearchEvidenceTool(
        embeddings=EmbeddingService.from_settings(settings),
        search=SearchService.from_settings(settings),
    )
    hits = tool.run(
        SearchEvidenceArgs(query=args.query, doc_types=args.doc_types, top_k=args.top_k),
        engagement_id=args.engagement,
    )
    for i, hit in enumerate(hits, 1):
        print(f"{i}. [{hit.chunk_id}] {hit.source_name} p.{hit.page} score={hit.score:.4f}")
        print(
            "   " + hit.excerpt[:300].replace("\n", " ") + ("..." if len(hit.excerpt) > 300 else "")
        )
    if not hits:
        print("no results")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
