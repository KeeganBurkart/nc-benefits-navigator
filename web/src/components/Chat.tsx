import { useEffect, useRef, useState } from 'react'
import { streamMessage } from '../api'
import type { Household, ScreeningResult } from '../types'

interface Msg {
  role: 'user' | 'assistant' | 'notice'
  text: string
}

interface ChatProps {
  sessionId: string | null
  onHousehold: (h: Household) => void
  onScreening: (s: ScreeningResult) => void
}

function appendDelta(messages: Msg[], delta: string): Msg[] {
  const last = messages[messages.length - 1]
  if (last && last.role === 'assistant') {
    return [...messages.slice(0, -1), { ...last, text: last.text + delta }]
  }
  return [...messages, { role: 'assistant', text: delta }]
}

function withNotice(messages: Msg[], text: string): Msg[] {
  const trimmed =
    messages.length > 0 &&
    messages[messages.length - 1].role === 'assistant' &&
    messages[messages.length - 1].text === ''
      ? messages.slice(0, -1)
      : messages
  return [...trimmed, { role: 'notice', text }]
}

export default function Chat({ sessionId, onHousehold, onScreening }: ChatProps) {
  const [messages, setMessages] = useState<Msg[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [lastFailed, setLastFailed] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  async function send(text: string) {
    const trimmed = text.trim()
    if (!sessionId || !trimmed || streaming) return
    setStreaming(true)
    setLastFailed(null)
    setMessages((m) => [...m, { role: 'user', text: trimmed }, { role: 'assistant', text: '' }])
    let failed = false
    try {
      await streamMessage(sessionId, trimmed, (event) => {
        if (event.type === 'text') {
          setMessages((m) => appendDelta(m, event.delta))
        } else if (event.type === 'household') {
          onHousehold(event.data)
        } else if (event.type === 'screening') {
          onScreening(event.data)
        } else if (event.type === 'error') {
          failed = true
          setMessages((m) => withNotice(m, event.message))
        }
      })
    } catch (e) {
      failed = true
      setMessages((m) => withNotice(m, (e as Error).message))
    }
    if (failed) setLastFailed(trimmed)
    setStreaming(false)
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const text = input
    setInput('')
    void send(text)
  }

  return (
    <div className="chat">
      <div className="chat-messages" ref={listRef}>
        {messages.length === 0 && (
          <p className="chat-empty">
            Describe the household to begin — for example: “Single mom, two kids ages 4 and 7,
            works part time at $15/hour.”
          </p>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`msg msg-${msg.role}`}>
            {msg.role === 'notice' ? (
              <span>
                {msg.text}
                {lastFailed !== null && i === messages.length - 1 && (
                  <button
                    type="button"
                    className="retry-btn"
                    disabled={streaming}
                    onClick={() => void send(lastFailed)}
                  >
                    Retry
                  </button>
                )}
              </span>
            ) : (
              msg.text
            )}
          </div>
        ))}
      </div>
      <form className="chat-input" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Tell me about the household…"
          aria-label="Message"
          disabled={streaming || !sessionId}
          maxLength={2000}
        />
        <button type="submit" disabled={streaming || !sessionId || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}
