import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import { usePolling } from '../hooks/usePolling'
import type { EngagementDetail, ReviewSummary } from '../types'
import { AskStep } from '../workspace/AskStep'
import { DocumentsStep } from '../workspace/DocumentsStep'
import { FindingsView } from '../workspace/FindingsView'
import { ReviewStep } from '../workspace/ReviewStep'

export type Step = 'documents' | 'ask' | 'review' | 'findings'

interface Props {
  engagementId: string
  step: Step
  reviewId?: string
  onNavigate: (step: Step, reviewId?: string) => void
  onHome: () => void
}

const STEPS: { key: Step; label: string; n: number }[] = [
  { key: 'documents', label: 'Upload & process', n: 1 },
  { key: 'ask', label: 'Ask agent', n: 2 },
  { key: 'review', label: 'Run review', n: 3 },
  { key: 'findings', label: 'Evidence & findings', n: 4 },
]

/**
 * One engagement, four steps. Readiness (which steps are enabled) comes from the backend's
 * can_ask / can_review; the page polls while documents or reviews are in flight.
 */
export function WorkspacePage({ engagementId, step, reviewId, onNavigate, onHome }: Props) {
  const [detail, setDetail] = useState<EngagementDetail | null>(null)
  const [reviews, setReviews] = useState<ReviewSummary[]>([])
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    api.getEngagement(engagementId).then(setDetail).catch((e: Error) => setError(e.message))
    api.listReviews(engagementId).then(setReviews).catch(() => undefined)
  }, [engagementId])

  useEffect(load, [load])

  const processing = detail?.documents.some((d) => d.status === 'processing') ?? false
  const reviewing = reviews.some((r) => r.status === 'queued' || r.status === 'running')
  usePolling(load, processing || reviewing, 2500)

  if (error) return <p role="alert">{error}</p>
  if (!detail) return <p className="muted">Loading engagement…</p>

  const docs = detail.documents.filter((d) => d.kind === 'document')
  const indexed = docs.filter((d) => d.status === 'indexed').length
  const latestDone = reviews.find((r) => r.status === 'done')
  const enabled: Record<Step, boolean> = {
    documents: true,
    ask: detail.can_ask,
    review: detail.can_review,
    findings: reviews.length > 0,
  }

  return (
    <div className="workspace">
      <button className="link" onClick={onHome}>
        ← All engagements
      </button>
      <header className="workspace__header">
        <div>
          <h2>
            {detail.engagement.company_name}{' '}
            <span className="muted">· {detail.engagement.tax_year}</span>
          </h2>
          <p className="muted small">
            <code>{detail.engagement.engagement_id}</code> · home state {detail.engagement.home_state}
          </p>
        </div>
        <dl className="workspace__stats">
          <div>
            <dt>Documents</dt>
            <dd>
              {indexed} / {docs.length} indexed
              {processing && <StatusBadge status="processing" />}
            </dd>
          </div>
          <div>
            <dt>Latest review</dt>
            <dd>
              {detail.latest_review ? (
                detail.latest_review.status === 'done' && detail.latest_review.overall_risk_level ? (
                  <StatusBadge status={detail.latest_review.overall_risk_level} />
                ) : (
                  <StatusBadge status={detail.latest_review.status} />
                )
              ) : (
                '—'
              )}
            </dd>
          </div>
        </dl>
      </header>

      <nav className="steps" aria-label="Workflow">
        {STEPS.map((s) => (
          <button
            key={s.key}
            className={`step${step === s.key ? ' step--active' : ''}`}
            disabled={!enabled[s.key]}
            aria-current={step === s.key ? 'step' : undefined}
            onClick={() => onNavigate(s.key, s.key === 'findings' ? (reviewId ?? latestDone?.review_id) : undefined)}
          >
            <span className="step__n">{s.n}</span> {s.label}
          </button>
        ))}
      </nav>

      {step === 'documents' && <DocumentsStep detail={detail} onChanged={load} />}
      {step === 'ask' && <AskStep detail={detail} />}
      {step === 'review' && (
        <ReviewStep
          detail={detail}
          reviews={reviews}
          onChanged={load}
          onOpenFindings={(id) => onNavigate('findings', id)}
        />
      )}
      {step === 'findings' &&
        (reviewId ?? latestDone?.review_id ? (
          <FindingsView reviewId={reviewId ?? latestDone!.review_id} />
        ) : (
          <p className="muted">No completed review yet — run one in step 3.</p>
        ))}
    </div>
  )
}
