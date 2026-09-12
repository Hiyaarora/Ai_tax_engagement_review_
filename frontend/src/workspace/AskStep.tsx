import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import type { AskResult, CitationGuardReport, EngagementDetail } from '../types'

interface Props {
  detail: EngagementDetail
}

function guardNotes(report: CitationGuardReport): string[] {
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`
  const notes: string[] = []
  if (report.dropped_citations.length)
    notes.push(`${plural(report.dropped_citations.length, 'citation')} removed (never retrieved)`)
  if (report.corrected_citations.length)
    notes.push(`${plural(report.corrected_citations.length, 'citation')} corrected to the indexed source/page`)
  if (report.unverified_quotes.length)
    notes.push(`${plural(report.unverified_quotes.length, 'quote')} cleared (not verbatim in the passage)`)
  return notes
}

const EXAMPLES = [
  'Does the company hold inventory in Texas, and is it registered there?',
  'What are the sales and transactions in Texas?',
  'How many employees work outside the home state?',
  'What does the tax reference guide say about 3PL warehouses?',
]

/**
 * Grounded question answering. The backend retrieves passages for this engagement only, answers
 * from them, and verifies every citation; the UI shows the answer, the verified citations, and the
 * raw passages so the reviewer can check the model's reading.
 */
export function AskStep({ detail }: Props) {
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<AskResult[]>([])
  const indexed = detail.documents.filter((d) => d.status === 'indexed').length

  async function ask(event: FormEvent) {
    event.preventDefault()
    const q = question.trim()
    if (!q) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.ask(detail.engagement.engagement_id, q)
      setHistory((h) => [result, ...h])
      setQuestion('')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <form onSubmit={ask} className="card form">
        <h3>Ask the agent</h3>
        <p className="muted small">
          Answers come only from this engagement's {indexed} indexed document{indexed === 1 ? '' : 's'}{' '}
          (client files and the tax reference guide) and, for sales questions, figures computed
          from the sales data. Every citation is verified against the retrieved passage.
        </p>
        <label>
          Question
          <textarea
            rows={3}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={EXAMPLES[0]}
            disabled={!detail.can_ask || busy}
          />
        </label>
        <div className="button-row">
          <button className="primary" type="submit" disabled={!detail.can_ask || busy || !question.trim()}>
            Ask
          </button>
          {!detail.can_ask && (
            <span className="muted small">Index at least one document first (step 1).</span>
          )}
          {busy && <span className="muted small">Retrieving passages and drafting an answer…</span>}
        </div>
        {detail.can_ask && (
          <p className="muted small">
            Try:{' '}
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="link small" onClick={() => setQuestion(ex)}>
                {ex}
              </button>
            )).reduce<React.ReactNode[]>((acc, el, i) => (i ? [...acc, ' · ', el] : [el]), [])}
          </p>
        )}
        {error && <p role="alert">{error}</p>}
      </form>

      {history.map((r, i) => {
        const notes = guardNotes(r.citation_guard)
        const id = `ask-${history.length - i}`
        return (
          <article key={id} className="card answer" aria-labelledby={`${id}-q`}>
            <h4 id={`${id}-q`} className="answer__question">
              {r.question}
            </h4>
            {!r.found_in_documents && (
              <p className="flag__warning">
                Not found in the documents — the model could not answer this from the indexed
                evidence. Treat the text below as an explanation of what is missing, not a finding.
              </p>
            )}
            <p className="answer__text">{r.answer}</p>

            <section aria-labelledby={`${id}-c`} className="flag__section answer__citations">
              <h5 id={`${id}-c`}>Verified citations</h5>
              {r.citations.length === 0 ? (
                <p className="muted small">None.</p>
              ) : (
                <ul className="evidence">
                  {r.citations.map((c, j) => (
                    <li key={`${c.chunk_id}-${j}`}>
                      <span className="evidence__source">
                        {c.source_name} p.{c.page}
                      </span>{' '}
                      <code className="evidence__chunk">{c.chunk_id}</code>
                      {c.quote ? (
                        <blockquote>“{c.quote}”</blockquote>
                      ) : (
                        <p className="muted small">(quote not verified against the passage)</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-labelledby={`${id}-s`} className="flag__section answer__structured">
              <h5 id={`${id}-s`}>Computed from client data</h5>
              {r.structured_evidence.length === 0 ? (
                <p className="muted small">None used.</p>
              ) : (
                <ul className="findings">
                  {r.structured_evidence.map((e, j) => (
                    <li key={`${e.tool}-${j}`}>
                      {e.finding}{' '}
                      <span className="muted small">
                        — Source: <code>{e.source}</code> ({e.tool})
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <details className="answer__passages">
              <summary>
                Retrieved passages ({r.passages.length}) — what the model was given
              </summary>
              <section aria-label="Retrieved passages">
                <ul className="passages">
                  {r.passages.map((p) => (
                    <li key={p.chunk_id}>
                      <span className="evidence__source">
                        {p.source_name} p.{p.page}
                      </span>{' '}
                      <code className="evidence__chunk">{p.chunk_id}</code>
                      <pre className="passage">{p.excerpt}</pre>
                    </li>
                  ))}
                </ul>
              </section>
            </details>

            <p className="muted small">
              {notes.length ? `Citation guard: ${notes.join('; ')}.` : 'Citation guard: all citations verified.'}{' '}
              · {r.model} · {r.disclaimer}
            </p>
          </article>
        )
      })}
    </section>
  )
}
