import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { usePolling } from '../hooks/usePolling'
import type { EngagementDetail, ReferenceStatus } from '../types'

const US_STATES = [
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA', 'HI', 'ID', 'IL', 'IN', 'IA', 'KS',
  'KY', 'LA', 'ME', 'MD', 'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ', 'NM', 'NY',
  'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV',
  'WI', 'WY', 'DC',
]

interface Props {
  onOpen: (engagementId: string) => void
}

export function HomePage({ onOpen }: Props) {
  const [engagements, setEngagements] = useState<EngagementDetail[] | null>(null)
  const [reference, setReference] = useState<ReferenceStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [company, setCompany] = useState('')
  const [homeState, setHomeState] = useState('CO')
  const [taxYear, setTaxYear] = useState(String(new Date().getFullYear() - 1))
  const [creating, setCreating] = useState(false)

  const load = useCallback(() => {
    api.listEngagements().then(setEngagements).catch((e: Error) => setError(e.message))
    api.referenceStatus().then(setReference).catch(() => setReference(null))
  }, [])

  useEffect(load, [load])
  usePolling(load, reference?.status === 'processing', 2000)

  async function create(event: FormEvent) {
    event.preventDefault()
    setCreating(true)
    setError(null)
    try {
      const detail = await api.createEngagement({
        company_name: company.trim(),
        home_state: homeState,
        tax_year: Number(taxYear),
      })
      onOpen(detail.engagement.engagement_id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setCreating(false)
    }
  }

  async function indexReference() {
    try {
      await api.indexReference()
      setReference((r) => (r ? { ...r, status: 'processing', indexed: false } : r))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  return (
    <div className="home">
      <section className="card">
        <h2>New engagement</h2>
        <form onSubmit={create} className="form">
          <label>
            Company
            <input value={company} onChange={(e) => setCompany(e.target.value)} required />
          </label>
          <label>
            Home state
            <select value={homeState} onChange={(e) => setHomeState(e.target.value)}>
              {US_STATES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
          <label>
            Tax year
            <input
              type="number"
              min={2000}
              max={2100}
              value={taxYear}
              onChange={(e) => setTaxYear(e.target.value)}
              required
            />
          </label>
          <button className="primary" type="submit" disabled={creating || !company.trim()}>
            Create engagement
          </button>
        </form>
      </section>

      <section className="card">
        <h2>Engagements</h2>
        {error && <p role="alert">{error}</p>}
        {engagements === null ? (
          <p className="muted">Loading…</p>
        ) : engagements.length === 0 ? (
          <p className="muted">No engagements yet — create one above.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Client</th>
                <th>Year</th>
                <th>Documents</th>
                <th>Latest review</th>
              </tr>
            </thead>
            <tbody>
              {engagements.map((d) => {
                const docs = d.documents.filter((x) => x.kind === 'document')
                const indexed = docs.filter((x) => x.status === 'indexed').length
                return (
                  <tr key={d.engagement.engagement_id}>
                    <td>
                      <button className="link" onClick={() => onOpen(d.engagement.engagement_id)}>
                        {d.engagement.company_name}
                      </button>
                      <div className="muted small">{d.engagement.engagement_id}</div>
                    </td>
                    <td>{d.engagement.tax_year}</td>
                    <td>
                      {indexed} of {docs.length} documents indexed
                    </td>
                    <td>
                      {d.latest_review ? (
                        d.latest_review.status === 'done' && d.latest_review.overall_risk_level ? (
                          <StatusBadge status={d.latest_review.overall_risk_level} />
                        ) : (
                          <StatusBadge status={d.latest_review.status} />
                        )
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="card card--quiet">
        <h3>Shared reference guidance</h3>
        {reference === null ? (
          <p className="muted">Status unavailable.</p>
        ) : reference.status === 'processing' ? (
          <p>Indexing reference guidance…</p>
        ) : reference.indexed ? (
          <p>
            Reference guidance indexed ({reference.chunks} passages). The synthetic SALT guide is
            searchable in every engagement.
          </p>
        ) : (
          <p>
            {reference.status === 'failed' ? (
              <span role="alert">Indexing failed: {reference.error} </span>
            ) : (
              <>The synthetic SALT reference guide is not indexed yet. </>
            )}
            <button onClick={indexReference}>Index reference guidance</button>
          </p>
        )}
      </section>
    </div>
  )
}
