import type {
  Decision,
  DocType,
  DocumentRecord,
  EngagementDetail,
  FlagDecision,
  HealthResponse,
  ReferenceStatus,
  ReviewDetail,
  ReviewStatus,
  ReviewSummary,
} from '../types'

const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = init?.body instanceof FormData
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    // Let the browser set the multipart boundary for FormData bodies.
    headers: isForm ? init?.headers : { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!response.ok) {
    // FastAPI puts the human-readable reason in {"detail": ...}
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) detail = JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, `API ${response.status}: ${detail}`)
  }
  return (await response.json()) as T
}

const enc = encodeURIComponent

export const api = {
  health: () => request<HealthResponse>('/health'),

  // engagements + documents
  listEngagements: () => request<EngagementDetail[]>('/engagements'),
  createEngagement: (body: { company_name: string; home_state: string; tax_year: number }) =>
    request<EngagementDetail>('/engagements', { method: 'POST', body: JSON.stringify(body) }),
  getEngagement: (id: string) => request<EngagementDetail>(`/engagements/${enc(id)}`),
  uploadDocument: (id: string, file: File, docType?: DocType) => {
    const form = new FormData()
    form.append('file', file, file.name)
    if (docType) form.append('doc_type', docType)
    return request<DocumentRecord>(`/engagements/${enc(id)}/documents`, {
      method: 'POST',
      body: form,
    })
  },
  processDocuments: (id: string) =>
    request<{ engagement_id: string; queued: number }>(
      `/engagements/${enc(id)}/documents/process`,
      { method: 'POST' },
    ),
  loadDemoFiles: (id: string) =>
    request<{ engagement_id: string; documents: DocumentRecord[]; queued: number }>(
      `/engagements/${enc(id)}/demo-files`,
      { method: 'POST' },
    ),

  // shared reference guidance
  referenceStatus: () => request<ReferenceStatus>('/reference'),
  indexReference: () => request<{ status: string }>('/reference/index', { method: 'POST' }),

  // reviews
  listReviews: (id: string) => request<ReviewSummary[]>(`/engagements/${enc(id)}/reviews`),
  runReview: (id: string) =>
    request<{ review_id: string; status: ReviewStatus }>(`/engagements/${enc(id)}/reviews`, {
      method: 'POST',
    }),
  getReview: (reviewId: string) => request<ReviewDetail>(`/reviews/${enc(reviewId)}`),
  decideFlag: (reviewId: string, flagId: string, decision: Decision, reviewerNote = '') =>
    request<FlagDecision>(`/reviews/${enc(reviewId)}/flags/${enc(flagId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ decision, reviewer_note: reviewerNote }),
    }),
}
