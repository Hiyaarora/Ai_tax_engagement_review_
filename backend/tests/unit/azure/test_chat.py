from types import SimpleNamespace

from app.azure.chat import ChatService
from app.config import Settings


class _FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text='{"answer": "yes"}', model="gpt-4.1-mini")


class _FakeClient:
    def __init__(self) -> None:
        self.responses = _FakeResponses()
        self.base_url = "https://example.services.ai.azure.com/openai/v1/"


def test_complete_json_sends_system_user_and_strict_schema():
    client = _FakeClient()
    service = ChatService(client=client, deployment="gpt-4.1-mini")  # type: ignore[arg-type]

    text = service.complete_json(
        system="You are careful.",
        user="Question?",
        schema_name="ask_draft",
        schema={"type": "object", "properties": {"answer": {"type": "string"}}},
    )

    assert text == '{"answer": "yes"}'
    call = client.responses.calls[0]
    assert call["model"] == "gpt-4.1-mini"
    assert call["instructions"] == "You are careful."
    assert call["input"] == "Question?"
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["name"] == "ask_draft"
    assert call["text"]["format"]["strict"] is True
    assert call["temperature"] == 0.1


def test_from_settings_targets_resource_level_route_and_chat_deployment():
    settings = Settings(
        _env_file=None,
        foundry_project_endpoint="https://example.services.ai.azure.com/api/projects/p",
        foundry_chat_deployment="gpt-4.1-mini",
    )
    service = ChatService.from_settings(settings)
    assert service.deployment == "gpt-4.1-mini"
    assert str(service.base_url) == "https://example.services.ai.azure.com/openai/v1/"
