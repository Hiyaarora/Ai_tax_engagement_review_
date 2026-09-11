"""The per-review user message. The agent's standing instructions live in system_prompt.md."""

from __future__ import annotations

from app.models.engagement import EngagementData


def build_review_prompt(data: EngagementData, document_names: list[str]) -> str:
    docs = "\n".join(f"  - {name}" for name in document_names) or "  (none)"
    return f"""Review the following engagement for potential state and local tax (SALT) nexus risks.

Engagement: {data.engagement_id}
Client: {data.company_name} (SYNTHETIC demo client)
Home state: {data.home_state}
Tax year: {data.tax_year}
Indexed documents available to search_evidence:
{docs}
Shared reference guidance (illustrative, not law) is also searchable with doc_types=["reference"].

Procedure:
1. Call analyze_sales_by_state and check_economic_nexus_thresholds for the sales picture.
2. Call get_employee_locations and get_questionnaire_answers for presence and registrations.
3. For every state you intend to flag, call search_evidence to retrieve the supporting passages
   from the client's documents and the reference guidance, and cite them by chunk_id.
4. Compare the client's self-reported answers with the structured data and note inconsistencies.
5. Return the review as JSON matching the required schema. Do not flag states where neither
   physical presence nor a met threshold is indicated; list them in states_reviewed_without_flags.
"""
