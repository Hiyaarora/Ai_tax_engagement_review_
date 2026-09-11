import type { EngagementDetail } from '../types'

interface Props {
  detail: EngagementDetail
}

/**
 * Placeholder for Section 2 (grounded question answering). Kept in the step bar so the workflow
 * reads correctly; it is only reachable once the backend reports can_ask.
 */
export function AskStep({ detail }: Props) {
  const indexed = detail.documents.filter((d) => d.status === 'indexed').length
  return (
    <section className="card">
      <h3>Ask the agent</h3>
      <p className="muted">
        Ask a question about this engagement's {indexed} indexed document{indexed === 1 ? '' : 's'}{' '}
        and get a grounded answer with verified citations. This step is being built next; run the
        engagement review in step 3 in the meantime.
      </p>
      <textarea disabled rows={3} placeholder="e.g. Does the company hold inventory in Texas?" />
      <div className="button-row">
        <button className="primary" disabled>
          Ask
        </button>
      </div>
    </section>
  )
}
