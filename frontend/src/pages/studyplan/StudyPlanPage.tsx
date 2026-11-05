import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowLeft, Calendar, Sparkles } from "lucide-react"
import { Card } from "../../components/ui/Card"
import { ErrorBanner, ProgressBar, Spinner } from "../../components/ui/Primitives"
import { StudyPlanTaskRow } from "../../components/ui/StudyPlanTaskRow"
import { errorMessage, studyPlan, type StudyPlanResponse, type StudyPlanTask } from "../../lib/api"
import { taskHref, todayIso } from "../../lib/studyPlanTasks"

function dayLabel(dateStr: string): string {
  if (dateStr === todayIso()) return "Today"
  return new Date(dateStr + "T00:00:00").toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })
}

export function StudyPlanPage() {
  const navigate = useNavigate()
  const [week, setWeek] = useState<StudyPlanResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    studyPlan
      .week()
      .then(setWeek)
      .catch((e) => setError(errorMessage(e)))
  }, [])

  async function toggleTask(dayIndex: number, taskIndex: number, task: StudyPlanTask) {
    const next = !task.done
    setWeek((cur) => {
      if (!cur) return cur
      const days = cur.days.map((d, i) =>
        i === dayIndex ? { ...d, tasks: d.tasks.map((t, j) => (j === taskIndex ? { ...t, done: next } : t)) } : d,
      )
      return { ...cur, days }
    })
    try {
      await studyPlan.markDone(dayIndex, taskIndex, next)
    } catch {
      setWeek((cur) => {
        if (!cur) return cur
        const days = cur.days.map((d, i) =>
          i === dayIndex ? { ...d, tasks: d.tasks.map((t, j) => (j === taskIndex ? { ...t, done: !next } : t)) } : d,
        )
        return { ...cur, days }
      })
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={() => navigate("/")}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> Dashboard
      </button>
      <h2 className="-mt-2 text-xl font-semibold text-zinc-900">Your study plan</h2>

      {error && <ErrorBanner message={error} />}
      {!week && !error && (
        <div className="flex min-h-[40vh] items-center justify-center">
          <Spinner />
        </div>
      )}

      {week && (
        <>
          {week.days_remaining !== null && (
            <div className="flex items-center gap-4 rounded-2xl bg-brand-600 p-4 text-white shadow-[var(--shadow-card)]">
              <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-white/15">
                <Calendar className="size-5" aria-hidden />
              </div>
              <p className="text-lg font-semibold leading-tight">{week.days_remaining} days to your ESSLCE</p>
            </div>
          )}

          {!week.realistic && (
            <Card className="border-amber-200 bg-amber-50 p-4">
              <p className="text-sm text-amber-900">
                There isn't quite enough time at your current daily pace to cover everything at least once before the
                exam (about {week.shortfall_minutes} extra minutes would be needed). This plan prioritizes the units
                that are tested most on real ESSLCE papers.
              </p>
            </Card>
          )}

          {week.missing_subjects.length > 0 && (
            <Card className="p-4">
              <p className="text-sm text-zinc-700">
                Your stream usually also includes:{" "}
                <span className="font-medium">{week.missing_subjects.map((s) => s.replace(/_/g, " ")).join(", ")}</span>.
                Add them from your profile if you want a plan for them too.
              </p>
            </Card>
          )}

          {week.weekly_note && (
            <Card className="flex items-start gap-3 p-4">
              <Sparkles className="mt-0.5 size-4 shrink-0 text-brand-600" aria-hidden />
              <p className="text-sm text-zinc-700">{week.weekly_note}</p>
            </Card>
          )}

          {Object.keys(week.coverage).length > 0 && (
            <Card className="flex flex-col gap-3 p-4">
              <p className="text-sm font-semibold text-zinc-900">Curriculum coverage</p>
              {Object.entries(week.coverage).map(([subject, ratio]) => (
                <div key={subject}>
                  <div className="mb-1 flex items-center justify-between text-xs text-zinc-500">
                    <span className="capitalize">{subject.replace(/_/g, " ")}</span>
                    <span>{ratio === null ? "-" : `${Math.round(ratio * 100)}%`}</span>
                  </div>
                  <ProgressBar value={ratio === null ? 0 : ratio * 100} />
                </div>
              ))}
            </Card>
          )}

          <div className="flex flex-col gap-3">
            {week.days.map((day, dayIndex) => (
              <Card key={day.date} className="flex flex-col gap-2 p-4">
                <p className="text-sm font-semibold text-zinc-900">{dayLabel(day.date)}</p>
                {day.rationale && <p className="text-xs text-zinc-500">{day.rationale}</p>}
                <div className="flex flex-col gap-2">
                  {day.tasks.map((t, taskIndex) => (
                    <StudyPlanTaskRow
                      key={taskIndex}
                      task={t}
                      onToggle={() => toggleTask(dayIndex, taskIndex, t)}
                      onOpen={() => navigate(taskHref(t.subject, t))}
                    />
                  ))}
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
