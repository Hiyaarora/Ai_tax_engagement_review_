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
    })
    render(<HomePage onOpen={vi.fn()} />)

    expect(await screen.findByText(/Acme Widgets LLC/)).toBeInTheDocument()
    expect(screen.getByText(/1 of 2 documents indexed/)).toBeInTheDocument()
    expect(screen.getByText('HIGH')).toBeInTheDocument()
    expect(screen.queryByText(/reference guidance/i)).not.toBeInTheDocument()
  })

  it('explains each field of the new-engagement form', async () => {
    mockApi({ 'GET /api/engagements': () => ({ body: [] }) })
    render(<HomePage onOpen={vi.fn()} />)
    expect(await screen.findByText(/Client or engagement name/)).toBeInTheDocument()
    expect(screen.getByText(/primary\/home state/)).toBeInTheDocument()
    expect(screen.getByText(/Tax period being reviewed/)).toBeInTheDocument()
  })

  it('deletes an engagement only after confirmation', async () => {
    const calls = mockApi({
      'GET /api/engagements': () => ({ body: [engagement] }),
      [`DELETE /api/engagements/${E}`]: () => ({ status: 204, body: null }),
    })
    const confirm = vi
      .spyOn(window, 'confirm')
      .mockReturnValueOnce(false)
      .mockReturnValueOnce(true)
    render(<HomePage onOpen={vi.fn()} />)

    await userEvent.click(await screen.findByRole('button', { name: /Delete/ }))
    expect(calls).not.toContain(`DELETE /api/engagements/${E}`)

    await userEvent.click(screen.getByRole('button', { name: /Delete/ }))
    expect(calls).toContain(`DELETE /api/engagements/${E}`)
    expect(confirm).toHaveBeenCalledTimes(2)
    expect(await screen.findByText(/No engagements yet/)).toBeInTheDocument()
  })

  it('creates an engagement and opens it', async () => {
    const onOpen = vi.fn()
    const calls = mockApi({
      'GET /api/engagements': () => ({ body: [] }),
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
})
