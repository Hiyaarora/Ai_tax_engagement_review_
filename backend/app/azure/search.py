"""Azure AI Search wrapper.

Stage 1 only holds the clients and index-level helpers. Index creation, upsert and hybrid query
arrive with the RAG pipeline (Milestone 2, Stage 2+).
"""

from __future__ import annotations

from typing import Self

from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient

from app.azure.credential import get_credential
from app.config import Settings


class SearchService:
    def __init__(
        self, index_client: SearchIndexClient, index_name: str, endpoint: str = ""
    ) -> None:
        self._index_client = index_client
        self.index_name = index_name
        self.endpoint = endpoint

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        return cls(
            index_client=SearchIndexClient(settings.azure_search_endpoint, get_credential()),
            index_name=settings.azure_search_index_name,
            endpoint=settings.azure_search_endpoint,
        )

    def index_exists(self) -> bool:
        return self.index_name in set(self._index_client.list_index_names())

    def search_client(self) -> SearchClient:
        """Document-level client for the configured index (used by later stages)."""
        return self._index_client.get_search_client(self.index_name)

    def ping(self) -> None:
        """Cheap authenticated call used by the connectivity check. Raises on failure."""
        self._index_client.get_service_statistics()
