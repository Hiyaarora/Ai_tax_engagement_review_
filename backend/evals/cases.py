"""Golden evaluation cases: controlled variants of the synthetic Acme engagement.

Each case is the committed dataset plus a small *mutation* (an answer flipped, a state's sales
changed, a location removed) with the flags a correct review must and must not raise. Documents
for a case are produced by the same generator as the demo files, so the agent sees realistic
PDF/DOCX/CSV inputs, not hand-written fixtures.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.engagement import (
    EmployeeLocation,
    EngagementData,
    QuestionnaireAnswer,
    Transaction,
)
from scripts.synthetic import dataset, generate

GOLDEN_SET_PATH = Path(__file__).resolve().parent / "golden_set.jsonl"
RiskLevel = Literal["low", "medium", "high"]


class Mutation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questionnaire: dict[str, str] = Field(
        default_factory=dict, description="answer overrides by id"
    )
    questionnaire_notes: dict[str, str] = Field(default_factory=dict, description="note overrides")
    remove_locations: list[str] = Field(default_factory=list, description="states to drop")
    sales_plan: dict[str, tuple[int, float]] = Field(
        default_factory=dict, description="state -> (transactions, revenue) overrides"
    )


class ExpectedFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str | None
    categories_any: list[str] = Field(default_factory=list)
    min_risk_level: RiskLevel = "low"


class ForbiddenFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: str | None
    categories_any: list[str] = Field(default_factory=list)
    max_risk_level: RiskLevel | None = Field(
        default=None, description="If set, flags at or below this level are tolerated."
    )


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    description: str
    mutation: Mutation = Field(default_factory=Mutation)
    expected_flags: list[ExpectedFlag] = Field(default_factory=list)
    forbidden_flags: list[ForbiddenFlag] = Field(default_factory=list)


def load_cases(path: Path = GOLDEN_SET_PATH) -> list[EvalCase]:
    return [
        EvalCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _mutated_questionnaire(case: EvalCase) -> list[dataset.QuestionnaireItem]:
    items = []
    for item in dataset.questionnaire():
        updates = {}
        if item.id in case.mutation.questionnaire:
            updates["answer"] = case.mutation.questionnaire[item.id]
        if item.id in case.mutation.questionnaire_notes:
            updates["note"] = case.mutation.questionnaire_notes[item.id]
        items.append(replace(item, **updates) if updates else item)
    return items


def _mutated_locations(case: EvalCase) -> list[dataset.EmployeeLocation]:
    return [
        loc
        for loc in dataset.employee_locations()
        if loc.state not in case.mutation.remove_locations
    ]


def _mutated_transactions(case: EvalCase) -> list[dataset.Transaction]:
    plan = {**dataset.SALES_PLAN, **case.mutation.sales_plan}
    return dataset.sales_transactions(plan)


def build_variant(case: EvalCase) -> EngagementData:
    """The engagement data for a case, in the same shape the tools consume."""
    return EngagementData(
        engagement_id=dataset.ENGAGEMENT_ID,
        company_name=dataset.COMPANY.name,
        home_state=dataset.COMPANY.home_state,
        tax_year=dataset.TAX_YEAR,
        transactions=[Transaction(**t.__dict__) for t in _mutated_transactions(case)],
        questionnaire=[QuestionnaireAnswer(**q.__dict__) for q in _mutated_questionnaire(case)],
        locations=[EmployeeLocation(**loc.__dict__) for loc in _mutated_locations(case)],
    )


def write_variant_files(case: EvalCase, directory: Path) -> list[Path]:
    """Write the case's documents and structured files (upload-ready) into ``directory``."""
    directory.mkdir(parents=True, exist_ok=True)
    items, locations, rows = (
        _mutated_questionnaire(case),
        _mutated_locations(case),
        _mutated_transactions(case),
    )
    generate.write_questionnaire_pdf(directory / "questionnaire.pdf", items)
    generate.write_questionnaire_json(directory / "questionnaire.json", items)
    generate.write_locations_docx(directory / "locations.docx", locations)
    generate.write_locations_json(directory / "locations.json", locations)
    generate.write_sales_csv_file(directory / "sales.csv", rows)
    generate.write_reference_pdf(directory / "salt_reference_guide.pdf")
    return sorted(p for p in directory.iterdir() if p.is_file())


CASES: list[EvalCase] = load_cases()
