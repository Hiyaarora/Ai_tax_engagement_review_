from app.agent.definition import build_agent_definition, load_system_prompt
from app.agent.tool_registry import build_registry
from app.config import Settings


def test_system_prompt_states_the_guardrails():
    prompt = load_system_prompt().lower()
    for phrase in ("synthetic", "not tax advice", "never fabricate", "human review", "chunk_id"):
        assert phrase in prompt, phrase


def test_definition_binds_model_instructions_tools_and_strict_output_schema():
    settings = Settings(_env_file=None, foundry_chat_deployment="gpt-4.1-mini")
    registry = build_registry(search_evidence=None)

    definition = build_agent_definition(settings, registry)

    assert definition.model == "gpt-4.1-mini"
    assert "Never fabricate evidence" in (definition.instructions or "")
    assert [t.name for t in definition.tools or []] == registry.names
    assert all(t.strict is True for t in definition.tools or [])
    fmt = definition.text.format  # type: ignore[union-attr]
    assert fmt.name == "review_draft" and fmt.strict is True
    assert "risk_flags" in fmt.schema["properties"]
    assert fmt.schema["additionalProperties"] is False
    assert definition.temperature == 0.1
