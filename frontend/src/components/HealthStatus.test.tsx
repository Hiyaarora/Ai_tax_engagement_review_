import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HealthStatus } from './HealthStatus'
import type { HealthResponse } from '../types'

const healthy: HealthResponse = {
  status: 'ok',
  service: 'fd-tax-review-backend',
  version: '0.1.0',
  environment: 'development',
  azure: { foundry: true, search: false, document_intelligence: false },
}

afterEach(() => vi.restoreAllMocks())

describe('HealthStatus', () => {
  it('renders backend status and per-service configuration', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(healthy), { status: 200 }),
    )
    render(<HealthStatus />)
    expect(await screen.findByText(/fd-tax-review-backend v0.1.0/)).toBeInTheDocument()
    expect(screen.getByText(/Microsoft Foundry: configured/)).toBeInTheDocument()
    expect(screen.getByText(/Azure AI Search: not configured/)).toBeInTheDocument()
  })

  it('shows an error when the backend is unreachable', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('Failed to fetch'))
    render(<HealthStatus />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/Backend unreachable/)
  })
})
