import { useEffect } from 'react'

/** Call `tick` every `intervalMs` while `active` is true. Cleans up on change/unmount. */
export function usePolling(tick: () => void, active: boolean, intervalMs: number) {
  useEffect(() => {
    if (!active) return
    const id = window.setInterval(tick, intervalMs)
    return () => window.clearInterval(id)
  }, [tick, active, intervalMs])
}
