"""Direct chat completions on GPT-4.1-mini for grounded question answering.

Same resource-level Azure OpenAI v1 route and bearer-token auth as embeddings (see
``embeddings.py`` for why not the project-scoped route). The hosted review agent is not used here:
its definition is specialised for reviews (tools + ReviewDraft schema); a question needs a plain,
schema-constrained completion over passages the backend already retrieved.
"""

from __future__ import annotations

from typing import Any, Self

from azure.identity import get_bearer_token_provider
from openai import OpenAI

from app.azure.credential import get_credential
from app.azure.embeddings import COGNITIVE_SERVICES_SCOPE
from app.config import Settings


class ChatService:
    def __init__(self, client: OpenAI, deployment: str, temperature: float = 0.1) -> None:
        self._client = client
        self.deployment = deployment
        self.temperature = temperature

    @property
    def base_url(self) -> str:
        return str(self._client.base_url)

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        client = OpenAI(
            base_url=f"{settings.foundry_resource_endpoint}/openai/v1/",
            api_key=get_bearer_token_provider(get_credential(), COGNITIVE_SERVICES_SCOPE),
        )
        return cls(client=client, deployment=settings.foundry_chat_deployment)

    def complete_json(
        self, *, system: str, user: str, schema_name: str, schema: dict[str, Any]
    ) -> str:
        """One completion constrained to ``schema`` (strict). Returns the raw JSON text."""
        response: Any = self._client.responses.create(
            model=self.deployment,
            instructions=system,
            input=user,
            temperature=self.temperature,
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        )
        return str(response.output_text or "")
