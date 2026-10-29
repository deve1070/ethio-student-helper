import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, ChevronRight, Layers } from "lucide-react"
import { CardButton } from "../../components/ui/Card"
import { EmptyState, ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { errorMessage, esslce } from "../../lib/api"

interface UnitRow {
  grade: number
  unit: string
  questions: number
}
interface SkillRow {
  skill: string
  questions: number
}

export function EsslceUnitsPage() {
  const { subject = "" } = useParams()
  const navigate = useNavigate()
  const [units, setUnits] = useState<UnitRow[] | null>(null)
  const [skills, setSkills] = useState<SkillRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([esslce.units(subject), esslce.skills(subject)])
      .then(([u, s]) => {
        setUnits(u.units)
        setSkills(s.skills)
      })
      .catch((e) => setError(errorMessage(e)))
  }, [subject])

  const loaded = units !== null && skills !== null
  const empty = loaded && units!.length === 0 && skills!.length === 0

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={() => navigate(`/esslce/${encodeURIComponent(subject)}`)}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> {subject.replace(/_/g, " ")}
      </button>
      <p className="-mt-2 text-sm text-zinc-500">
        Pick a topic to practice - questions are pooled across every past paper that covers it.
      </p>

      {error && <ErrorBanner message={error} />}
      {!loaded && !error && <FullPageSpinner />}
      {empty && <EmptyState icon={Layers} title="No topics ready for practice yet" />}

      {loaded && units!.length > 0 && (
        <div className="flex flex-col gap-2.5">
          {units!.map((u) => (
            <CardButton
              key={`${u.grade}-${u.unit}`}
              onClick={() =>
                navigate(
                  `/esslce/${encodeURIComponent(subject)}/session?mode=practice&unit=${encodeURIComponent(u.unit)}&grade=${u.grade}`,
                )
              }
              className="flex items-center justify-between p-4"
            >
              <div>
                <p className="font-medium text-zinc-900">{u.unit}</p>
                <p className="text-sm text-zinc-500">
                  Grade {u.grade} - {u.questions} question{u.questions === 1 ? "" : "s"}
                </p>
              </div>
              <ChevronRight className="size-5 text-zinc-300" aria-hidden />
            </CardButton>
          ))}
        </div>
      )}

      {loaded && skills!.length > 0 && (
        <div className="flex flex-col gap-2.5">
          {skills!.map((s) => (
            <CardButton
              key={s.skill}
              onClick={() =>
                navigate(
                  `/esslce/${encodeURIComponent(subject)}/session?mode=practice&skill=${encodeURIComponent(s.skill)}`,
                )
              }
              className="flex items-center justify-between p-4"
            >
              <div>
                <p className="font-medium text-zinc-900">{s.skill}</p>
                <p className="text-sm text-zinc-500">
                  {s.questions} question{s.questions === 1 ? "" : "s"}
                </p>
              </div>
              <ChevronRight className="size-5 text-zinc-300" aria-hidden />
            </CardButton>
          ))}
        </div>
      )}
    </div>
  )
}
