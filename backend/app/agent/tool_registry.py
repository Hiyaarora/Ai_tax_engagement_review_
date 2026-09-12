"""Maps agent tool names to Python handlers and derives their JSON schemas from Pydantic.

Two guarantees:
* The schema pushed to Foundry and the arguments validated at dispatch come from the *same*
  Pydantic model, so they cannot drift.
* Handlers receive ``engagement_id`` and data from the ``ReviewContext``; the model can only pass
  the arguments in the args model (``extra="forbid"``), so it can never target another engagement.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.review_context import ReviewContext
from app.models.evidence import EvidenceHit
from app.models.review import strict_json_schema
from app.observability.tracing import span
from app.tools.employee_locations import get_employee_locations
from app.tools.nexus_thresholds import check_economic_nexus_thresholds
from app.tools.questionnaire import get_questionnaire_answers
from app.tools.sales_by_state import analyze_sales_by_state
from app.tools.search_evidence import SearchEvidenceArgs, SearchEvidenceTool

Handler = Callable[[ReviewContext, Any], BaseModel]


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionnaireArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str | None = Field(
        default=None,
        description="Optional section name, e.g. 'Physical presence' or 'Registrations'.",
    )


class SearchEvidenceOutput(BaseModel):
    source: str = "retrieved_evidence"
    hits: list[EvidenceHit]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    handler: Handler


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs = {spec.name: spec for spec in specs}

    @property
    def names(self) -> list[str]:
        return list(self._specs)

    def definitions(self) -> list[dict[str, Any]]:
        """Function-tool definitions in the shape the Responses API / Foundry agent expects."""
        return [
            {
                "type": "function",
                "name": spec.name,
                "description": spec.description,
                "parameters": strict_json_schema(spec.args_model),
            }
            for spec in self._specs.values()
        ]

    def dispatch(self, name: str, arguments_json: str, ctx: ReviewContext) -> str:
        """Run one tool call. Always returns JSON; errors go back to the model, never raise."""
        with span(f"tool.{name}", engagement_id=ctx.engagement_id) as current:
            started = time.perf_counter()
            output, ok = self._dispatch(name, arguments_json, ctx)
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            if ok:
                ctx.tool_timings.append((name, elapsed_ms))
            current.set_attribute("ok", ok)
            current.set_attribute("output_bytes", len(output))
            return output

    def _dispatch(self, name: str, arguments_json: str, ctx: ReviewContext) -> tuple[str, bool]:
        spec = self._specs.get(name)
        if spec is None:
            return json.dumps({"error": f"unknown tool {name!r}; available: {self.names}"}), False
        try:
            args = spec.args_model.model_validate_json(arguments_json or "{}")
        except ValidationError as exc:
            error = {"error": f"invalid arguments for {name}: {exc.errors()}"}
            return json.dumps(error, default=str), False
        ctx.tool_calls.append(name)
        return spec.handler(ctx, args).model_dump_json(), True


def build_registry(search_evidence: SearchEvidenceTool | None) -> ToolRegistry:
    def _search(ctx: ReviewContext, args: SearchEvidenceArgs) -> BaseModel:
        if search_evidence is None:
            raise RuntimeError("search_evidence tool not configured")
        hits = search_evidence.run(args, engagement_id=ctx.engagement_id)
        ctx.record_hits(hits)
        return SearchEvidenceOutput(hits=hits)

    return ToolRegistry(
        [
            ToolSpec(
                "search_evidence",
                SearchEvidenceTool.description,
                SearchEvidenceArgs,
                _search,
            ),
            ToolSpec(
                "analyze_sales_by_state",
                "Deterministic: revenue, transaction count and marketplace share by ship-to state "
                "for the engagement's tax year, computed from the client's sales data.",
                NoArgs,
                lambda ctx, _: analyze_sales_by_state(ctx.data),
            ),
            ToolSpec(
                "check_economic_nexus_thresholds",
                "Deterministic: compares each state's sales/transactions with the ILLUSTRATIVE "
                "reference thresholds and reports whether the threshold is met, with the basis.",
                NoArgs,
                lambda ctx, _: check_economic_nexus_thresholds(ctx.data),
            ),
            ToolSpec(
                "get_employee_locations",
                "Deterministic: the client's structured employee/office/site list by state, "
                "including states with employees and states with other presence (e.g. 3PL).",
                NoArgs,
                lambda ctx, _: get_employee_locations(ctx.data),
            ),
            ToolSpec(
                "get_questionnaire_answers",
                "Deterministic: the client's self-reported nexus questionnaire answers, "
                "optionally filtered to one section.",
                QuestionnaireArgs,
                lambda ctx, args: get_questionnaire_answers(ctx.data, section=args.section),
            ),
        ]
    )
