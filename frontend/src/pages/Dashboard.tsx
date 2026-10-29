import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import {
  BookOpenCheck,
  BookText,
  Calendar,
  Check,
  GraduationCap,
  MessageCircleQuestion,
  Sparkles,
} from "lucide-react"
import { Card, CardButton } from "../components/ui/Card"
import { Spinner } from "../components/ui/Primitives"
import { useAuth } from "../lib/auth"
import { studyPlan, type StudyPlanTask } from "../lib/api"

function daysUntil(dateStr: string): number {
  const ms = new Date(dateStr + "T00:00:00").getTime() - new Date().setHours(0, 0, 0, 0)
  return Math.round(ms / 86_400_000)
}

function taskHref(subject: string | null, t: StudyPlanTask): string {
  if (t.kind === "ask") return "/explain"
  if (t.kind === "practice" && subject) {
    return t.unit ? `/practice/${encodeURIComponent(subject)}/session?units=${encodeURIComponent(t.unit)}` : `/practice/${encodeURIComponent(subject)}`
  }
  if (t.kind === "esslce" && subject) {
    const params = new URLSearchParams({ mode: "practice" })
    if (t.unit) params.set("unit", t.unit)
    else if (t.skill) params.set("skill", t.skill)
    return t.unit || t.skill ? `/esslce/${encodeURIComponent(subject)}/session?${params.toString()}` : `/esslce/${encodeURIComponent(subject)}`
  }
  return "/"
}

export function DashboardPage() {
  const navigate = useNavigate()
  const { gradeLevel, fullProfile } = useAuth()
  const [plan, setPlan] = useState<StudyPlanTask[] | null>(null)

  useEffect(() => {
    studyPlan
      .today()
      .then((r) => setPlan(r.tasks))
      .catch(() => setPlan([])) // non-critical - the rest of the dashboard still works without it
  }, [])

  async function toggleTask(index: number, task: StudyPlanTask) {
    const next = !task.done
    setPlan((cur) => (cur ? cur.map((t, i) => (i === index ? { ...t, done: next } : t)) : cur))
    try {
      await studyPlan.markDone(index, next)
    } catch {
      setPlan((cur) => (cur ? cur.map((t, i) => (i === index ? { ...t, done: !next } : t)) : cur)) // revert on failure
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
        <p className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
          <Sparkles className="size-4 text-brand-600" aria-hidden /> Today's study plan
        </p>
        {plan === null ? (
          <div className="flex justify-center py-4">
            <Spinner />
          </div>
        ) : plan.length === 0 ? (
          <p className="text-sm text-zinc-500">Answer a few questions to get a personalized plan here.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {plan.map((t, i) => (
              <div
                key={i}
                className={
                  "flex items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors " +
                  (t.done ? "border-zinc-100 bg-zinc-50" : "border-zinc-200 bg-white")
                }
              >
                <button
                  onClick={() => toggleTask(i, t)}
                  aria-label={t.done ? "Mark not done" : "Mark done"}
                  className={
                    "flex size-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors " +
                    (t.done ? "border-brand-600 bg-brand-600 text-white" : "border-zinc-300")
                  }
                >
                  {t.done && <Check className="size-3.5" aria-hidden />}
                </button>
                <button
                  onClick={() => navigate(taskHref(t.subject, t))}
                  className="flex-1 text-left"
                >
                  <p className={"text-sm font-medium " + (t.done ? "text-zinc-400 line-through" : "text-zinc-900")}>
                    {t.label}
                  </p>
                  {t.minutes !== null && <p className="text-xs text-zinc-500">{t.minutes} min</p>}
                </button>
              </div>
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
