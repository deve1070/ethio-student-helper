import { RichText } from "../ui/RichText"

// Stored as "(1) first paragraph\n\n(2) second paragraph\n\n..." (exams/store.py's load_paper) - the
// paragraph number is already in the text, but a plain <p> collapses the blank line between paragraphs
// to a single space in HTML, so without splitting on it here the whole passage reads as one run-on block.
export function ReadingPassage({ title, text }: { title?: string | null; text: string }) {
  const paragraphs = text.split(/\n\n+/).filter(Boolean)
  return (
    <div className="flex flex-col gap-2.5 rounded-lg bg-zinc-50 p-3">
      {title && <p className="text-sm font-semibold text-zinc-700">{title}</p>}
      {paragraphs.map((para, i) => (
        <p key={i} className="text-sm leading-relaxed text-zinc-600">
          <RichText text={para} />
        </p>
      ))}
    </div>
  )
}
