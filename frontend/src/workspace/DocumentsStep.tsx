import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import { StatusBadge } from '../components/StatusBadge'
import type { DocType, DocumentRecord, EngagementDetail } from '../types'

interface Props {
  detail: EngagementDetail
  /** Called after any change so the workspace re-fetches the engagement (and starts polling). */
  onChanged: () => void
}

const KIND_LABELS: Record<DocumentRecord['kind'], string> = {
  document: 'Document (indexed as evidence)',
  sales_csv: 'Sales export (structured, for the tools)',
  questionnaire_json: 'Questionnaire data (structured)',
  locations_json: 'Locations data (structured)',
}

export function DocumentsStep({ detail, onChanged }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [docType, setDocType] = useState<DocType | ''>('')
  const [busy, setBusy] = useState<'upload' | 'process' | 'demo' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const id = detail.engagement.engagement_id

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
      setNotice(`Uploaded ${doc.original_name} as ${doc.file_name} (${doc.status}).`)
      setFile(null)
    })
  }

  return (
    <section>
      <div className="two-col">
        <form onSubmit={upload} className="card form">
          <h3>Upload a file</h3>
          <p className="muted small">
            PDF or DOCX documents are indexed as citable evidence. A CSV is treated as the sales
            export (columns: transaction_id, date, ship_to_state, amount_usd, channel).
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
            Document type
            <select value={docType} onChange={(e) => setDocType(e.target.value as DocType | '')}>
              <option value="">Infer from file name</option>
              <option value="questionnaire">Nexus questionnaire</option>
              <option value="locations">Employee / office locations</option>
              <option value="other">Other</option>
            </select>
          </label>
          <button className="primary" type="submit" disabled={!file || busy !== null}>
            Upload
          </button>
        </form>

        <div className="card">
          <h3>Process</h3>
          <p className="muted small">
            Indexing runs Document Intelligence, chunking and embeddings in the background. Each
            document succeeds or fails on its own; failed ones can be re-processed.
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
            <button
              disabled={busy !== null || processing}
              onClick={() =>
                void run('demo', () => api.loadDemoFiles(id), (r) =>
                  setNotice(
                    `Loaded ${r.documents.length} synthetic Acme files; processing ${r.queued} document${r.queued === 1 ? '' : 's'}…`,
                  ),
                )
              }
            >
              Load synthetic demo
            </button>
          </div>
          <p className="muted small">
            "Load synthetic demo" pushes the Acme fixtures through the same upload and processing
            path as a manual upload.
          </p>
        </div>
      </div>

      {error && <p role="alert">{error}</p>}
      {notice && <p className="status">{notice}</p>}

      <h3>Files</h3>
      {detail.documents.length === 0 ? (
        <p className="muted">No files yet.</p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>File</th>
              <th>Kind</th>
              <th>Type</th>
              <th>Status</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {detail.documents.map((d) => (
              <tr key={d.file_name}>
                <td>
                  {d.file_name}
                  {d.original_name && d.original_name !== d.file_name && (
                    <div className="muted small">from {d.original_name}</div>
                  )}
                </td>
                <td className="small">{KIND_LABELS[d.kind]}</td>
                <td>{d.kind === 'document' ? d.doc_type : '—'}</td>
                <td>
                  <StatusBadge status={d.status} />
                </td>
                <td className="small">
                  {d.status === 'indexed' && d.pages !== null && `${d.pages} pages · ${d.chunks} chunks`}
                  {d.status === 'failed' && <span className="error-text">{d.error}</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}
