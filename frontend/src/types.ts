// Mirrors the backend Pydantic models (app/models/review.py, app/db/reviews.py, app/api/*).
// Kept in sync by hand; the shapes are small and stable.

export interface AzureConfigState {
  foundry: boolean
  search: boolean
  document_intelligence: boolean
}

export interface HealthResponse {
  status: string
  service: string
  version: string
  environment: string
  azure: AzureConfigState
}

export type RiskLevel = 'low' | 'medium' | 'high'
export type RiskCategory =
  | 'physical_presence'
  | 'economic_nexus'
  | 'registration'
  | 'data_inconsistency'
  | 'other'
export type Decision = 'accepted' | 'rejected' | 'needs_more_info'

/** A passage the agent actually retrieved; source/page are backend-verified. */
export interface Citation {
  chunk_id: string
  source_name: string
  page: number
  quote: string
}

/** A deterministic result attributed to the tool that computed it. */
export interface ToolFinding {
  tool: string
  finding: string
}

export interface RiskFlag {
  id: string
  title: string
  state: string | null
  category: RiskCategory
  risk_level: RiskLevel
  explanation: string
  retrieved_evidence: Citation[]
  tool_findings: ToolFinding[]
  recommended_human_action: string
}

export interface CitationGuardReport {
  dropped_citations: string[]
  corrected_citations: string[]
  unverified_quotes: { chunk_id: string; quote: string }[]
  dropped_tool_findings: string[]
  flags_without_evidence: string[]
}

export interface ReviewResult {
  review_id: string
  engagement_id: string
  created_at: string
  model: string
  agent_name: string
  tool_calls: string[]
  citation_guard: CitationGuardReport
  human_review_required: true
  disclaimer: string
  overall_summary: string
  overall_risk_level: RiskLevel
  risk_flags: RiskFlag[]
  states_reviewed_without_flags: string[]
}

export interface FlagDecision {
  review_id: string
  flag_id: string
  decision: Decision
  reviewer_note: string
  decided_at: string
}

export interface ReviewDetail {
  review: ReviewResult
  decisions: FlagDecision[]
}

export interface ReviewSummary {
  review_id: string
  engagement_id: string
  created_at: string
  overall_risk_level: RiskLevel
  flag_count: number
  model: string
}

export interface EngagementSummary {
  engagement_id: string
  company_name: string
  home_state: string
  tax_year: number
  documents: string[]
}
