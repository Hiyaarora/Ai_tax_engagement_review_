import { vi } from 'vitest'

type Reply = { status?: number; body: unknown }
type Handler = (init?: RequestInit) => Reply | Promise<Reply>

/** Mock fetch by "METHOD /api/path" so page tests never touch the network. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: string[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = typeof input === 'string' ? input : (input as Request).url
    const key = `${init?.method ?? 'GET'} ${url}`
    calls.push(key)
    const handler = routes[key]
    if (!handler) {
      return new Response(JSON.stringify({ detail: `no mock for ${key}` }), { status: 500 })
    }
    const { status = 200, body } = await handler(init)
    return new Response(JSON.stringify(body), { status })
  })
  return calls
}
