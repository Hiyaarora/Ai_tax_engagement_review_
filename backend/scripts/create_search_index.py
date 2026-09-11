"""Create the evidence index in Azure AI Search.

Usage (from backend/):
  uv run python -m scripts.create_search_index              # create if missing (idempotent)
  uv run python -m scripts.create_search_index --recreate   # drop + create (deletes all chunks)
Schema lives in app/azure/search.py::build_index_definition.
"""

from __future__ import annotations

import argparse

from app.azure.search import SearchService
from app.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recreate", action="store_true", help="drop and re-create the index")
    args = parser.parse_args(argv)

    service = SearchService.from_settings(get_settings())
    if args.recreate:
        service.recreate_index()
        print(f"index {service.index_name!r}: recreated")
    else:
        created = service.create_index_if_missing()
        print(f"index {service.index_name!r}: {'created' if created else 'already exists'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
