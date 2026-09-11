"""Create the evidence index in Azure AI Search if it does not exist.

Usage (from backend/):  uv run python -m scripts.create_search_index
Idempotent. Schema lives in app/azure/search.py::build_index_definition.
"""

from __future__ import annotations

from app.azure.search import SearchService
from app.config import get_settings


def main() -> int:
    service = SearchService.from_settings(get_settings())
    created = service.create_index_if_missing()
    print(f"index {service.index_name!r}: {'created' if created else 'already exists'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
