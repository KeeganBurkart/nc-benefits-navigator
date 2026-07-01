import type { Household, Patch, Report, SseEvent } from './types'

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function check(r: Response): Promise<Response> {
  if (r.ok) return r
  let msg = `Request failed (HTTP ${r.status})`
  try {
    const body = await r.json()
    const detail = body?.detail
    if (detail && typeof detail === 'object' && typeof detail.error === 'string') {
      msg = detail.error
    } else if (typeof detail === 'string') {
      msg = detail
    }
  } catch {
    // keep the default message
  }
  throw new ApiError(msg, r.status)
}

const JSON_HEADERS = { 'Content-Type': 'application/json' }

export interface CreatedSession {
  sessionId: string
  demoMode: boolean
}

export async function createSession(): Promise<CreatedSession> {
  const r = await check(await fetch('/api/session', { method: 'POST' }))
  const body = await r.json()
  return {
    sessionId: body.session_id,
    demoMode: r.headers.get('X-Demo-Mode') === '1',
  }
}

export async function deleteSession(sessionId: string): Promise<void> {
  await check(await fetch(`/api/session/${sessionId}`, { method: 'DELETE' }))
}

export async function getReport(sessionId: string): Promise<Report> {
  const r = await check(await fetch(`/api/session/${sessionId}/report`))
  return (await r.json()) as Report
}

export async function patchHousehold(sessionId: string, patch: Patch): Promise<Household> {
  const r = await check(
    await fetch(`/api/session/${sessionId}/household`, {
      method: 'PATCH',
      headers: JSON_HEADERS,
      body: JSON.stringify({ patch }),
    }),
  )
  const body = await r.json()
  return body.household as Household
}

/** POST a chat message and invoke onEvent for each SSE event until the stream ends. */
export async function streamMessage(
  sessionId: string,
  text: string,
  onEvent: (event: SseEvent) => void,
): Promise<void> {
  const r = await check(
    await fetch(`/api/session/${sessionId}/message`, {
      method: 'POST',
      headers: JSON_HEADERS,
      body: JSON.stringify({ message: text }),
    }),
  )
  if (!r.body) throw new ApiError('response has no body', r.status)

  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let m: RegExpMatchArray | null
    while ((m = buf.match(/\r?\n\r?\n/)) !== null) {
      const block = buf.slice(0, m.index)
      buf = buf.slice(m.index! + m[0].length)
      const event = parseSseBlock(block)
      if (event) onEvent(event)
    }
  }
}

function parseSseBlock(block: string): SseEvent | null {
  let data = ''
  for (const rawLine of block.split(/\r?\n/)) {
    if (rawLine.startsWith('data:')) data += rawLine.slice(5).trim()
  }
  if (!data) return null
  try {
    return JSON.parse(data) as SseEvent
  } catch {
    return null
  }
}
