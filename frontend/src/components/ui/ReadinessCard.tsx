import { useEffect, useState } from "react"
import { Gauge } from "lucide-react"
import { Card } from "./Card"
import { ProgressBar } from "./Primitives"
import { progress, type SubjectReadiness } from "../../lib/api"

const MIN_ANSWERS = 10 // matches READINESS_MIN_ANSWERS in backend/exams/store.py

// Projected ESSLCE score per subject. The projection weights each unit by how much of the real
// exam it makes up; "based on" is how much of the exam the student has actually practised enough
// for the number to rest on their own answers.
export function ReadinessCard() {
  const [subjects, setSubjects] = useState<SubjectReadiness[] | null>(null)

  useEffect(() => {
    progress
      .readiness()
      .then((r) => setSubjects(r.subjects))
      .catch(() => setSubjects([])) // non-critical, like the other dashboard cards
  }, [])

  if (!subjects || subjects.length === 0) return null

  return (
    <Card className="flex flex-col gap-3 p-4">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
        <Gauge className="size-4 text-brand-600" aria-hidden /> Exam readiness
      </p>
      {subjects.map((s) => (
        <div key={s.subject} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-2">
            <p className="text-sm font-medium capitalize text-zinc-900">{s.subject.replace(/_/g, " ")}</p>
            {s.projected !== null ? (
              <p className="text-sm font-semibold text-zinc-900">{Math.round(s.projected * 100)}%</p>
            ) : (
              <p className="text-xs text-zinc-500">
                Answer {MIN_ANSWERS - s.answered} more to see a projection
              </p>
            )}
          </div>
          {s.projected !== null && (
            <>
              <ProgressBar value={s.projected * 100} />
              <p className="text-xs text-zinc-500">
                Based on {Math.round(s.coverage * 100)}% of the exam - practise more units to firm it up
              </p>
            </>
          )}
        </div>
      ))}
    </Card>
  )
}
