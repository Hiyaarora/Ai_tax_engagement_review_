"""Builds the hosted agent's definition from code: instructions, tool schemas, output schema.

The definition is version-controlled here and pushed to Foundry by ``scripts/sync_agent.py``, so
what runs in the portal is always what is in the repo.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from azure.ai.projects.models import (
    FunctionTool,
    PromptAgentDefinition,
    PromptAgentDefinitionTextOptions,
    TextResponseFormatJsonSchema,
    Tool,
)

from app.agent.tool_registry import ToolRegistry
from app.config import Settings
from app.models.review import ReviewDraft, strict_json_schema

SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"
OUTPUT_SCHEMA_NAME = "review_draft"


def load_system_prompt() -> str:
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def build_agent_definition(settings: Settings, registry: ToolRegistry) -> PromptAgentDefinition:
    tools: Sequence[Tool] = [
        FunctionTool(
            name=d["name"], description=d["description"], parameters=d["parameters"], strict=True
        )
        for d in registry.definitions()
    ]
    return PromptAgentDefinition(
        model=settings.foundry_chat_deployment,
        instructions=load_system_prompt(),
        tools=list(tools),
        temperature=0.1,
        text=PromptAgentDefinitionTextOptions(
            format=TextResponseFormatJsonSchema(
                name=OUTPUT_SCHEMA_NAME,
                description="Structured SALT nexus review: summary, risk flags with evidence.",
                schema=strict_json_schema(ReviewDraft),
                strict=True,
            )
        ),
    )
