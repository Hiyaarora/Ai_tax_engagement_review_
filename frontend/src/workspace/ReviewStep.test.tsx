import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ReviewStep } from './ReviewStep'
import { engagement, reviewSummary } from '../test-fixtures'
import { mockApi } from '../test-utils'

const E = engagement.engagement.engagement_id

afterEach(() => vi.restoreAllMocks())

describe('ReviewStep', () => {
  it('explains why review is unavailable until a document is indexed', () => {
    render(<ReviewStep detail={engagement} reviews={[]} onChanged={vi.fn()} onOpenFindings={vi.fn()} />)
    expect(screen.getByRole('button', { name: /Run review/ })).toBeDisabled()
    expect(screen.getByText(/index at least one document/i)).toBeInTheDocument()
  })

  it('queues a review and lists it with its status', async () => {
    const onChanged = vi.fn()
    mockApi({
      [`POST /api/engagements/${E}/reviews`]: () => ({ status: 202, body: { review_id: 'rev_9', status: 'queued' } }),
    })
    render(
      <ReviewStep
        detail={{ ...engagement, can_review: true }}
        reviews={[reviewSummary({ review_id: 'rev_old', status: 'done' })]}
        onChanged={onChanged}
        onOpenFindings={vi.fn()}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /Run review/ }))

    expect(onChanged).toHaveBeenCalled()
    expect(await screen.findByText(/Review rev_9 queued/)).toBeInTheDocument()
  })

  it('blocks a second run while one is in progress', () => {
    render(
      <ReviewStep
        detail={{ ...engagement, can_review: true }}
        reviews={[reviewSummary({ review_id: 'rev_running', status: 'running', overall_risk_level: null, flag_count: 0 })]}
        onChanged={vi.fn()}
        onOpenFindings={vi.fn()}
      />,
    )
    expect(screen.getByText('Running…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Run review/ })).toBeDisabled()
  })

  it('opens findings for a completed review and shows failures', async () => {
    const onOpenFindings = vi.fn()
    render(
      <ReviewStep
        detail={{ ...engagement, can_review: true }}
        reviews={[
          reviewSummary({ review_id: 'rev_done', status: 'done', overall_risk_level: 'high', flag_count: 3 }),
          reviewSummary({ review_id: 'rev_bad', status: 'failed', error: 'AgentRunError: max_turns', overall_risk_level: null, flag_count: 0 }),
        ]}
        onChanged={vi.fn()}
        onOpenFindings={onOpenFindings}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /View findings/ }))
    expect(onOpenFindings).toHaveBeenCalledWith('rev_done')
    expect(screen.getByText(/AgentRunError: max_turns/)).toBeInTheDocument()
  })
})
