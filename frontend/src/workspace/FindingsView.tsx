import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { RiskFlagCard } from '../components/RiskFlagCard'
import { StatusBadge } from '../components/StatusBadge'
import { usePolling } from '../hooks/usePolling'
import type { CitationGuardReport, Decision, FlagDecision, ReviewDetail } from '../types'

interface Props {
  reviewId: string
  pollMs?: number
}

function guardNotes(report: CitationGuardReport): string[] {
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`
  const notes: string[] = []
  if (report.dropped_citations.length)
    notes.push(`${plural(report.dropped_citations.length, 'citation')} removed (never retrieved)`)
  if (report.corrected_citations.length)
    notes.push(`${plural(report.corrected_citations.length, 'citation')} corrected to the indexed source/page`)
  if (report.unverified_quotes.length)
    notes.push(`${plural(report.unverified_quotes.length, 'quote')} cleared (not verbatim in the passage)`)
  if (report.dropped_tool_findings.length)
    notes.push(`${plural(report.dropped_tool_findings.length, 'tool finding')} removed (tool not called)`)
  if (report.flags_without_evidence.length)
    notes.push(`${plural(report.flags_without_evidence.length, 'flag')} left with no verified evidence`)
  return notes
}

/** Findings for one review. Polls while the review is queued/running, then renders the result. */
export function FindingsView({ reviewId, pollMs = 3000 }: Props) {
  const [detail, setDetail] = useState<ReviewDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.getReview(reviewId).then(setDetail).catch((e: Error) => setError(e.message))
  }, [reviewId])

  useEffect(load, [load])
  usePolling(load, detail?.status === 'queued' || detail?.status === 'running', pollMs)

  async function decide(flagId: string, decision: Decision, note: string) {
    const saved: FlagDecision = await api.decideFlag(reviewId, flagId, decision, note)
    setDetail((current) =>
      current
        ? { ...current, decisions: [...current.decisions.filter((d) => d.flag_id !== flagId), saved] }
        : current,
    )
  }

  if (error) return <p role="alert">{error}</p>
  if (!detail) return <p className="muted">Loading review…</p>
  if (detail.status === 'failed') {
    return (
      <p role="alert">
        Review {detail.review_id} failed: {detail.error}
      </p>
    )
  }
  if (detail.status !== 'done' || !detail.review) {
    return (
      <p className="status">
        <StatusBadge status={detail.status} /> Review is {detail.status} — retrieving evidence and
        computing figures. This page updates automatically.
      </p>
    )
  }

  const { review, decisions } = detail
  const notes = guardNotes(review.citation_guard)

  return (
    <section>
      <header className="review__header">
        <h3>
          Findings for <code>{review.review_id}</code>{' '}
          <StatusBadge status={review.overall_risk_level} />
        </h3>
        <p className="muted small">
          {new Date(review.created_at).toLocaleString()} · {review.model} via {review.agent_name} ·
          tools: {review.tool_calls.join(', ')}
        </p>
      </header>

      <p className="summary">{review.overall_summary}</p>

      <p className="progress">
        <strong>
          {decisions.length} of {review.risk_flags.length} flags decided
        </strong>{' '}
        — every flag needs a reviewer decision before this review is complete.
      </p>

      <aside className="guard">
        <h4>Citation guard</h4>
        {notes.length === 0 ? (
          <p>Every citation and tool finding the agent used was verified against this run.</p>
        ) : (
          <ul>
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </aside>

      {review.risk_flags.map((flag) => (
        <RiskFlagCard
          key={flag.id}
          flag={flag}
          decision={decisions.find((d) => d.flag_id === flag.id) ?? null}
          onDecide={decide}
        />
      ))}

      <p className="muted">
        Reviewed without flags: {review.states_reviewed_without_flags.join(', ') || '—'}
      </p>
      <p className="disclaimer">{review.disclaimer}</p>
    </section>
  )
}
