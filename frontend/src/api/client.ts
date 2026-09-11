import type {
  Decision,
  EngagementSummary,
  FlagDecision,
  HealthResponse,
  ReviewDetail,
  ReviewResult,
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
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!response.ok) {
    // FastAPI puts the human-readable reason in {"detail": ...}
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, `API ${response.status}: ${detail}`)
  }
  return (await response.json()) as T
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  listEngagements: () => request<EngagementSummary[]>('/engagements'),
  listReviews: (engagementId: string) =>
    request<ReviewSummary[]>(`/engagements/${encodeURIComponent(engagementId)}/reviews`),
  runReview: (engagementId: string) =>
    request<ReviewResult>(`/engagements/${encodeURIComponent(engagementId)}/reviews`, {
      method: 'POST',
    }),
  getReview: (reviewId: string) => request<ReviewDetail>(`/reviews/${encodeURIComponent(reviewId)}`),
  decideFlag: (reviewId: string, flagId: string, decision: Decision, reviewerNote = '') =>
    request<FlagDecision>(
      `/reviews/${encodeURIComponent(reviewId)}/flags/${encodeURIComponent(flagId)}`,
      { method: 'PATCH', body: JSON.stringify({ decision, reviewer_note: reviewerNote }) },
    ),
}
