import type { TokenUsage } from '../types'

const fmt = new Intl.NumberFormat('en-US')

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  const seconds = ms / 1000
  return seconds < 10 ? `${seconds.toFixed(1)} s` : `${Math.round(seconds)} s`
}

/** One muted line: tokens, turns, wall time and per-tool time - the cost of an AI run. */
export function UsageLine({ usage, model }: { usage: TokenUsage; model?: string }) {
  const total = usage.input_tokens + usage.output_tokens
  const tools = Object.entries(usage.tool_durations_ms)
    .sort(([, a], [, b]) => b - a)
    .map(([name, ms]) => `${name} ${formatDuration(ms)}`)
  return (
    <p className="muted small usage">
      {fmt.format(total)} tokens ({fmt.format(usage.input_tokens)} in / {fmt.format(usage.output_tokens)}{' '}
      out) · {usage.turns} turn{usage.turns === 1 ? '' : 's'} · {formatDuration(usage.duration_ms)}
      {model ? ` · ${model}` : ''}
      {tools.length ? ` · tools: ${tools.join(', ')}` : ''}
    </p>
  )
}
