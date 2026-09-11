import type { Step } from './pages/WorkspacePage'

export type Route =
  | { page: 'home' }
  | { page: 'workspace'; engagementId: string; step: Step; reviewId?: string }

const STEP_KEYS: Step[] = ['documents', 'ask', 'review', 'findings']

// Routes: #/  ·  #/e/<engagementId>/<step>[/<reviewId>]   (hash routing; no router dependency)
export function parseRoute(hash: string): Route {
  const match = /^#\/e\/([a-z0-9][a-z0-9-]{1,63})(?:\/([a-z]+))?(?:\/([A-Za-z0-9_-]+))?$/.exec(hash)
  if (!match) return { page: 'home' }
  const step = STEP_KEYS.includes(match[2] as Step) ? (match[2] as Step) : 'documents'
  return { page: 'workspace', engagementId: match[1], step, reviewId: match[3] }
}

