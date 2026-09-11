import json

import pytest
from pydantic import ValidationError

from app.models.review import (
    Citation,
    CitationGuardReport,
    ReviewDraft,
    ReviewResult,
    RiskFlag,
    ToolFinding,
    strict_json_schema,
)


def _flag(**overrides) -> dict:
    base = {
        "id": "TX-PHYSICAL-PRESENCE",
        "title": "Inventory held in Texas without registration",
        "state": "TX",
        "category": "physical_presence",
        "risk_level": "high",
        "explanation": "AI analysis text.",
        "retrieved_evidence": [
            {
                "chunk_id": "questionnaire-p1-c1",
                "source_name": "questionnaire.pdf",
                "page": 1,
                "quote": "Yes",
            }
        ],
        "tool_findings": [{"tool": "analyze_sales_by_state", "finding": "TX revenue 620,000.00"}],
        "recommended_human_action": "Confirm 3PL arrangement and registration status.",
    }
    return {**base, **overrides}


def _draft(**overrides) -> dict:
    base = {
        "overall_summary": "Two high-risk states.",
        "overall_risk_level": "high",
        "risk_flags": [_flag()],
        "states_reviewed_without_flags": ["CA", "NY"],
    }
    return {**base, **overrides}


def test_draft_parses_from_model_json():
    draft = ReviewDraft.model_validate_json(json.dumps(_draft()))
    assert draft.risk_flags[0].retrieved_evidence[0].chunk_id == "questionnaire-p1-c1"
    assert isinstance(draft.risk_flags[0].tool_findings[0], ToolFinding)


@pytest.mark.parametrize(
    "bad",
    [
        _draft(overall_risk_level="critical"),
        _draft(risk_flags=[_flag(category="tax_fraud")]),
        _draft(risk_flags=[_flag(risk_level="")]),
        _draft(risk_flags=[_flag(retrieved_evidence=[{"chunk_id": "x"}])]),
        {**_draft(), "extra_field": 1},
    ],
)
def test_draft_rejects_invalid_or_extra_content(bad):
    with pytest.raises(ValidationError):
        ReviewDraft.model_validate(bad)


def test_review_result_forces_human_review_and_carries_metadata():
    result = ReviewResult(
        **_draft(),
        review_id="rev_1",
        engagement_id="acme-2025",
        model="gpt-4.1-mini",
        agent_name="FDprojectAgent",
        tool_calls=["analyze_sales_by_state"],
        citation_guard=CitationGuardReport(),
    )
    assert result.human_review_required is True
    assert "not tax advice" in result.disclaimer.lower()
    assert result.created_at is not None
    with pytest.raises(ValidationError):
        ReviewResult(
            **_draft(),
            review_id="rev_1",
            engagement_id="acme-2025",
            model="m",
            agent_name="a",
            tool_calls=[],
            citation_guard=CitationGuardReport(),
            human_review_required=False,
        )


def _walk_objects(schema: dict, defs: dict):
    """Yield every object schema reachable from the root, following $ref."""
    seen = set()
    stack = [schema]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            if name not in seen:
                seen.add(name)
                stack.append(defs[name])
            continue
        if node.get("type") == "object":
            yield node
        for key in ("properties", "items", "anyOf", "$defs"):
            value = node.get(key)
            if isinstance(value, dict):
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)


def test_strict_schema_closes_every_object_and_requires_every_property():
    schema = strict_json_schema(ReviewDraft)
    objects = list(_walk_objects(schema, schema.get("$defs", {})))
    assert len(objects) >= 4  # draft, flag, citation, tool finding
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert sorted(obj["required"]) == sorted(obj["properties"])


def test_citation_and_flag_models_are_minimal_and_typed():
    c = Citation(chunk_id="a-p1-c0", source_name="a.pdf", page=1, quote="x")
    assert c.page == 1
    with pytest.raises(ValidationError):
        RiskFlag(**_flag(state="Texas"))  # must be a 2-letter code or null
