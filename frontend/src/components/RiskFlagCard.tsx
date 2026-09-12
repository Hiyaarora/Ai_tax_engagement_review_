import { useState } from 'react'
import type { Decision, FlagDecision, RiskFlag } from '../types'

interface Props {
  flag: RiskFlag
  decision: FlagDecision | null
  onDecide: (flagId: string, decision: Decision, reviewerNote: string) => Promise<void> | void
}

const DECISION_LABELS: Record<Decision, string> = {
  accepted: 'Accepted',
  rejected: 'Rejected',
  needs_more_info: 'Needs more info',
}

const CATEGORY_LABELS: Record<RiskFlag['category'], string> = {
  physical_presence: 'Physical presence',
  economic_nexus: 'Economic nexus',
  registration: 'Registration',
  data_inconsistency: 'Data inconsistency',
  other: 'Other',
}

/**
 * One risk flag. The three kinds of information are rendered as separate labelled regions so a
 * reviewer never mistakes the model's analysis for a retrieved fact or a computed figure.
 */
export function RiskFlagCard({ flag, decision, onDecide }: Props) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const hasEvidence = flag.retrieved_evidence.length > 0 || flag.tool_findings.length > 0

  async function decide(value: Decision) {
    setBusy(true)
    setError(null)
    try {
      await onDecide(flag.id, value, note)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const headingId = `flag-${flag.id}`

  return (
    <article className={`flag flag--${flag.risk_level}`} aria-labelledby={headingId}>
      <header className="flag__header">
        <span className={`badge badge--${flag.risk_level}`}>{flag.risk_level.toUpperCase()}</span>
        <h3 id={headingId}>
          {flag.state ? `${flag.state} · ` : ''}
          {flag.title}
        </h3>
        <span className="flag__category">Potential nexus risk · {CATEGORY_LABELS[flag.category]}</span>
      </header>

      {!hasEvidence && (
        <p role="alert" className="flag__warning">
          This flag has no verified evidence — the citation guard removed everything the agent
          cited. Treat it as an unsupported hypothesis.
        </p>
      )}

      <section aria-labelledby={`${headingId}-evidence`} className="flag__section">
        <h4 id={`${headingId}-evidence`}>Retrieved evidence</h4>
        {flag.retrieved_evidence.length === 0 ? (
          <p className="muted">None retrieved.</p>
        ) : (
          <ul className="evidence">
            {flag.retrieved_evidence.map((c, i) => (
              <li key={`${c.chunk_id}-${i}`}>
                <span className="evidence__source">
                  {c.source_name} p.{c.page}
                </span>{' '}
                <code className="evidence__chunk">{c.chunk_id}</code>
                {c.quote ? (
                  <blockquote>“{c.quote}”</blockquote>
                ) : (
                  <p className="muted">(quote not verified against the passage — open the source)</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby={`${headingId}-computed`} className="flag__section">
        <h4 id={`${headingId}-computed`}>Computed from client data</h4>
        {flag.tool_findings.length === 0 ? (
          <p className="muted">No deterministic results referenced.</p>
        ) : (
          <ul className="findings">
            {flag.tool_findings.map((f, i) => (
              <li key={`${f.tool}-${i}`}>
                <code>{f.tool}</code>: {f.finding}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby={`${headingId}-analysis`} className="flag__section flag__analysis">
        <h4 id={`${headingId}-analysis`}>AI analysis</h4>
        <p>{flag.explanation}</p>
      </section>

      <p className="flag__action">
        <strong>Recommended human action:</strong> {flag.recommended_human_action}
      </p>

      <footer className="flag__decision">
        {decision ? (
          <p>
            <strong>{DECISION_LABELS[decision.decision]}</strong>
            {decision.reviewer_note ? ` — ${decision.reviewer_note}` : ''}
            <span className="muted"> ({new Date(decision.decided_at).toLocaleString()})</span>
          </p>
        ) : (
          <>
            <label>
              Reviewer note
              <input
                type="text"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="optional"
              />
            </label>
            <div className="flag__buttons">
              <button disabled={busy} onClick={() => decide('accepted')}>
                Accept
              </button>
              <button disabled={busy} onClick={() => decide('rejected')}>
                Reject
              </button>
              <button disabled={busy} onClick={() => decide('needs_more_info')}>
                Needs more info
              </button>
            </div>
            {error && <p role="alert">{error}</p>}
          </>
        )}
      </footer>
    </article>
  )
}
