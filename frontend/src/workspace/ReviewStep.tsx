import { useState } from 'react'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import type { EngagementDetail, ReviewSummary } from '../types'

interface Props {
  detail: EngagementDetail
  reviews: ReviewSummary[]
  onChanged: () => void
  onOpenFindings: (reviewId: string) => void
}

export function ReviewStep({ detail, reviews, onChanged, onOpenFindings }: Props) {
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const inFlight = reviews.some((r) => r.status === 'queued' || r.status === 'running')

  async function run() {
    setBusy(true)
    setError(null)
    try {
      const queued = await api.runReview(detail.engagement.engagement_id)
      setNotice(`Review ${queued.review_id} queued — the agent usually takes 30–90 seconds.`)
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <div className="card">
        <h3>Run engagement review</h3>
        <p className="muted small">
          The Foundry agent calls the deterministic tools (sales by state, threshold checks,
          locations, questionnaire) and retrieves evidence from the indexed documents, then returns
          structured findings. Every citation is verified by the backend before you see it.
        </p>
        <div className="button-row">
          <button className="primary" onClick={run} disabled={!detail.can_review || busy || inFlight}>
            Run review
          </button>
          {!detail.can_review && (
            <span className="muted small">Index at least one document first (Documents step).</span>
          )}
          {inFlight && <span className="muted small">A review is already in progress.</span>}
        </div>
        {notice && <p className="status">{notice}</p>}
        {error && <p role="alert">{error}</p>}
      </div>

      <h3>Reviews</h3>
      {reviews.length === 0 ? (
        <p className="muted">No reviews yet.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Review</th>
              <th>Started</th>
              <th>Status</th>
              <th>Overall risk</th>
              <th>Flags</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {reviews.map((r) => (
              <tr key={r.review_id}>
                <td>
                  <code>{r.review_id}</code>
                </td>
                <td>{new Date(r.created_at).toLocaleString()}</td>
                <td>
                  <StatusBadge status={r.status} />
                  {r.status === 'failed' && r.error && (
                    <div className="error-text small">{r.error}</div>
                  )}
                </td>
                <td>{r.overall_risk_level ? <StatusBadge status={r.overall_risk_level} /> : '—'}</td>
                <td>{r.status === 'done' ? r.flag_count : '—'}</td>
                <td>
                  {r.status === 'done' && (
                    <button className="link" onClick={() => onOpenFindings(r.review_id)}>
                      View findings
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
