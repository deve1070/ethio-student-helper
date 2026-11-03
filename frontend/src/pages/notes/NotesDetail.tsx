import { useEffect, useRef, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, BookMarked, Download, Lightbulb } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { MathText } from "../../components/ui/MathText"
import { ErrorBanner, Spinner } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
import { downloadElementAsPdf } from "../../lib/pdf"
import { errorMessage, notes, type StudyNote, type StudyNoteSection } from "../../lib/api"

function citationLine(citation: StudyNoteSection["citation"]): string | null {
  if (!citation) return null
  const parts = [citation.section, citation.page_start ? `p. ${citation.page_start}` : null]
  const detail = parts.filter(Boolean).join(", ")
  return detail ? `${citation.textbook} - ${detail}` : citation.textbook
}

function SectionBlock({ section }: { section: StudyNoteSection }) {
  // "3.1" -> depth 1 (top-level), "3.1.2" -> depth 2 (sub-topic of the 3.1 above it)
  const depth = section.number.split(".").length - 1
  const isSub = depth >= 2
  return (
    <div className={isSub ? "ml-4 border-l-2 border-zinc-100 pl-4" : ""}>
      <p className={isSub ? "text-sm font-semibold text-zinc-800" : "text-base font-semibold text-zinc-900"}>
        <span className="mr-1.5 text-zinc-400">{section.number}</span>
        {section.heading}
      </p>
      <p className="mt-1 text-[15px] leading-relaxed text-zinc-700">
        <MathText text={section.summary} />
      </p>
      {section.examples.map((example, i) => (
        <div key={i} className="mt-2 rounded-lg bg-emerald-50 p-3 text-[14px] leading-relaxed text-zinc-700">
          <p className="mb-1 text-xs font-semibold tracking-wide text-emerald-700 uppercase">Example</p>
          <MathText text={example} />
        </div>
      ))}
      {citationLine(section.citation) && (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-zinc-400">
          <BookMarked className="size-3 shrink-0" aria-hidden />
          {citationLine(section.citation)}
        </p>
      )}
    </div>
  )
}

function NoteContent({ note }: { note: StudyNote }) {
  return (
    <>
      <p className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
        <Lightbulb className="size-4 text-brand-600" aria-hidden /> Overview
      </p>
      <p className="text-[15px] leading-relaxed text-zinc-700">{note.overview}</p>
      <div className="mt-4 flex flex-col gap-4">
        {note.sections.map((s) => (
          <SectionBlock key={s.number} section={s} />
        ))}
      </div>
    </>
  )
}

export function NotesDetailPage() {
  const { subject = "", unit = "" } = useParams()
  const { gradeLevel } = useAuth()
  const navigate = useNavigate()
  const [note, setNote] = useState<StudyNote | null>(null)
  const [stage, setStage] = useState("Getting your notes ready...")
  const [error, setError] = useState<string | null>(null)
  const [downloading, setDownloading] = useState(false)
  const printRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setNote(null)
    setError(null)
    setStage("Getting your notes ready...")
    notes
      .note(gradeLevel, subject, unit, setStage)
      .then(setNote)
      .catch((e) => setError(errorMessage(e)))
  }, [gradeLevel, subject, unit])

  async function downloadPdf() {
    if (!printRef.current) return
    setDownloading(true)
    try {
      await downloadElementAsPdf(printRef.current, `${subject}-${unit}.pdf`.replace(/\s+/g, "_"))
    } finally {
      setDownloading(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={() => navigate(`/notes/${encodeURIComponent(subject)}`)}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> {subject.replace(/_/g, " ")}
      </button>
      <h2 className="-mt-2 text-xl font-semibold text-zinc-900">{unit}</h2>

      {error && <ErrorBanner message={error} />}
      {!note && !error && (
        <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-sm text-zinc-500">
          <Spinner />
          {stage}
        </div>
      )}

      {note && (
        <>
          <Card className="flex flex-col gap-2 p-4">
            <NoteContent note={note} />
          </Card>

          <div className="flex gap-2">
            <Button
              fullWidth
              onClick={() => navigate(`/practice/${encodeURIComponent(subject)}/session?units=${encodeURIComponent(unit)}`)}
            >
              Practice this unit
            </Button>
            <Button variant="secondary" onClick={downloadPdf} disabled={downloading}>
              <Download className="size-4" aria-hidden /> {downloading ? "Preparing..." : "PDF"}
            </Button>
          </div>

          {/* Off-screen (not display:none - html2canvas needs a real layout to capture), fixed-width
              mirror of the same note content, used only as the source for downloadElementAsPdf - a
              dedicated print-friendly layout rather than capturing the interactive on-screen view
              itself (which has app chrome/nav this shouldn't include). */}
          <div className="pointer-events-none fixed top-0 left-[-9999px] w-[650px] bg-white p-6" ref={printRef}>
            <h1 className="mb-1 text-xl font-semibold text-zinc-900">{unit}</h1>
            <p className="mb-4 text-sm text-zinc-500">{subject.replace(/_/g, " ")}</p>
            <NoteContent note={note} />
          </div>
        </>
      )}
    </div>
  )
}
