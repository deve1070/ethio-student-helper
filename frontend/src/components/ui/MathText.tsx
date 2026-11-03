import { Fragment, useMemo } from "react"
import katex from "katex"

// The same four LaTeX delimiter forms exams/latex_render.py's own _BLOCK regex recognizes for its
// (weaker, PNG-based) rendering - \[...\] and \(...\) listed first so a doubled $$ is consumed as one
// block, not matched as two separate single-$ spans. Bare $...$ excludes newlines, same reasoning as the
// backend: it's the most ambiguous delimiter, so it shouldn't be allowed to span a paragraph break.
const MATH = /\\\[([\s\S]*?)\\\]|\\\(([\s\S]*?)\\\)|\$\$([\s\S]*?)\$\$|\$([^$\n]*?)\$/g
// Same bold handling as RichText.tsx, reused here so a math-bearing string doesn't lose it.
const BOLD = /\*\*(.+?)\*\*/g

function renderMath(latex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(latex, { throwOnError: false, displayMode })
  } catch {
    // A construct KaTeX genuinely can't parse - show the raw LaTeX rather than break the page, the same
    // graceful-degradation spirit as the backend's own PNG fallback (render_latex_png returns None on
    // anything unrenderable, caller shows plain text instead of a broken image).
    return latex
  }
}

function plainSegments(text: string, keyPrefix: string): React.ReactNode[] {
  const parts: React.ReactNode[] = []
  let last = 0
  let i = 0
  BOLD.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = BOLD.exec(text))) {
    if (m.index > last) parts.push(<Fragment key={`${keyPrefix}-${i++}`}>{text.slice(last, m.index)}</Fragment>)
    parts.push(
      <strong key={`${keyPrefix}-${i++}`} className="font-semibold text-inherit">
        {m[1]}
      </strong>,
    )
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push(<Fragment key={`${keyPrefix}-${i++}`}>{text.slice(last)}</Fragment>)
  return parts
}

/** Renders text that may contain LaTeX math as real KaTeX HTML, plus **bold** (RichText.tsx's own
 * handling, reused here) for everything else - replaces the backend's PNG-image math rendering on the
 * web app (Telegram still gets the PNG, it has no way to run JS; see
 * docs/dev_plans/better_study_notes.md). Used wherever a response carries LaTeX-bearing text: study
 * notes, elaborate, ask-about-this-question, exam answer explanations. */
export function MathText({ text, className }: { text: string; className?: string }) {
  const nodes = useMemo(() => {
    const parts: React.ReactNode[] = []
    let last = 0
    let i = 0
    MATH.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = MATH.exec(text))) {
      if (m.index > last) parts.push(...plainSegments(text.slice(last, m.index), `t${i++}`))
      const [, block1, inline1, block2, inline2] = m
      const latex = block1 ?? inline1 ?? block2 ?? inline2 ?? ""
      const displayMode = block1 !== undefined || block2 !== undefined
      parts.push(
        // eslint-disable-next-line react/no-danger -- katex.renderToString's own output, not user HTML
        <span key={`m${i++}`} dangerouslySetInnerHTML={{ __html: renderMath(latex, displayMode) }} />,
      )
      last = m.index + m[0].length
    }
    if (last < text.length) parts.push(...plainSegments(text.slice(last), `t${i++}`))
    return parts
  }, [text])

  return <span className={className}>{nodes}</span>
}
