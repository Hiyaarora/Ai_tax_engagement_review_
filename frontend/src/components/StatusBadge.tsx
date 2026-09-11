import type { DocumentStatus, ReviewStatus, RiskLevel } from '../types'

type Status = DocumentStatus | ReviewStatus | RiskLevel

const LABELS: Record<Status, string> = {
  uploaded: 'Uploaded',
  processing: 'Processing…',
  indexed: 'Indexed',
  validated: 'Validated',
  failed: 'Failed',
  queued: 'Queued',
  running: 'Running…',
  done: 'Done',
  low: 'LOW',
  medium: 'MEDIUM',
  high: 'HIGH',
}

/** One badge component for pipeline statuses and risk levels, so colours stay consistent. */
export function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge badge--${status}`}>{LABELS[status]}</span>
}
