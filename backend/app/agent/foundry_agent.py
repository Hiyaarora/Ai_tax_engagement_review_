"""Runs the hosted Foundry prompt agent via the OpenAI Responses API and serves its tool calls.

Foundry (azure-ai-projects 2.x) agents are invoked with ``responses.create`` + ``agent_reference``
against the project endpoint. When the agent wants a function tool, the response carries
``function_call`` items; we execute them locally and continue the same conversation with
``previous_response_id`` + ``function_call_output`` items until the agent produces its final text.
This is the 2.x equivalent of the 1.x threads/runs ``requires_action`` loop.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from azure.ai.projects import AIProjectClient
from openai import OpenAI

from app.azure.credential import get_credential
from app.config import Settings
from app.observability.tracing import span

Dispatch = Callable[[str, str], str]  # (tool name, arguments JSON) -> output JSON


class AgentRunError(RuntimeError):
    pass


@dataclass
class AgentRunOutcome:
    output_text: str
    model: str
    response_ids: list[str] = field(default_factory=list)
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class FoundryAgentRunner:
    def __init__(self, client: OpenAI, agent_name: str, max_turns: int = 12) -> None:
        self._client = client
        self.agent_name = agent_name
        self.max_turns = max_turns

    @classmethod
    def from_settings(cls, settings: Settings) -> FoundryAgentRunner:
        project = AIProjectClient(settings.foundry_project_endpoint, get_credential())
        return cls(project.get_openai_client(), agent_name=settings.foundry_agent_name)

    @property
    def _agent_ref(self) -> dict[str, Any]:
        return {"agent_reference": {"name": self.agent_name, "type": "agent_reference"}}

    def run(self, user_input: str, dispatch: Dispatch) -> AgentRunOutcome:
        """Drive the agent to completion. ``max_turns`` bounds the number of API round-trips."""
        outcome = AgentRunOutcome(output_text="", model="")
        previous_id: str | None = None
        pending: list[dict[str, Any]] = []
        for turn in range(1, self.max_turns + 1):
            with span("agent.turn", agent=self.agent_name, turn=turn) as current:
                response: Any = (
                    self._client.responses.create(input=user_input, extra_body=self._agent_ref)
                    if previous_id is None
                    else self._client.responses.create(
                        previous_response_id=previous_id,
                        input=pending,  # type: ignore[arg-type]  # openai types omit tool outputs
                        extra_body=self._agent_ref,
                    )
                )
                self._record(response, outcome)
                current.set_attribute("response_id", response.id)
                status = getattr(response, "status", "completed")
                if status in ("failed", "incomplete", "cancelled"):
                    raise AgentRunError(f"agent response {response.id} {status}")
                calls = [
                    item for item in response.output if getattr(item, "type", "") == "function_call"
                ]
                current.set_attribute("tool_calls", len(calls))
            if not calls:
                outcome.output_text = response.output_text or ""
                if not outcome.output_text:
                    raise AgentRunError(f"agent response {response.id} has no output text")
                return outcome
            pending = [
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": dispatch(call.name, call.arguments),
                }
                for call in calls
            ]
            previous_id = response.id
        raise AgentRunError(f"agent did not finish within max_turns={self.max_turns}")

    @staticmethod
    def _record(response: Any, outcome: AgentRunOutcome) -> None:
        outcome.response_ids.append(response.id)
        outcome.turns += 1
        outcome.model = getattr(response, "model", outcome.model) or outcome.model
        usage = getattr(response, "usage", None)
        if usage is not None:
            outcome.input_tokens += getattr(usage, "input_tokens", 0) or 0
            outcome.output_tokens += getattr(usage, "output_tokens", 0) or 0
