import { Fragment } from "react"

// Exam-sourced text (a passage, a stem, an option) sometimes carries markdown-style **bold** around the
// exact word or phrase a question is asking about, copied from the original exam's own bold formatting -
// confirmed in stored data (passages, 78 question stems, 15 option sets). Rendered as plain text, the
// asterisks show up literally instead of emphasis, so this is the one place that turns them into real
// <strong> markup. No other markdown is in use here, so nothing more elaborate is needed.
const BOLD = /\*\*(.+?)\*\*/g

export function RichText({ text, className }: { text: string; className?: string }) {
  const parts: React.ReactNode[] = []
  let last = 0
  let i = 0
  BOLD.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = BOLD.exec(text))) {
    if (m.index > last) parts.push(<Fragment key={i++}>{text.slice(last, m.index)}</Fragment>)
    parts.push(
      <strong key={i++} className="font-semibold text-inherit">
        {m[1]}
      </strong>,
    )
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(<Fragment key={i++}>{text.slice(last)}</Fragment>)
  return <span className={className}>{parts}</span>
}
