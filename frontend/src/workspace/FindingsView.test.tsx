import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { FindingsView } from './FindingsView'
import { doneReview } from '../test-fixtures'
import { mockApi } from '../test-utils'

afterEach(() => vi.restoreAllMocks())

describe('FindingsView', () => {
  it('renders summary, guard notes, flags, decisions and unflagged states', async () => {
    mockApi({ 'GET /api/reviews/rev_1': () => ({ body: doneReview }) })
    render(<FindingsView reviewId="rev_1" />)

    expect(await screen.findByText(/Texas and Washington need attention/)).toBeInTheDocument()
    expect(screen.getByText(/1 citation removed/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /Texas inventory/ })).toBeInTheDocument()
    expect(screen.getByText(/Accepted/)).toBeInTheDocument()
    expect(screen.getByText(/CA, NY/)).toBeInTheDocument()
    expect(screen.getByText(/1 of 2 flags decided/)).toBeInTheDocument()
    expect(screen.getByText(/not a definitive tax determination/i)).toBeInTheDocument()
  })

  it('records a decision and updates the counter', async () => {
    mockApi({
      'GET /api/reviews/rev_1': () => ({ body: doneReview }),
      'PATCH /api/reviews/rev_1/flags/TX-1': (init) => ({
        body: {
          review_id: 'rev_1',
          flag_id: 'TX-1',
          ...(JSON.parse(String(init?.body)) as object),
          decided_at: '2026-09-11T12:00:00Z',
        },
      }),
    })
    render(<FindingsView reviewId="rev_1" />)
    await screen.findByText(/1 of 2 flags decided/)

    await userEvent.click(screen.getByRole('button', { name: /Reject/ }))

    expect(await screen.findByText(/2 of 2 flags decided/)).toBeInTheDocument()
  })

  it('shows progress for a running review and polls until done', async () => {
    let polls = 0
    mockApi({
      'GET /api/reviews/rev_1': () => {
        polls += 1
        return polls < 2 ? { body: { ...doneReview, status: 'running', review: null, decisions: [] } } : { body: doneReview }
      },
    })
    render(<FindingsView reviewId="rev_1" pollMs={20} />)

    expect(await screen.findByText(/Review is running/)).toBeInTheDocument()
    expect(await screen.findByText(/Texas and Washington need attention/)).toBeInTheDocument()
  })

  it('shows the error for a failed review', async () => {
    mockApi({
      'GET /api/reviews/rev_1': () => ({
        body: { ...doneReview, status: 'failed', error: 'ReviewParseError: bad json', review: null, decisions: [] },
      }),
    })
    render(<FindingsView reviewId="rev_1" />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/ReviewParseError: bad json/)
  })
})
