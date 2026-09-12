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

/** Cost and latency of one agent/model run. */
export interface TokenUsage {
  input_tokens: number
  output_tokens: number
  turns: number
  duration_ms: number
  tool_durations_ms: Record<string, number>
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
  usage: TokenUsage
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

export type ReviewStatus = 'queued' | 'running' | 'done' | 'failed'

/** A review at any point in its lifecycle; `review` is set only when status is `done`. */
export interface ReviewDetail {
  review_id: string
  engagement_id: string
  status: ReviewStatus
  error: string | null
  review: ReviewResult | null
  decisions: FlagDecision[]
}

export interface ReviewSummary {
  review_id: string
  engagement_id: string
  created_at: string
  status: ReviewStatus
  error: string | null
  overall_risk_level: RiskLevel | null
  flag_count: number
  model: string | null
}

export type FileKind = 'document' | 'sales_csv' | 'questionnaire_json' | 'locations_json'
export type DocumentStatus = 'uploaded' | 'processing' | 'indexed' | 'validated' | 'failed'
export type DocType = 'questionnaire' | 'locations' | 'reference' | 'other'

export interface DocumentRecord {
  engagement_id: string
  file_name: string
  original_name: string
  kind: FileKind
  doc_type: DocType
  status: DocumentStatus
  pages: number | null
  chunks: number | null
  error: string | null
  updated_at: string
}

export interface EngagementRecord {
  engagement_id: string
  company_name: string
  home_state: string
  tax_year: number
  created_at: string
}

/** Backend-owned readiness: the UI never computes can_ask / can_review itself. */
export interface EngagementDetail {
  engagement: EngagementRecord
  documents: DocumentRecord[]
  can_ask: boolean
  can_review: boolean
  latest_review: ReviewSummary | null
}

export interface ReferenceStatus {
  indexed: boolean
  status: 'not_indexed' | 'processing' | 'indexed' | 'failed'
  chunks: number
  error: string | null
}

/** A retrieved passage (what the review agent and the ask endpoint both see). */
export interface EvidenceHit {
  chunk_id: string
  doc_id: string
  doc_type: DocType
  source_name: string
  page: number
  excerpt: string
  score: number
}

/** A figure computed from a client data file (e.g. sales.csv) - not a document passage. */
export interface StructuredEvidence {
  tool: string
  source: string
  finding: string
}

/** Grounded answer to one question; citations passed the same guard as review flags. */
export interface AskResult {
  engagement_id: string
  question: string
  answer: string
  found_in_documents: boolean
  citations: Citation[]
  structured_evidence: StructuredEvidence[]
  tool_calls: string[]
  passages: EvidenceHit[]
  citation_guard: CitationGuardReport
  usage: TokenUsage
  model: string
  disclaimer: string
}
