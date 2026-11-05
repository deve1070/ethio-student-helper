import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { BookOpenCheck, BookText, Calendar, GraduationCap, MessageCircleQuestion, Sparkles } from "lucide-react"
import { Card, CardButton } from "../components/ui/Card"
import { Spinner } from "../components/ui/Primitives"
import { StudyPlanTaskRow } from "../components/ui/StudyPlanTaskRow"
import { useAuth } from "../lib/auth"
import { studyPlan, type StudyPlanResponse, type StudyPlanTask } from "../lib/api"
import { taskHref, todayIso } from "../lib/studyPlanTasks"

function daysUntil(dateStr: string): number {
  const ms = new Date(dateStr + "T00:00:00").getTime() - new Date().setHours(0, 0, 0, 0)
  return Math.round(ms / 86_400_000)
}

export function DashboardPage() {
  const navigate = useNavigate()
  const { gradeLevel, fullProfile } = useAuth()
  const [week, setWeek] = useState<StudyPlanResponse | null | undefined>(undefined)

  useEffect(() => {
    studyPlan
      .week()
      .then(setWeek)
      .catch(() => setWeek(null)) // non-critical - the rest of the dashboard still works without it
  }, [])

  // the week's plan is keyed by calendar date, not array position - today is usually days[0] (a fresh
  // plan starts on the day it's generated), but can drift if the student opens the app after a gap
  const dayIndex = week ? week.days.findIndex((d) => d.date === todayIso()) : -1
  const today = dayIndex >= 0 ? week!.days[dayIndex] : null
  const plan = today?.tasks ?? null
  const loading = week === undefined

  async function toggleTask(taskIndex: number, task: StudyPlanTask) {
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
      }) // revert on failure
    }
  }

  const tiles = [
    {
      icon: MessageCircleQuestion,
      title: "Ask a question",
      description: "Get a grounded explanation from your Grade " + gradeLevel + " textbooks.",
      to: "/explain",
      color: "bg-brand-600",
    },
    {
      icon: BookOpenCheck,
      title: "Practice",
      description: "Multiple-choice questions from your textbooks, by subject and unit.",
      to: "/practice",
      color: "bg-accent-500",
    },
    {
      icon: GraduationCap,
      title: "ESSLCE exam bank",
      description: "Grade 12 national exam past papers - practice, mock exams, and diagnostics.",
      to: "/esslce",
      color: "bg-zinc-800",
    },
    {
      icon: BookText,
      title: "Study notes",
      description: "Topic summaries, key formulas, and worked examples from your textbooks.",
      to: "/notes",
      color: "bg-emerald-600",
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      {fullProfile?.exam_date && (
        <div className="flex items-center gap-4 rounded-2xl bg-brand-600 p-4 text-white shadow-[var(--shadow-card)]">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-white/15">
            <Calendar className="size-5" aria-hidden />
          </div>
          <div>
            <p className="text-lg font-semibold leading-tight">
              {daysUntil(fullProfile.exam_date) >= 0
                ? `${daysUntil(fullProfile.exam_date)} days to your ESSLCE`
                : "Your ESSLCE date has passed"}
            </p>
            <p className="text-sm text-white/80">{fullProfile.exam_date}</p>
          </div>
        </div>
      )}

      <Card className="flex flex-col gap-3 p-4">
        <div className="flex items-center justify-between">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
            <Sparkles className="size-4 text-brand-600" aria-hidden /> Today's study plan
          </p>
          {week && <button onClick={() => navigate("/study-plan")} className="text-xs font-medium text-brand-600">View full week</button>}
        </div>
        {loading ? (
          <div className="flex justify-center py-4">
            <Spinner />
          </div>
        ) : !plan ? (
          <p className="text-sm text-zinc-500">Set up your profile to get a personalized plan here.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {today?.rationale && <p className="text-xs text-zinc-500">{today.rationale}</p>}
            {week && !week.realistic && (
              <p className="rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800">
                There isn't quite enough time to cover everything before your exam - this plan prioritizes what's tested most.
              </p>
            )}
            {plan.map((t, i) => (
              <StudyPlanTaskRow key={i} task={t} onToggle={() => toggleTask(i, t)} onOpen={() => navigate(taskHref(t.subject, t))} />
            ))}
          </div>
        )}
      </Card>

      <p className="text-sm text-zinc-500">What would you like to study today?</p>
      {tiles.map((tile) => (
        <CardButton key={tile.to} onClick={() => navigate(tile.to)} className="p-4">
          <div className="flex items-center gap-4">
            <div className={`flex size-11 shrink-0 items-center justify-center rounded-xl ${tile.color}`}>
              <tile.icon className="size-5 text-white" aria-hidden />
            </div>
            <div>
              <p className="font-semibold text-zinc-900">{tile.title}</p>
              <p className="mt-0.5 text-sm text-zinc-500">{tile.description}</p>
            </div>
          </div>
        </CardButton>
      ))}
    </div>
  )
}
