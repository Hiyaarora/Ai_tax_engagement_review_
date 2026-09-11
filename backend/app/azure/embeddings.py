"""Embeddings via the Azure OpenAI v1 route on the Foundry project's AI Services resource.

We deliberately do not use ``AIProjectClient.get_openai_client()``: it targets the project-scoped
``/api/projects/<name>/openai/v1`` route, which returns 404 on this project. The resource-level
``{resource}/openai/v1`` route (derived from the project endpoint in ``Settings``) works with the
same ``DefaultAzureCredential`` bearer token - still keyless, one config value.
"""

from __future__ import annotations

from typing import Self

from azure.identity import get_bearer_token_provider
from openai import OpenAI

from app.azure.credential import get_credential
from app.config import Settings

# text-embedding-3-small output size; the AI Search vector field must use this dimension.
EMBEDDING_DIMENSIONS = 1536

COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"


class EmbeddingService:
    def __init__(self, client: OpenAI, deployment: str) -> None:
        self._client = client
        self.deployment = deployment

    @property
    def base_url(self) -> str:
        return str(self._client.base_url)

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        client = OpenAI(
            base_url=f"{settings.foundry_resource_endpoint}/openai/v1/",
            api_key=get_bearer_token_provider(get_credential(), COGNITIVE_SERVICES_SCOPE),
        )
        return cls(client=client, deployment=settings.foundry_embedding_deployment)

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed each text; result order matches input order."""
        if not texts:
            return []
        if any(not text.strip() for text in texts):
            raise ValueError("cannot embed blank text")
        response = self._client.embeddings.create(model=self.deployment, input=texts)
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

    def ping(self) -> None:
        """Cheap authenticated call used by the connectivity check. Raises on failure."""
        self.embed(["ping"])
