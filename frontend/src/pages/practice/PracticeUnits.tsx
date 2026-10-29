import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, Play, TrendingDown } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card, CardButton } from "../../components/ui/Card"
import { Badge, ErrorBanner, FullPageSpinner, ProgressBar } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
import { errorMessage, practice, type PracticeUnit } from "../../lib/api"
import { LEVEL_LABEL, LEVEL_TONE } from "../../lib/levels"

export function PracticeUnitsPage() {
  const { subject = "" } = useParams()
  const { gradeLevel } = useAuth()
  const navigate = useNavigate()
  const [units, setUnits] = useState<PracticeUnit[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    practice
      .units(gradeLevel, subject)
      .then((r) => setUnits(r.units))
      .catch((e) => setError(errorMessage(e)))
  }, [gradeLevel, subject])

  const weakUnits = units?.filter((u) => u.level === "weak").map((u) => u.unit) ?? []

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={() => navigate("/practice")}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> Subjects
      </button>
      <h2 className="-mt-2 text-xl font-semibold capitalize text-zinc-900">{subject.replace(/_/g, " ")}</h2>

      {error && <ErrorBanner message={error} />}
      {!units && !error && <FullPageSpinner />}

      {units && (
        <>
          <Card className="flex items-center justify-between p-4">
            <div>
              <p className="font-medium text-zinc-900">Mixed practice</p>
              <p className="text-sm text-zinc-500">Questions across every unit, prioritizing what you miss.</p>
            </div>
            <Button size="sm" onClick={() => navigate(`/practice/${encodeURIComponent(subject)}/session`)}>
              <Play className="size-4" aria-hidden /> Start
            </Button>
          </Card>

          {weakUnits.length > 0 && (
            <CardButton
              className="flex items-center justify-between p-4"
              onClick={() =>
                navigate(
                  `/practice/${encodeURIComponent(subject)}/session?units=${encodeURIComponent(
                    weakUnits.join("|"),
                  )}`,
                )
              }
            >
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-lg bg-red-50">
                  <TrendingDown className="size-4 text-red-600" aria-hidden />
                </div>
                <div>
                  <p className="font-medium text-zinc-900">Focus on weak units</p>
                  <p className="text-sm text-zinc-500">{weakUnits.length} unit(s) need more work</p>
                </div>
              </div>
            </CardButton>
          )}

          <div className="mt-1 flex flex-col gap-2.5">
            {units.map((u) => (
              <CardButton
                key={u.unit}
                className="p-4"
                onClick={() =>
                  navigate(
                    `/practice/${encodeURIComponent(subject)}/session?units=${encodeURIComponent(u.unit)}`,
                  )
                }
              >
                <div className="flex items-center justify-between gap-3">
                  <p className="font-medium text-zinc-900">{u.unit}</p>
                  <Badge tone={LEVEL_TONE[u.level] ?? "neutral"}>{LEVEL_LABEL[u.level] ?? u.level}</Badge>
                </div>
                <p className="mt-1 text-sm text-zinc-500">
                  {u.questions} questions
                  {u.accuracy !== null ? ` - ${Math.round(u.accuracy * 100)}% accuracy` : ""}
                </p>
                {u.accuracy !== null && <ProgressBar value={u.accuracy * 100} className="mt-2" />}
              </CardButton>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
