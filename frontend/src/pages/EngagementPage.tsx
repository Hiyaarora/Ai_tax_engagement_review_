import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { EngagementSummary, ReviewSummary } from '../types'

interface Props {
  onOpenReview: (reviewId: string) => void
}

type RunState =
  | { kind: 'idle' }
  | { kind: 'running'; startedAt: number }
  | { kind: 'done'; reviewId: string }
  | { kind: 'error'; message: string }

export function EngagementPage({ onOpenReview }: Props) {
  const [engagements, setEngagements] = useState<EngagementSummary[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [reviews, setReviews] = useState<ReviewSummary[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [run, setRun] = useState<RunState>({ kind: 'idle' })

  useEffect(() => {
    api
      .listEngagements()
      .then((list) => {
        setEngagements(list)
        setSelected(list[0]?.engagement_id ?? null)
      })
      .catch((err: Error) => setLoadError(err.message))
  }, [])

  const refreshReviews = useCallback(() => {
    if (!selected) return
    api
      .listReviews(selected)
      .then(setReviews)
      .catch((err: Error) => setLoadError(err.message))
  }, [selected])

  useEffect(refreshReviews, [refreshReviews])

  async function runReview() {
    if (!selected) return
    setRun({ kind: 'running', startedAt: Date.now() })
    try {
      const result = await api.runReview(selected)
      setRun({ kind: 'done', reviewId: result.review_id })
      refreshReviews()
      onOpenReview(result.review_id)
    } catch (err) {
      setRun({ kind: 'error', message: (err as Error).message })
    }
  }

  if (loadError) return <p role="alert">{loadError}</p>
  if (!engagements) return <p>Loading engagements…</p>
  const engagement = engagements.find((e) => e.engagement_id === selected)

  return (
    <section>
      <h2>Engagements</h2>
      <ul className="engagements">
        {engagements.map((e) => (
          <li key={e.engagement_id}>
            <button
              className={e.engagement_id === selected ? 'link link--active' : 'link'}
              onClick={() => setSelected(e.engagement_id)}
            >
              {e.company_name} — {e.tax_year}
            </button>
          </li>
        ))}
      </ul>

      {engagement && (
        <>
          <dl className="facts">
            <dt>Engagement</dt>
            <dd>{engagement.engagement_id}</dd>
            <dt>Home state</dt>
            <dd>{engagement.home_state}</dd>
            <dt>Indexed documents</dt>
            <dd>{engagement.documents.join(', ') || 'none'}</dd>
          </dl>

          <div className="run">
            <button className="primary" onClick={runReview} disabled={run.kind === 'running'}>
              Run review
            </button>
            {run.kind === 'running' && (
              <p className="status">
                Running the review agent — retrieving evidence and computing figures. This usually
                takes 30–90 seconds.
              </p>
            )}
            {run.kind === 'done' && <p className="status">Review complete: {run.reviewId}</p>}
            {run.kind === 'error' && <p role="alert">{run.message}</p>}
          </div>

          <h3>Past reviews</h3>
          {reviews.length === 0 ? (
            <p className="muted">No reviews yet.</p>
          ) : (
            <table className="reviews">
              <thead>
                <tr>
                  <th>Review</th>
                  <th>When</th>
                  <th>Overall risk</th>
                  <th>Flags</th>
                </tr>
              </thead>
              <tbody>
                {reviews.map((r) => (
                  <tr key={r.review_id}>
                    <td>
                      <button className="link" onClick={() => onOpenReview(r.review_id)}>
                        {r.review_id}
                      </button>
                    </td>
                    <td>{new Date(r.created_at).toLocaleString()}</td>
                    <td>
                      <span className={`badge badge--${r.overall_risk_level}`}>
                        {r.overall_risk_level.toUpperCase()}
                      </span>
                    </td>
                    <td>{r.flag_count} flags</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  )
}
