import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, BookMarked, Lightbulb, Sigma } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { ErrorBanner, Spinner } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
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
      <p className="mt-1 text-[15px] leading-relaxed text-zinc-700">{section.summary}</p>
      {citationLine(section.citation) && (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-zinc-400">
          <BookMarked className="size-3 shrink-0" aria-hidden />
          {citationLine(section.citation)}
        </p>
      )}
    </div>
  )
}

export function NotesDetailPage() {
  const { subject = "", unit = "" } = useParams()
  const { gradeLevel } = useAuth()
  const navigate = useNavigate()
  const [note, setNote] = useState<StudyNote | null>(null)
  const [stage, setStage] = useState("Getting your notes ready...")
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setNote(null)
    setError(null)
    setStage("Getting your notes ready...")
    notes
      .note(gradeLevel, subject, unit, setStage)
      .then(setNote)
      .catch((e) => setError(errorMessage(e)))
  }, [gradeLevel, subject, unit])

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
            <p className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
              <Lightbulb className="size-4 text-brand-600" aria-hidden /> Overview
            </p>
            <p className="text-[15px] leading-relaxed text-zinc-700">{note.overview}</p>
          </Card>

          <Card className="flex flex-col gap-4 p-4">
            {note.sections.map((s) => (
              <SectionBlock key={s.number} section={s} />
            ))}
          </Card>

          {note.formulas_image_base64 && (
            <Card className="flex flex-col gap-3 p-4">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
                <Sigma className="size-4 text-accent-600" aria-hidden /> Key formulas
              </p>
              <img
                src={`data:image/png;base64,${note.formulas_image_base64}`}
                alt="Key formulas"
                className="rounded-lg border border-zinc-100"
              />
            </Card>
          )}

          {note.worked_example_image_base64 && (
            <Card className="flex flex-col gap-3 p-4">
              <p className="text-sm font-semibold text-zinc-900">Worked example</p>
              <img
                src={`data:image/png;base64,${note.worked_example_image_base64}`}
                alt="Worked example"
                className="rounded-lg border border-zinc-100"
              />
            </Card>
          )}

          <Button
            fullWidth
            onClick={() => navigate(`/practice/${encodeURIComponent(subject)}/session?units=${encodeURIComponent(unit)}`)}
          >
            Practice this unit
          </Button>
        </>
      )}
    </div>
  )
}
