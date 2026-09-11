"""Structured client data for one engagement - the input to the deterministic tools.

These are the *system-of-record* copies (what an intake form or ERP export would provide). The
PDF/DOCX versions of the same facts are indexed separately as citable evidence.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

ENGAGEMENT_ID_PATTERN = r"^[a-z0-9][a-z0-9\-]{1,63}$"


class Transaction(BaseModel):
    transaction_id: str
    date: date
    ship_to_state: str = Field(min_length=2, max_length=2)
    amount_usd: float
    channel: str


class QuestionnaireAnswer(BaseModel):
    id: str
    section: str
    question: str
    answer: str
    note: str = ""


class EmployeeLocation(BaseModel):
    city: str
    state: str = Field(min_length=2, max_length=2)
    site_type: str
    headcount: int = Field(ge=0)
    note: str = ""


class EngagementData(BaseModel):
    engagement_id: str = Field(pattern=ENGAGEMENT_ID_PATTERN)
    company_name: str
    home_state: str = Field(min_length=2, max_length=2)
    tax_year: int
    transactions: list[Transaction]
    questionnaire: list[QuestionnaireAnswer]
    locations: list[EmployeeLocation]
