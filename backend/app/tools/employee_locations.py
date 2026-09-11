"""get_employee_locations - where the company has people or sites, from the structured HR list."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.models.engagement import EmployeeLocation, EngagementData


class EmployeeLocationsResult(BaseModel):
    engagement_id: str
    home_state: str
    total_headcount: int
    states_with_employees: list[str]
    states_with_other_presence: list[str]
    locations: list[EmployeeLocation]
    source: Literal["tool:get_employee_locations"] = "tool:get_employee_locations"


def get_employee_locations(data: EngagementData) -> EmployeeLocationsResult:
    with_employees = sorted({loc.state for loc in data.locations if loc.headcount > 0})
    other = sorted(
        {loc.state for loc in data.locations if loc.headcount == 0} - set(with_employees)
    )
    return EmployeeLocationsResult(
        engagement_id=data.engagement_id,
        home_state=data.home_state,
        total_headcount=sum(loc.headcount for loc in data.locations),
        states_with_employees=with_employees,
        states_with_other_presence=other,
        locations=list(data.locations),
    )
