"""Push the versioned agent definition (instructions, tools, output schema) to Foundry.

Usage (from backend/):  uv run python -m scripts.sync_agent [--show]
Creates a new version of the agent named by FOUNDRY_AGENT_NAME. Run after changing
app/agent/system_prompt.md, any tool argument model, or the ReviewDraft schema.
"""

from __future__ import annotations

import argparse
import json

from azure.ai.projects import AIProjectClient

from app.agent.definition import build_agent_definition
from app.agent.tool_registry import build_registry
from app.azure.credential import get_credential
from app.config import get_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", action="store_true", help="print the definition, do not push")
    args = parser.parse_args(argv)

    settings = get_settings()
    definition = build_agent_definition(settings, build_registry(search_evidence=None))
    if args.show:
        print(json.dumps(definition.as_dict(), indent=2))
        return 0

    project = AIProjectClient(settings.foundry_project_endpoint, get_credential())
    version = project.agents.create_version(
        settings.foundry_agent_name,
        definition=definition,
        description="F&D Tax Engagement Review Agent (synthetic data, decision support only)",
    )
    print(f"agent {settings.foundry_agent_name!r}: version {version.version} created")
    tool_names = [getattr(t, "name", t.type) for t in definition.tools or []]
    print(f"  model={definition.model} tools={tool_names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
