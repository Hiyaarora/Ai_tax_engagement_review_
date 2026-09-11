from types import SimpleNamespace

import pytest

from app.agent.foundry_agent import AgentRunError, FoundryAgentRunner


def _fn_call(call_id: str, name: str, arguments: str):
    return SimpleNamespace(type="function_call", call_id=call_id, name=name, arguments=arguments)


def _response(rid: str, output: list, text: str = "", status: str = "completed"):
    return SimpleNamespace(
        id=rid,
        status=status,
        output=output,
        output_text=text,
        model="gpt-4.1-mini",
        usage=SimpleNamespace(input_tokens=10, output_tokens=5),
    )


class _FakeResponses:
    def __init__(self, scripted: list) -> None:
        self._scripted = list(scripted)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._scripted.pop(0)


class _FakeClient:
    def __init__(self, scripted: list) -> None:
        self.responses = _FakeResponses(scripted)


def test_run_dispatches_function_calls_and_returns_final_text():
    client = _FakeClient(
        [
            _response(
                "r1",
                [
                    _fn_call("c1", "analyze_sales_by_state", "{}"),
                    _fn_call("c2", "search_evidence", '{"query": "tx"}'),
                ],
            ),
            _response("r2", [_fn_call("c3", "get_employee_locations", "{}")]),
            _response("r3", [SimpleNamespace(type="message")], text='{"overall_summary": "done"}'),
        ]
    )
    dispatched: list[tuple[str, str]] = []

    def dispatch(name: str, args: str) -> str:
        dispatched.append((name, args))
        return f'{{"ran": "{name}"}}'

    outcome = FoundryAgentRunner(client, agent_name="FDprojectAgent").run("review acme", dispatch)  # type: ignore[arg-type]

    assert outcome.output_text == '{"overall_summary": "done"}'
    assert dispatched == [
        ("analyze_sales_by_state", "{}"),
        ("search_evidence", '{"query": "tx"}'),
        ("get_employee_locations", "{}"),
    ]
    first, second, third = client.responses.calls
    assert first["input"] == "review acme"
    assert first["extra_body"] == {
        "agent_reference": {"name": "FDprojectAgent", "type": "agent_reference"}
    }
    assert second["previous_response_id"] == "r1"
    assert second["input"] == [
        {
            "type": "function_call_output",
            "call_id": "c1",
            "output": '{"ran": "analyze_sales_by_state"}',
        },
        {"type": "function_call_output", "call_id": "c2", "output": '{"ran": "search_evidence"}'},
    ]
    assert third["previous_response_id"] == "r2"
    assert outcome.response_ids == ["r1", "r2", "r3"]
    assert outcome.turns == 3
    assert outcome.model == "gpt-4.1-mini"
    assert outcome.input_tokens == 30 and outcome.output_tokens == 15


def test_run_stops_after_max_turns():
    endless = [
        _response(f"r{i}", [_fn_call(f"c{i}", "analyze_sales_by_state", "{}")]) for i in range(20)
    ]
    client = _FakeClient(endless)
    runner = FoundryAgentRunner(client, agent_name="A", max_turns=3)  # type: ignore[arg-type]
    with pytest.raises(AgentRunError, match="max_turns"):
        runner.run("go", lambda n, a: "{}")
    assert len(client.responses.calls) == 3


def test_run_raises_on_failed_or_incomplete_response():
    client = _FakeClient([_response("r1", [], status="failed")])
    with pytest.raises(AgentRunError, match="failed"):
        FoundryAgentRunner(client, agent_name="A").run("go", lambda n, a: "{}")  # type: ignore[arg-type]


def test_run_raises_when_final_response_has_no_text():
    client = _FakeClient([_response("r1", [SimpleNamespace(type="message")], text="")])
    with pytest.raises(AgentRunError, match="no output text"):
        FoundryAgentRunner(client, agent_name="A").run("go", lambda n, a: "{}")  # type: ignore[arg-type]
