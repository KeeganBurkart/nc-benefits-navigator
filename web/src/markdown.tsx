import type { ReactNode } from 'react'

// Minimal markdown-lite renderer for assistant chat text: bold, headings,
// bullet lists, and horizontal rules. Streaming-safe — an unmatched marker
// (e.g. a lone "**" before its closing pair has streamed in) just renders as
// literal text until it resolves on a later delta.

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const parts: ReactNode[] = []
  const re = /\*\*(.+?)\*\*/g
  let last = 0
  let match: RegExpExecArray | null
  let i = 0
  while ((match = re.exec(text)) !== null) {
    if (match.index > last) parts.push(text.slice(last, match.index))
    parts.push(<strong key={`${keyPrefix}-b${i++}`}>{match[1]}</strong>)
    last = re.lastIndex
  }
  if (last < text.length) parts.push(text.slice(last))
  return parts
}

export function renderMarkdownLite(text: string): ReactNode {
  const lines = text.split('\n')
  const blocks: ReactNode[] = []
  let listItems: string[] = []
  let key = 0

  const flushList = () => {
    if (listItems.length === 0) return
    blocks.push(
      <ul key={`ul-${key}`}>
        {listItems.map((item, i) => (
          <li key={i}>{renderInline(item, `li-${key}-${i}`)}</li>
        ))}
      </ul>,
    )
    key += 1
    listItems = []
  }

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed === '') {
      flushList()
      continue
    }
    if (/^-{3,}$/.test(trimmed)) {
      flushList()
      blocks.push(<hr key={`hr-${key++}`} />)
      continue
    }
    const heading = trimmed.match(/^#{1,6}\s+(.*)$/)
    if (heading) {
      flushList()
      blocks.push(
        <p className="msg-heading" key={`h-${key++}`}>
          {renderInline(heading[1], `h-${key}`)}
        </p>,
      )
      continue
    }
    const bullet = trimmed.match(/^[-*]\s+(.*)$/)
    if (bullet) {
      listItems.push(bullet[1])
      continue
    }
    flushList()
    blocks.push(<p key={`p-${key++}`}>{renderInline(line, `p-${key}`)}</p>)
  }
  flushList()

  return <>{blocks}</>
}
