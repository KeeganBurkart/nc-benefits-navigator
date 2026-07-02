import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { streamMessage } from '../api'
import Chat from '../components/Chat'
import type { SseEvent } from '../types'

vi.mock('../api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../api')>()
  return { ...mod, streamMessage: vi.fn() }
})

const mockStream = vi.mocked(streamMessage)

function emitting(...events: SseEvent[]) {
  return async (_id: string, _text: string, onEvent: (e: SseEvent) => void) => {
    for (const event of events) onEvent(event)
  }
}

async function sendMessage(text: string) {
  fireEvent.change(screen.getByLabelText('Message'), { target: { value: text } })
  fireEvent.click(screen.getByText('Send'))
}

describe('Chat', () => {
  beforeEach(() => {
    mockStream.mockReset()
  })

  it('renders streamed text deltas in order', async () => {
    mockStream.mockImplementation(
      emitting({ type: 'text', delta: 'Hel' }, { type: 'text', delta: 'lo there' }, { type: 'done' }),
    )
    render(<Chat sessionId="s1" onHousehold={vi.fn()} onScreening={vi.fn()} />)
    await sendMessage('hi')
    expect(await screen.findByText('Hello there')).toBeTruthy()
    expect(mockStream).toHaveBeenCalledWith('s1', 'hi', expect.any(Function))
  })

  it('forwards household and screening events', async () => {
    const onHousehold = vi.fn()
    const onScreening = vi.fn()
    const hh = { members: [] }
    const sc = { programs: [] }
    mockStream.mockImplementation(
      emitting(
        { type: 'household', data: hh as never },
        { type: 'screening', data: sc as never },
        { type: 'done' },
      ),
    )
    render(<Chat sessionId="s1" onHousehold={onHousehold} onScreening={onScreening} />)
    await sendMessage('hi')
    expect(onHousehold).toHaveBeenCalledWith(hh)
    expect(onScreening).toHaveBeenCalledWith(sc)
  })

  it('shows an inline notice on error events, and retry re-sends the message', async () => {
    mockStream.mockImplementation(emitting({ type: 'error', message: 'API unreachable' }))
    render(<Chat sessionId="s1" onHousehold={vi.fn()} onScreening={vi.fn()} />)
    await sendMessage('first try')
    expect(await screen.findByText(/API unreachable/)).toBeTruthy()

    mockStream.mockImplementation(emitting({ type: 'text', delta: 'Recovered' }, { type: 'done' }))
    fireEvent.click(await screen.findByText('Retry'))
    expect(await screen.findByText('Recovered')).toBeTruthy()
    expect(mockStream).toHaveBeenCalledTimes(2)
    expect(mockStream).toHaveBeenLastCalledWith('s1', 'first try', expect.any(Function))
  })

  it('renders assistant markdown — bold text becomes a <strong> element', async () => {
    mockStream.mockImplementation(
      emitting({ type: 'text', delta: 'Recorded — her wage is **$12/hour**.' }, { type: 'done' }),
    )
    render(<Chat sessionId="s1" onHousehold={vi.fn()} onScreening={vi.fn()} />)
    await sendMessage('hi')
    const strong = await screen.findByText('$12/hour')
    expect(strong.tagName).toBe('STRONG')
  })

  it('inserts a paragraph break between text segments split by a tool call', async () => {
    mockStream.mockImplementation(
      emitting(
        { type: 'text', delta: 'Let me record that.' },
        { type: 'household', data: {} as never },
        { type: 'screening', data: {} as never },
        { type: 'text', delta: 'Got it — recorded.' },
        { type: 'done' },
      ),
    )
    render(<Chat sessionId="s1" onHousehold={vi.fn()} onScreening={vi.fn()} />)
    await sendMessage('hi')
    const bubble = (await screen.findByText('Let me record that.')).closest('.msg-assistant')!
    const paragraphs = bubble.querySelectorAll('p')
    expect(paragraphs).toHaveLength(2)
    expect(paragraphs[0].textContent).toBe('Let me record that.')
    expect(paragraphs[1].textContent).toBe('Got it — recorded.')
  })

  it('disables the input while streaming', async () => {
    let release: () => void = () => {}
    mockStream.mockImplementation(
      (_id, _text, onEvent) =>
        new Promise<void>((resolve) => {
          onEvent({ type: 'text', delta: 'thinking' })
          release = () => {
            onEvent({ type: 'done' })
            resolve()
          }
        }),
    )
    render(<Chat sessionId="s1" onHousehold={vi.fn()} onScreening={vi.fn()} />)
    await sendMessage('hi')
    await screen.findByText('thinking')
    expect((screen.getByLabelText('Message') as HTMLInputElement).disabled).toBe(true)
    release()
    await vi.waitFor(() => {
      expect((screen.getByLabelText('Message') as HTMLInputElement).disabled).toBe(false)
    })
  })
})
