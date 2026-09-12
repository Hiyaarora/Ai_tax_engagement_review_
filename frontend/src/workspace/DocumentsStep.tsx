import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import type { DocType, DocumentRecord, EngagementDetail } from '../types'

interface Props {
  detail: EngagementDetail
  /** Called after any change so the workspace re-fetches the engagement (and starts polling). */
  onChanged: () => void
}

/** Human-readable file types. Internal JSON fixtures are never shown to the user. */
function typeLabel(d: DocumentRecord): string {
  if (d.kind === 'sales_csv') return 'Sales Data'
  switch (d.doc_type) {
    case 'questionnaire':
      return 'Questionnaire'
    case 'locations':
      return 'Employee/Office Locations'
    case 'reference':
      return 'Tax Reference Guide'
    default:
      return 'Other'
  }
}

const isInternal = (d: DocumentRecord) =>
  d.kind === 'questionnaire_json' || d.kind === 'locations_json'

function FileTable({ documents }: { documents: DocumentRecord[] }) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>File</th>
          <th>Type</th>
          <th>Status</th>
          <th>Details</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((d) => (
          <tr key={d.file_name}>
            <td>
              {d.file_name}
              {d.original_name && d.original_name !== d.file_name && (
                <div className="muted small">from {d.original_name}</div>
              )}
            </td>
            <td>{typeLabel(d)}</td>
            <td>
              <StatusBadge status={d.status} />
            </td>
            <td className="small">
              {d.status === 'indexed' && d.pages !== null && `${d.pages} pages · ${d.chunks} chunks`}
              {d.status === 'validated' && 'Ready for the deterministic tools'}
              {d.status === 'failed' && <span className="error-text">{d.error}</span>}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function DocumentsStep({ detail, onChanged }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [docType, setDocType] = useState<DocType | ''>('')
  const [busy, setBusy] = useState<'upload' | 'process' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const id = detail.engagement.engagement_id

  const visible = detail.documents.filter((d) => !isInternal(d))
  const clientFiles = visible.filter((d) => d.doc_type !== 'reference')
  const referenceFiles = visible.filter((d) => d.doc_type === 'reference')
  const pending = detail.documents.filter(
    (d) => d.kind === 'document' && (d.status === 'uploaded' || d.status === 'failed'),
  )
  const processing = detail.documents.some((d) => d.status === 'processing')

  async function run<T>(kind: NonNullable<typeof busy>, action: () => Promise<T>, done: (r: T) => void) {
    setBusy(kind)
    setError(null)
    setNotice(null)
    try {
      done(await action())
      onChanged()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(null)
    }
  }

  function upload(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    void run('upload', () => api.uploadDocument(id, file, docType || undefined), (doc) => {
      setNotice(`Uploaded ${doc.original_name} as ${typeLabel(doc)} (${doc.status}).`)
      setFile(null)
    })
  }

  return (
    <section>
      <div className="two-col">
        <form onSubmit={upload} className="card form">
          <h3>Upload a file</h3>
          <p className="muted small">
            Client files: the nexus questionnaire (PDF), employee/office locations (DOCX) and the
            sales data export (CSV). The tax reference guide (PDF) is indexed alongside them.
          </p>
          <label>
            Choose file
            <input
              type="file"
              accept=".pdf,.docx,.csv"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <label>
            File type
            <select value={docType} onChange={(e) => setDocType(e.target.value as DocType | '')}>
              <option value="">Detect from file name</option>
              <option value="questionnaire">Questionnaire (PDF)</option>
              <option value="locations">Employee/Office Locations (DOCX)</option>
              <option value="reference">Tax Reference Guide (PDF)</option>
              <option value="other">Other document</option>
            </select>
          </label>
          <button className="primary" type="submit" disabled={!file || busy !== null}>
            Upload
          </button>
        </form>

        <div className="card">
          <h3>Process</h3>
          <p className="muted small">
            Indexing extracts the text of each PDF/DOCX and makes it searchable for questions and
            the review. Each file succeeds or fails on its own; failed files can be re-processed.
          </p>
          <div className="button-row">
            <button
              className="primary"
              disabled={pending.length === 0 || busy !== null || processing}
              onClick={() =>
                void run('process', () => api.processDocuments(id), (r) =>
                  setNotice(`Processing ${r.queued} document${r.queued === 1 ? '' : 's'}…`),
                )
              }
            >
              Process documents{pending.length ? ` (${pending.length})` : ''}
            </button>
            {processing && <span className="muted small">Processing — this page updates automatically.</span>}
          </div>
        </div>
      </div>

      {error && <p role="alert">{error}</p>}
      {notice && <p className="status">{notice}</p>}

      <section aria-labelledby="client-files">
        <h3 id="client-files">Client files</h3>
        {clientFiles.length === 0 ? (
          <p className="muted">No client files yet — upload the questionnaire, locations and sales data.</p>
        ) : (
          <FileTable documents={clientFiles} />
        )}
      </section>

      <section aria-labelledby="reference-guide">
        <h3 id="reference-guide">Tax Reference Guide</h3>
        {referenceFiles.length === 0 ? (
          <p className="muted">
            No reference guide yet — upload the tax reference guide (PDF) so answers and findings
            can cite it.
          </p>
        ) : (
          <FileTable documents={referenceFiles} />
        )}
      </section>
    </section>
  )
}
