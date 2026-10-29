import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, ChevronRight } from "lucide-react"
import { CardButton } from "../../components/ui/Card"
import { ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
import { errorMessage, notes } from "../../lib/api"

export function NotesUnitsPage() {
  const { subject = "" } = useParams()
  const { gradeLevel } = useAuth()
  const navigate = useNavigate()
  const [units, setUnits] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    notes
      .units(gradeLevel, subject)
      .then((r) => setUnits(r.units))
      .catch((e) => setError(errorMessage(e)))
  }, [gradeLevel, subject])

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={() => navigate("/notes")}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> Subjects
      </button>
      <h2 className="-mt-2 text-xl font-semibold capitalize text-zinc-900">{subject.replace(/_/g, " ")}</h2>

      {error && <ErrorBanner message={error} />}
      {!units && !error && <FullPageSpinner />}

      {units && (
        <div className="flex flex-col gap-2.5">
          {units.map((u) => (
            <CardButton
              key={u}
              onClick={() => navigate(`/notes/${encodeURIComponent(subject)}/${encodeURIComponent(u)}`)}
              className="flex items-center justify-between p-4"
            >
              <p className="font-medium text-zinc-900">{u}</p>
              <ChevronRight className="size-5 text-zinc-300" aria-hidden />
            </CardButton>
          ))}
        </div>
      )}
    </div>
  )
}
