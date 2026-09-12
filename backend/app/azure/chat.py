"""Direct chat completions on GPT-4.1-mini for grounded question answering.

Same resource-level Azure OpenAI v1 route and bearer-token auth as embeddings (see
``embeddings.py`` for why not the project-scoped route). The hosted review agent is not used here:
its definition is specialised for reviews (tools + ReviewDraft schema); a question needs a plain,
schema-constrained completion over passages the backend already retrieved - optionally with a
small set of function tools, served with the same ``function_call`` -> ``function_call_output``
round-trip as the review agent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Self

from azure.identity import get_bearer_token_provider
from openai import OpenAI

from app.azure.credential import get_credential
from app.azure.embeddings import COGNITIVE_SERVICES_SCOPE
from app.config import Settings
from app.observability.tracing import span

Dispatch = Callable[[str, str], str]  # (tool name, arguments JSON) -> output JSON


@dataclass
class ChatCompletion:
    text: str
    model: str
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


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
            timeout=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
        return cls(client=client, deployment=settings.foundry_chat_deployment)

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
        tools: list[dict[str, Any]] | None = None,
        dispatch: Dispatch | None = None,
        max_turns: int = 4,
    ) -> ChatCompletion:
        """One completion constrained to ``schema`` (strict). Returns the raw JSON text + usage.

        With ``tools``, the model may call functions first; each ``function_call`` is answered by
        ``dispatch`` and the conversation continues until the model emits its final JSON.
        ``max_turns`` bounds the number of API round-trips.
        """
        common: dict[str, Any] = {
            "model": self.deployment,
            "instructions": system,
            "temperature": self.temperature,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
        }
        if tools:
            common["tools"] = tools

        result = ChatCompletion(text="", model=self.deployment)
        # gen_ai.* attributes follow the OpenTelemetry GenAI semantic conventions so this span is
        # recognised by the Foundry Tracing view alongside the agent's own spans.
        with span(
            "chat.complete",
            model=self.deployment,
            tools=len(tools or []),
            **{
                "gen_ai.operation.name": "chat",
                "gen_ai.provider.name": "azure.openai",
                "gen_ai.request.model": self.deployment,
            },
        ) as current:
            previous_id: str | None = None
            pending: list[dict[str, Any]] = []
            for _ in range(max_turns):
                response: Any = (
                    self._client.responses.create(input=user, **common)
                    if previous_id is None
                    else self._client.responses.create(
                        previous_response_id=previous_id,
                        input=pending,  # type: ignore[arg-type]  # openai types omit tool outputs
                        **common,
                    )
                )
                _record_usage(response, result)
                calls = [
                    item for item in response.output if getattr(item, "type", "") == "function_call"
                ]
                if not calls or dispatch is None:
                    result.text = str(response.output_text or "")
                    current.set_attribute("turns", result.turns)
                    current.set_attribute("input_tokens", result.input_tokens)
                    current.set_attribute("output_tokens", result.output_tokens)
                    current.set_attribute("gen_ai.response.model", result.model)
                    current.set_attribute("gen_ai.usage.input_tokens", result.input_tokens)
                    current.set_attribute("gen_ai.usage.output_tokens", result.output_tokens)
                    return result
                pending = [
                    {
                        "type": "function_call_output",
                        "call_id": call.call_id,
                        "output": dispatch(call.name, call.arguments),
                    }
                    for call in calls
                ]
                previous_id = response.id
        raise RuntimeError(f"model did not finish within max_turns={max_turns}")


def _record_usage(response: Any, result: ChatCompletion) -> None:
    result.turns += 1
    result.model = getattr(response, "model", result.model) or result.model
    usage = getattr(response, "usage", None)
    if usage is not None:
        result.input_tokens += getattr(usage, "input_tokens", 0) or 0
        result.output_tokens += getattr(usage, "output_tokens", 0) or 0
