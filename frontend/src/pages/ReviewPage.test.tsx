import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReviewPage } from './ReviewPage'
import { mockApi } from '../test-utils'
import type { ReviewDetail } from '../types'

const detail: ReviewDetail = {
  review: {
    review_id: 'rev_1',
    engagement_id: 'acme-2025',
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
    { review_id: 'rev_1', flag_id: 'WA-1', decision: 'accepted', reviewer_note: '', decided_at: '2026-09-11T11:00:00Z' },
  ],
}

afterEach(() => vi.restoreAllMocks())

describe('ReviewPage', () => {
  it('renders summary, guard notes, flags, existing decisions and unflagged states', async () => {
    mockApi({ 'GET /api/reviews/rev_1': () => ({ body: detail }) })
    render(<ReviewPage reviewId="rev_1" onBack={vi.fn()} />)

    expect(await screen.findByText(/Texas and Washington need attention/)).toBeInTheDocument()
    expect(screen.getByText(/1 citation removed/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Texas inventory/ })).toBeInTheDocument()
    expect(screen.getByText(/Accepted/)).toBeInTheDocument() // WA decision already recorded
    expect(screen.getByText(/CA, NY/)).toBeInTheDocument()
    expect(screen.getByText(/1 of 2 flags decided/)).toBeInTheDocument()
  })

  it('records a decision and updates the progress counter', async () => {
    const calls = mockApi({
      'GET /api/reviews/rev_1': () => ({ body: detail }),
      'PATCH /api/reviews/rev_1/flags/TX-1': (init) => ({
        body: {
          review_id: 'rev_1',
          flag_id: 'TX-1',
          ...(JSON.parse(String(init?.body)) as object),
          decided_at: '2026-09-11T12:00:00Z',
        },
      }),
    })
    render(<ReviewPage reviewId="rev_1" onBack={vi.fn()} />)
    await screen.findByText(/1 of 2 flags decided/)

    await userEvent.click(screen.getByRole('button', { name: /Reject/ }))

    expect(await screen.findByText(/2 of 2 flags decided/)).toBeInTheDocument()
    expect(calls).toContain('PATCH /api/reviews/rev_1/flags/TX-1')
  })

  it('shows an error for an unknown review', async () => {
    mockApi({ 'GET /api/reviews/rev_x': () => ({ status: 404, body: { detail: 'unknown review rev_x' } }) })
    render(<ReviewPage reviewId="rev_x" onBack={vi.fn()} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/unknown review/)
  })
})
