"""get_questionnaire_answers - the client's self-reported answers, optionally one section."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.models.engagement import EngagementData, QuestionnaireAnswer


class QuestionnaireResult(BaseModel):
    engagement_id: str
    section: str | None
    available_sections: list[str]
    answers: list[QuestionnaireAnswer]
    source: Literal["tool:get_questionnaire_answers"] = "tool:get_questionnaire_answers"


def get_questionnaire_answers(
    data: EngagementData, section: str | None = None
) -> QuestionnaireResult:
    sections = list(dict.fromkeys(a.section for a in data.questionnaire))
    matched = None
    if section:
        matched = next((s for s in sections if s.lower() == section.strip().lower()), None)
    answers = (
        [a for a in data.questionnaire if a.section == matched]
        if section
        else list(data.questionnaire)
    )
    return QuestionnaireResult(
        engagement_id=data.engagement_id,
        section=matched,
        available_sections=sections,
        answers=answers,
    )
