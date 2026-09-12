from types import SimpleNamespace

from app.azure.chat import ChatService
from app.config import Settings


class _FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text='{"answer": "yes"}', model="gpt-4.1-mini", output=[])


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


def _fn_call(call_id: str, name: str, arguments: str):
    return SimpleNamespace(type="function_call", call_id=call_id, name=name, arguments=arguments)


def _resp(rid: str, output: list, text: str = ""):
    return SimpleNamespace(id=rid, status="completed", output=output, output_text=text, model="m")


class _ScriptedResponses:
    def __init__(self, scripted: list) -> None:
        self.scripted = list(scripted)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.scripted.pop(0)


def test_complete_json_with_tools_dispatches_function_calls_then_returns_final_json():
    client = SimpleNamespace(
        responses=_ScriptedResponses(
            [
                _resp("r1", [_fn_call("c1", "analyze_sales_by_state", "{}")]),
                _resp("r2", [SimpleNamespace(type="message")], text='{"answer": "TX 620k"}'),
            ]
        ),
        base_url="x",
    )
    service = ChatService(client=client, deployment="gpt-4.1-mini")  # type: ignore[arg-type]
    dispatched: list[tuple[str, str]] = []
    tools = [{"type": "function", "name": "analyze_sales_by_state", "parameters": {}}]

    text = service.complete_json(
        system="sys",
        user="What are the sales in Texas?",
        schema_name="ask_draft",
        schema={"type": "object"},
        tools=tools,
        dispatch=lambda name, args: dispatched.append((name, args)) or '{"states": []}',
    )

    assert text == '{"answer": "TX 620k"}'
    assert dispatched == [("analyze_sales_by_state", "{}")]
    first, second = client.responses.calls
    assert first["tools"] == tools and first["text"]["format"]["name"] == "ask_draft"
    assert second["previous_response_id"] == "r1"
    assert second["input"] == [
        {"type": "function_call_output", "call_id": "c1", "output": '{"states": []}'}
    ]
    assert second["tools"] == tools and second["instructions"] == "sys"


def test_complete_json_with_tools_stops_after_max_turns():
    import pytest

    endless = [
        _resp(f"r{i}", [_fn_call(f"c{i}", "analyze_sales_by_state", "{}")]) for i in range(9)
    ]
    client = SimpleNamespace(responses=_ScriptedResponses(endless), base_url="x")
    service = ChatService(client=client, deployment="m")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="max_turns"):
        service.complete_json(
            system="s",
            user="u",
            schema_name="n",
            schema={},
            tools=[{}],
            dispatch=lambda n, a: "{}",
            max_turns=3,
        )
    assert len(client.responses.calls) == 3
