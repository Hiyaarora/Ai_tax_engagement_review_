import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EngagementPage } from './EngagementPage'
import { mockApi } from '../test-utils'
import type { EngagementSummary, ReviewResult, ReviewSummary } from '../types'

const engagement: EngagementSummary = {
  engagement_id: 'acme-2025',
  company_name: 'Acme Widgets LLC',
  home_state: 'CO',
  tax_year: 2025,
  documents: ['locations.docx', 'questionnaire.pdf'],
}

const pastReview: ReviewSummary = {
  review_id: 'rev_old',
  engagement_id: 'acme-2025',
  created_at: '2026-09-11T09:00:00Z',
  overall_risk_level: 'medium',
  flag_count: 3,
  model: 'gpt-4.1-mini',
}

const newReview = {
  review_id: 'rev_new',
  engagement_id: 'acme-2025',
  overall_risk_level: 'high',
  risk_flags: [],
} as unknown as ReviewResult

afterEach(() => vi.restoreAllMocks())

describe('EngagementPage', () => {
  it('lists the engagement, its documents and past reviews', async () => {
    mockApi({
      'GET /api/engagements': () => ({ body: [engagement] }),
      'GET /api/engagements/acme-2025/reviews': () => ({ body: [pastReview] }),
    })
    render(<EngagementPage onOpenReview={vi.fn()} />)

    expect(await screen.findByText(/Acme Widgets LLC/)).toBeInTheDocument()
    expect(screen.getByText(/questionnaire\.pdf/)).toBeInTheDocument()
    expect(await screen.findByText(/rev_old/)).toBeInTheDocument()
    expect(screen.getByText(/3 flags/)).toBeInTheDocument()
  })

  it('runs a review, shows progress, then opens the result', async () => {
    const onOpenReview = vi.fn()
    mockApi({
      'GET /api/engagements': () => ({ body: [engagement] }),
      'GET /api/engagements/acme-2025/reviews': () => ({ body: [] }),
      'POST /api/engagements/acme-2025/reviews': () =>
        new Promise((resolve) => setTimeout(() => resolve({ status: 201, body: newReview }), 50)),
    })
    render(<EngagementPage onOpenReview={onOpenReview} />)

    await userEvent.click(await screen.findByRole('button', { name: /Run review/ }))

    expect(await screen.findByText(/Running the review agent/)).toBeInTheDocument()
    expect(await screen.findByText(/Review complete/)).toBeInTheDocument()
    expect(onOpenReview).toHaveBeenCalledWith('rev_new')
  })

  it('surfaces the backend error when the agent fails', async () => {
    mockApi({
      'GET /api/engagements': () => ({ body: [engagement] }),
      'GET /api/engagements/acme-2025/reviews': () => ({ body: [] }),
      'POST /api/engagements/acme-2025/reviews': () => ({
        status: 502,
        body: { detail: 'review agent error: agent response r1 failed' },
      }),
    })
    render(<EngagementPage onOpenReview={vi.fn()} />)

    await userEvent.click(await screen.findByRole('button', { name: /Run review/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/agent response r1 failed/)
  })
})
