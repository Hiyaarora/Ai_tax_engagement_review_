import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { RiskFlagCard } from './RiskFlagCard'
import type { RiskFlag } from '../types'

const flag: RiskFlag = {
  id: 'TX-PHYSICAL-PRESENCE',
  title: 'Inventory in Texas without registration',
  state: 'TX',
  category: 'physical_presence',
  risk_level: 'high',
  explanation: 'The 3PL inventory may create physical presence.',
  retrieved_evidence: [
    {
      chunk_id: 'questionnaire-p1-c1',
      source_name: 'questionnaire.pdf',
      page: 1,
      quote: 'Inventory is stored at a 3PL warehouse in Dallas, Texas.',
    },
    { chunk_id: 'locations-p1-c0', source_name: 'locations.docx', page: 1, quote: '' },
  ],
  tool_findings: [{ tool: 'analyze_sales_by_state', finding: 'TX revenue 620,000.00' }],
  recommended_human_action: 'Confirm the 3PL arrangement.',
}

describe('RiskFlagCard', () => {
  it('keeps retrieved evidence, computed results and AI analysis in separate labelled sections', () => {
    render(<RiskFlagCard flag={flag} decision={null} onDecide={vi.fn()} />)

    expect(screen.getByRole('heading', { name: /Inventory in Texas without registration/ })).toBeInTheDocument()
    expect(screen.getByText('HIGH')).toBeInTheDocument()

    const evidence = screen.getByRole('region', { name: /Retrieved evidence/ })
    expect(within(evidence).getByText('questionnaire.pdf p.1')).toBeInTheDocument()
    expect(within(evidence).getByText('locations.docx p.1')).toBeInTheDocument()
    expect(within(evidence).getByText(/Inventory is stored at a 3PL/)).toBeInTheDocument()
    expect(within(evidence).getByText(/quote not verified/i)).toBeInTheDocument()

    const computed = screen.getByRole('region', { name: /Computed from client data/ })
    expect(within(computed).getByText(/analyze_sales_by_state/)).toBeInTheDocument()
    expect(within(computed).getByText(/TX revenue 620,000.00/)).toBeInTheDocument()

    const analysis = screen.getByRole('region', { name: /AI analysis/ })
    expect(within(analysis).getByText(/3PL inventory may create/)).toBeInTheDocument()
    expect(within(analysis).queryByText(/620,000/)).not.toBeInTheDocument()

    expect(screen.getByText(/Confirm the 3PL arrangement/)).toBeInTheDocument()
  })

  it('records a reviewer decision with an optional note', async () => {
    const onDecide = vi.fn().mockResolvedValue(undefined)
    render(<RiskFlagCard flag={flag} decision={null} onDecide={onDecide} />)

    await userEvent.type(screen.getByLabelText(/Reviewer note/), 'Checked with client')
    await userEvent.click(screen.getByRole('button', { name: /Accept/ }))

    expect(onDecide).toHaveBeenCalledWith('TX-PHYSICAL-PRESENCE', 'accepted', 'Checked with client')
  })

  it('shows the recorded decision instead of the buttons', () => {
    render(
      <RiskFlagCard
        flag={flag}
        decision={{
          review_id: 'r',
          flag_id: flag.id,
          decision: 'rejected',
          reviewer_note: 'Not applicable',
          decided_at: '2026-09-11T10:00:00Z',
        }}
        onDecide={vi.fn()}
      />,
    )
    expect(screen.getByText(/Rejected/)).toBeInTheDocument()
    expect(screen.getByText(/Not applicable/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Accept/ })).not.toBeInTheDocument()
  })

  it('warns when a flag has no verified evidence at all', () => {
    render(
      <RiskFlagCard
        flag={{ ...flag, retrieved_evidence: [], tool_findings: [] }}
        decision={null}
        onDecide={vi.fn()}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(/no verified evidence/i)
  })
})
