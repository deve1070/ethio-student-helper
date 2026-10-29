import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { BookText, ChevronRight } from "lucide-react"
import { CardButton } from "../../components/ui/Card"
import { EmptyState, Field, FullPageSpinner, ErrorBanner } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
import { errorMessage, notes } from "../../lib/api"

const GRADES = [9, 10, 11, 12]

export function NotesSubjectsPage() {
  const { gradeLevel, setGradeLevel } = useAuth()
  const navigate = useNavigate()
  const [subjects, setSubjects] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setSubjects(null)
    setError(null)
    notes
      .subjects(gradeLevel)
      .then((r) => setSubjects(r.subjects))
      .catch((e) => setError(errorMessage(e)))
  }, [gradeLevel])

  return (
    <div className="flex flex-col gap-5">
      <Field label="Grade" htmlFor="grade">
        <div className="grid grid-cols-4 gap-2">
          {GRADES.map((g) => (
            <button
              key={g}
              type="button"
              onClick={() => setGradeLevel(g)}
              className={
                "h-10 rounded-lg border text-sm font-medium transition-colors " +
                (gradeLevel === g
                  ? "border-brand-600 bg-brand-50 text-brand-700"
                  : "border-zinc-300 text-zinc-600 hover:bg-zinc-50")
              }
            >
              {g}
            </button>
          ))}
        </div>
      </Field>

      {error && <ErrorBanner message={error} />}
      {!subjects && !error && <FullPageSpinner />}

      {subjects && subjects.length === 0 && (
        <EmptyState
          icon={BookText}
          title="No study notes yet"
          description={`There isn't any indexed textbook content for Grade ${gradeLevel} yet.`}
        />
      )}

      {subjects && subjects.length > 0 && (
        <div className="flex flex-col gap-2.5">
          {subjects.map((s) => (
            <CardButton
              key={s}
              onClick={() => navigate(`/notes/${encodeURIComponent(s)}`)}
              className="flex items-center justify-between p-4"
            >
              <p className="font-medium capitalize text-zinc-900">{s.replace(/_/g, " ")}</p>
              <ChevronRight className="size-5 text-zinc-300" aria-hidden />
            </CardButton>
          ))}
        </div>
      )}
    </div>
  )
}
