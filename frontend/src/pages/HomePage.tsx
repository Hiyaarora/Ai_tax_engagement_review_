import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import type { EngagementDetail } from '../types'

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
  const [error, setError] = useState<string | null>(null)
  const [company, setCompany] = useState('')
  const [homeState, setHomeState] = useState('CO')
  const [taxYear, setTaxYear] = useState(String(new Date().getFullYear() - 1))
  const [creating, setCreating] = useState(false)
  const [deleting, setDeleting] = useState<string | null>(null)

  const load = useCallback(() => {
    api.listEngagements().then(setEngagements).catch((e: Error) => setError(e.message))
  }, [])

  useEffect(load, [load])

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

  async function remove(detail: EngagementDetail) {
    const { engagement_id, company_name, tax_year } = detail.engagement
    const ok = window.confirm(
      `Delete "${company_name} — ${tax_year}"?\n\nThis removes its uploaded files, indexed passages, reviews and decisions. This cannot be undone.`,
    )
    if (!ok) return
    setDeleting(engagement_id)
    setError(null)
    try {
      await api.deleteEngagement(engagement_id)
      setEngagements((list) => list?.filter((e) => e.engagement.engagement_id !== engagement_id) ?? list)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div className="home">
      <section className="card">
        <h2>New engagement</h2>
        <form onSubmit={create} className="form">
          <label>
            Company
            <input
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              required
              aria-describedby="help-company"
            />
            <span id="help-company" className="help">
              Client or engagement name.
            </span>
          </label>
          <label>
            Home state
            <select
              value={homeState}
              onChange={(e) => setHomeState(e.target.value)}
              aria-describedby="help-state"
            >
              {US_STATES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
            <span id="help-state" className="help">
              Client’s primary/home state. Used as context for the tax review.
            </span>
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
              aria-describedby="help-year"
            />
            <span id="help-year" className="help">
              Tax period being reviewed.
            </span>
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
                <th></th>
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
                    <td className="table__actions">
                      <button
                        className="danger"
                        onClick={() => remove(d)}
                        disabled={deleting === d.engagement.engagement_id}
                        aria-label={`Delete ${d.engagement.company_name} ${d.engagement.tax_year}`}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
