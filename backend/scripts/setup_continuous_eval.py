"""Attach continuous evaluation to the review agent in Foundry.

Usage (from backend/):  uv run python -m scripts.setup_continuous_eval [--sampling 100] [--disable]

Creates (or reuses) an Eval that runs Foundry's built-in agent evaluators - relevance, coherence,
task adherence, intent resolution, tool-call accuracy - and a rule that applies it to every
completed FDprojectAgent response. Scores then appear in the *Evaluation* column of the Foundry
Tracing view and in the Evaluations tab. Only responses produced after the rule exists are scored.

Prerequisite (one-off RBAC): the project's system-assigned managed identity needs the
"Foundry User" role on the project, because continuous evaluation runs as that identity:
    az role assignment create --assignee-object-id <project principalId> \\
        --assignee-principal-type ServicePrincipal --role "Foundry User" --scope <project id>
Propagation can take several minutes; the script retries.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    ContinuousEvaluationRuleAction,
    EvaluationRule,
    EvaluationRuleEventType,
    EvaluationRuleFilter,
)
from azure.core.exceptions import HttpResponseError

from app.azure.credential import get_credential
from app.config import get_settings

RULE_ID = "fd-tax-review-continuous"
EVAL_NAME = "fd-tax-review continuous evaluation"
EVALUATORS = ("relevance", "coherence", "task_adherence", "intent_resolution", "tool_call_accuracy")


def _find_or_create_eval(openai_client: Any, deployment: str) -> str:
    for existing in openai_client.evals.list():
        if getattr(existing, "name", "") == EVAL_NAME:
            return str(existing.id)
    created = openai_client.evals.create(
        name=EVAL_NAME,
        data_source_config={"type": "azure_ai_source", "scenario": "responses"},
        testing_criteria=[
            {
                "type": "azure_ai_evaluator",
                "name": name,
                "evaluator_name": f"builtin.{name}",
                "initialization_parameters": {"deployment_name": deployment},
            }
            for name in EVALUATORS
        ],
    )
    return str(created.id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sampling", type=int, default=100, help="percent of responses to score")
    parser.add_argument("--max-hourly", type=int, default=50)
    parser.add_argument("--disable", action="store_true", help="disable the rule instead")
    args = parser.parse_args(argv)

    settings = get_settings()
    project = AIProjectClient(settings.foundry_project_endpoint, get_credential())
    eval_id = _find_or_create_eval(project.get_openai_client(), settings.foundry_chat_deployment)
    print(f"eval: {eval_id} ({', '.join(EVALUATORS)})")

    rule = EvaluationRule(
        display_name="FD tax review - evaluate every agent response",
        description="Built-in agent evaluators on each completed FDprojectAgent response.",
        event_type=EvaluationRuleEventType.RESPONSE_COMPLETED,
        filter=EvaluationRuleFilter(agent_name=settings.foundry_agent_name),
        action=ContinuousEvaluationRuleAction(
            eval_id=eval_id, sampling_rate=args.sampling, max_hourly_runs=args.max_hourly
        ),
        enabled=not args.disable,
    )
    for attempt in range(1, 21):
        try:
            saved = project.evaluation_rules.create_or_update(id=RULE_ID, evaluation_rule=rule)
        except HttpResponseError as exc:
            if "managed identity" in str(exc):
                print(f"attempt {attempt}: waiting for the Foundry User role to propagate...")
                time.sleep(30)
                continue
            raise
        print(
            f"rule {saved.id}: enabled={saved.enabled} agent={settings.foundry_agent_name} "
            f"sampling={args.sampling}%"
        )
        return 0
    print("gave up: grant the project managed identity 'Foundry User' on the project (see --help)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
