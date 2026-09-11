import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { HealthResponse } from '../types'

type State =
  | { kind: 'loading' }
  | { kind: 'ok'; data: HealthResponse }
  | { kind: 'error'; message: string }

const SERVICE_LABELS: Record<keyof HealthResponse['azure'], string> = {
  foundry: 'Microsoft Foundry',
  search: 'Azure AI Search',
  document_intelligence: 'Azure Document Intelligence',
}

export function HealthStatus() {
  const [state, setState] = useState<State>({ kind: 'loading' })

  useEffect(() => {
    api
      .health()
      .then((data) => setState({ kind: 'ok', data }))
      .catch((err: Error) => setState({ kind: 'error', message: err.message }))
  }, [])

  if (state.kind === 'loading') return <p>Checking backend…</p>
  if (state.kind === 'error') {
    return (
      <p role="alert">
        Backend unreachable: {state.message}. Is FastAPI running on port 8000?
      </p>
    )
  }

  const { data } = state
  return (
    <section>
      <h2>Backend status</h2>
      <p>
        {data.service} v{data.version} — <strong>{data.status}</strong> ({data.environment})
      </p>
      <h3>Azure services configured</h3>
      <ul>
        {(Object.keys(SERVICE_LABELS) as Array<keyof typeof SERVICE_LABELS>).map((key) => (
          <li key={key}>
            {SERVICE_LABELS[key]}: {data.azure[key] ? 'configured' : 'not configured'}
          </li>
        ))}
      </ul>
    </section>
  )
}
