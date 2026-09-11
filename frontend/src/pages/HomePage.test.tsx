import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HomePage } from './HomePage'
import { engagement, reviewSummary } from '../test-fixtures'
import { mockApi } from '../test-utils'

const E = engagement.engagement.engagement_id

afterEach(() => vi.restoreAllMocks())

describe('HomePage', () => {
  it('lists engagements with document and latest-review status', async () => {
    mockApi({
      'GET /api/engagements': () => ({
        body: [
          {
            ...engagement,
            documents: [{ status: 'indexed', kind: 'document' }, { status: 'uploaded', kind: 'document' }],
            can_ask: true,
            can_review: true,
            latest_review: reviewSummary({ status: 'done', overall_risk_level: 'high' }),
          },
        ],
      }),
      'GET /api/reference': () => ({ body: { indexed: true, status: 'indexed', chunks: 3, error: null } }),
    })
    render(<HomePage onOpen={vi.fn()} />)

    expect(await screen.findByText(/Acme Widgets LLC/)).toBeInTheDocument()
    expect(screen.getByText(/1 of 2 documents indexed/)).toBeInTheDocument()
    expect(screen.getByText('HIGH')).toBeInTheDocument()
    expect(await screen.findByText(/Reference guidance indexed/)).toBeInTheDocument()
  })

  it('creates an engagement and opens it', async () => {
    const onOpen = vi.fn()
    const calls = mockApi({
      'GET /api/engagements': () => ({ body: [] }),
      'GET /api/reference': () => ({ body: { indexed: false, status: 'not_indexed', chunks: 0, error: null } }),
      'POST /api/engagements': (init) => {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>
        expect(body).toEqual({ company_name: 'Beta Corp', home_state: 'WA', tax_year: 2025 })
        return { status: 201, body: engagement }
      },
    })
    render(<HomePage onOpen={onOpen} />)

    await userEvent.type(await screen.findByLabelText(/Company/), 'Beta Corp')
    await userEvent.selectOptions(screen.getByLabelText(/Home state/), 'WA')
    await userEvent.clear(screen.getByLabelText(/Tax year/))
    await userEvent.type(screen.getByLabelText(/Tax year/), '2025')
    await userEvent.click(screen.getByRole('button', { name: /Create engagement/ }))

    expect(onOpen).toHaveBeenCalledWith(E)
    expect(calls).toContain('POST /api/engagements')
  })

  it('offers to index the reference guidance when it is missing', async () => {
    mockApi({
      'GET /api/engagements': () => ({ body: [] }),
      'GET /api/reference': () => ({ body: { indexed: false, status: 'not_indexed', chunks: 0, error: null } }),
      'POST /api/reference/index': () => ({ status: 202, body: { status: 'processing' } }),
    })
    render(<HomePage onOpen={vi.fn()} />)

    await userEvent.click(await screen.findByRole('button', { name: /Index reference guidance/ }))

    expect(await screen.findByText(/Indexing reference guidance/)).toBeInTheDocument()
  })
})
