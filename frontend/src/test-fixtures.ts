import type { DocumentRecord, EngagementDetail, ReviewDetail, ReviewSummary } from './types'

export const engagement: EngagementDetail = {
  engagement: {
    engagement_id: 'acme-widgets-llc-2025-ab12',
    company_name: 'Acme Widgets LLC',
    home_state: 'CO',
    tax_year: 2025,
    created_at: '2026-09-11T09:00:00Z',
  },
  documents: [],
  can_ask: false,
  can_review: false,
  latest_review: null,
}

export function doc(overrides: Partial<DocumentRecord>): DocumentRecord {
  return {
    engagement_id: engagement.engagement.engagement_id,
    file_name: 'questionnaire.pdf',
    original_name: 'questionnaire.pdf',
    kind: 'document',
    doc_type: 'questionnaire',
    status: 'uploaded',
    pages: null,
    chunks: null,
    error: null,
    updated_at: '2026-09-11T09:01:00Z',
    ...overrides,
  }
}

export function reviewSummary(overrides: Partial<ReviewSummary>): ReviewSummary {
  return {
    review_id: 'rev_1',
    engagement_id: engagement.engagement.engagement_id,
    created_at: '2026-09-11T10:00:00Z',
    status: 'done',
    error: null,
    overall_risk_level: 'medium',
    flag_count: 3,
    model: 'gpt-4.1-mini',
    ...overrides,
  }
}

export const doneReview: ReviewDetail = {
  review_id: 'rev_1',
  engagement_id: engagement.engagement.engagement_id,
  status: 'done',
  error: null,
  review: {
    review_id: 'rev_1',
    engagement_id: engagement.engagement.engagement_id,
    created_at: '2026-09-11T10:00:00Z',
    model: 'gpt-4.1-mini',
    agent_name: 'FDprojectAgent',
    tool_calls: ['analyze_sales_by_state', 'search_evidence'],
    citation_guard: {
      dropped_citations: ['ghost-p1-c0'],
      corrected_citations: [],
      unverified_quotes: [],
      dropped_tool_findings: [],
      flags_without_evidence: [],
    },
    human_review_required: true,
    disclaimer: 'Decision support only - not tax advice.',
    overall_summary: 'Texas and Washington need attention.',
    overall_risk_level: 'high',
    risk_flags: [
      {
        id: 'TX-1',
        title: 'Texas inventory',
        state: 'TX',
        category: 'physical_presence',
        risk_level: 'high',
        explanation: 'e',
        retrieved_evidence: [],
        tool_findings: [{ tool: 'analyze_sales_by_state', finding: 'TX revenue 620,000.00' }],
        recommended_human_action: 'Confirm.',
      },
      {
        id: 'WA-1',
        title: 'Washington remote employees',
        state: 'WA',
        category: 'economic_nexus',
        risk_level: 'medium',
        explanation: 'e',
        retrieved_evidence: [],
        tool_findings: [{ tool: 'analyze_sales_by_state', finding: 'WA transactions 250' }],
        recommended_human_action: 'Verify.',
      },
    ],
    states_reviewed_without_flags: ['CA', 'NY'],
  },
  decisions: [
    {
      review_id: 'rev_1',
      flag_id: 'WA-1',
      decision: 'accepted',
      reviewer_note: '',
      decided_at: '2026-09-11T11:00:00Z',
    },
  ],
}
