import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AskStep } from './AskStep'
import { engagement } from '../test-fixtures'
import { mockApi } from '../test-utils'
import type { AskResult } from '../types'

const E = engagement.engagement.engagement_id
const ready = { ...engagement, can_ask: true }

const answer: AskResult = {
  engagement_id: E,
  question: 'Does the company hold inventory in Texas?',
  answer: 'Yes - at a 3PL warehouse in Dallas (chunk_id: questionnaire-p1-c1).',
  found_in_documents: true,
  citations: [
    { chunk_id: 'questionnaire-p1-c1', source_name: 'questionnaire.pdf', page: 1, quote: '3PL warehouse in Dallas' },
  ],
  structured_evidence: [
    { tool: 'analyze_sales_by_state', source: 'sales.csv', finding: 'TX revenue 620,000.00' },
  ],
  tool_calls: ['analyze_sales_by_state'],
  passages: [
    {
      chunk_id: 'questionnaire-p1-c1',
      doc_id: 'questionnaire',
      doc_type: 'questionnaire',
      source_name: 'questionnaire.pdf',
      page: 1,
      excerpt: 'Physical presence | inventory_tx | Does the company hold inventory in Texas? | Yes | 3PL warehouse in Dallas',
      score: 0.03,
    },
    {
      chunk_id: 'salt_reference_guide-p1-c2',
      doc_id: 'salt_reference_guide',
      doc_type: 'reference',
      source_name: 'salt_reference_guide.pdf',
      page: 1,
      excerpt: '3. Registration and marketplace facilitators ...',
      score: 0.02,
    },
  ],
  citation_guard: {
    dropped_citations: ['ghost-p1-c0'],
    corrected_citations: [],
    unverified_quotes: [],
    dropped_tool_findings: [],
    flags_without_evidence: [],
  },
  model: 'gpt-4.1-mini',
  disclaimer: 'Decision support only - not tax advice.',
}

afterEach(() => vi.restoreAllMocks())

describe('AskStep', () => {
  it('is disabled until the backend says can_ask', () => {
    render(<AskStep detail={engagement} />)
    expect(screen.getByRole('button', { name: /^Ask$/ })).toBeDisabled()
    expect(screen.getByText(/index at least one document/i)).toBeInTheDocument()
  })

  it('asks a question and renders the answer, verified citations, passages and guard notes', async () => {
    const calls = mockApi({
      [`POST /api/engagements/${E}/ask`]: (init) => {
        expect(JSON.parse(String(init?.body))).toEqual({ question: 'Does the company hold inventory in Texas?' })
        return { body: answer }
      },
    })
    render(<AskStep detail={ready} />)

    await userEvent.type(screen.getByLabelText(/Question/), 'Does the company hold inventory in Texas?')
    await userEvent.click(screen.getByRole('button', { name: /^Ask$/ }))

    expect(await screen.findByText(/Yes - at a 3PL warehouse/)).toBeInTheDocument()
    const citations = screen.getByRole('region', { name: /Verified citations/ })
    expect(within(citations).getByText('questionnaire.pdf p.1')).toBeInTheDocument()
    expect(within(citations).getByText(/3PL warehouse in Dallas/)).toBeInTheDocument()
    const structured = screen.getByRole('region', { name: /Computed from client data/ })
    expect(within(structured).getByText(/TX revenue 620,000.00/)).toBeInTheDocument()
    expect(within(structured).getByText('sales.csv')).toBeInTheDocument()
    expect(within(citations).queryByText(/sales\.csv/)).not.toBeInTheDocument()
    const passages = screen.getByRole('region', { name: /Retrieved passages/ })
    expect(within(passages).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText(/1 citation removed/)).toBeInTheDocument()
    expect(calls).toContain(`POST /api/engagements/${E}/ask`)
  })

  it('flags answers the documents could not support', async () => {
    mockApi({
      [`POST /api/engagements/${E}/ask`]: () => ({
        body: {
          ...answer,
          found_in_documents: false,
          citations: [],
          structured_evidence: [],
          answer: 'The documents do not say.',
        },
      }),
    })
    render(<AskStep detail={ready} />)
    await userEvent.type(screen.getByLabelText(/Question/), 'Crypto policy?')
    await userEvent.click(screen.getByRole('button', { name: /^Ask$/ }))
    expect(await screen.findByText(/Not found in the documents/)).toBeInTheDocument()
  })

  it('shows backend errors', async () => {
    mockApi({
      [`POST /api/engagements/${E}/ask`]: () => ({ status: 502, body: { detail: 'answer error: boom' } }),
    })
    render(<AskStep detail={ready} />)
    await userEvent.type(screen.getByLabelText(/Question/), 'x')
    await userEvent.click(screen.getByRole('button', { name: /^Ask$/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/answer error: boom/)
  })
})
