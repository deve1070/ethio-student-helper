import { useEffect, useMemo, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { Atom, Check, Landmark, Sparkles } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card, CardButton } from "../../components/ui/Card"
import { ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
import { auth, errorMessage, type StreamSubjects } from "../../lib/api"

type Step = "stream" | "subjects" | "examDate" | "goal" | "done"

const GOAL_OPTIONS = [
  { minutes: 30, label: "30 minutes", description: "Good for busy schedules" },
  { minutes: 60, label: "1 hour", description: "Recommended for steady progress" },
  { minutes: 120, label: "2 hours", description: "For serious preparation" },
  { minutes: 180, label: "3+ hours", description: "For top performers" },
]

export function OnboardingPage() {
  const { gradeLevel, fullProfile, refreshProfile } = useAuth()
  const navigate = useNavigate()

  const steps = useMemo<Step[]>(() => {
    const s: Step[] = []
    if (gradeLevel >= 11) s.push("stream")
    s.push("subjects")
    if (gradeLevel === 12) s.push("examDate")
    s.push("goal")
    s.push("done")
    return s
  }, [gradeLevel])

  const [stepIndex, setStepIndex] = useState(0)
  const step = steps[stepIndex]

  const [stream, setStream] = useState<"natural_science" | "social_science" | null>(null)
  const [subjectsSelected, setSubjectsSelected] = useState<string[]>([])
  const [examDate, setExamDate] = useState("")
  const [dailyGoalMinutes, setDailyGoalMinutes] = useState(60)

  const [streamSubjects, setStreamSubjects] = useState<StreamSubjects | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    auth.streams().then(setStreamSubjects).catch(() => {})
  }, [])

  // prefill once, the first time an already-collected profile is available - e.g. re-entering via
  // "Edit setup" from the Profile page. Never re-runs on a later refreshProfile() during this session,
  // so it doesn't clobber choices made further along in the same wizard pass.
  const prefilled = useRef(false)
  useEffect(() => {
    if (prefilled.current || !fullProfile) return
    prefilled.current = true
    if (fullProfile.stream) setStream(fullProfile.stream)
    if (fullProfile.subjects_selected) setSubjectsSelected(fullProfile.subjects_selected)
    if (fullProfile.exam_date) setExamDate(fullProfile.exam_date)
    if (fullProfile.daily_goal_minutes) setDailyGoalMinutes(fullProfile.daily_goal_minutes)
  }, [fullProfile])

  const availableSubjects = useMemo(() => {
    if (!streamSubjects) return []
    if (stream === "natural_science") return [...streamSubjects.common, ...streamSubjects.natural_only].sort()
    if (stream === "social_science") return [...streamSubjects.common, ...streamSubjects.social_only].sort()
    return [...streamSubjects.common, ...streamSubjects.natural_only, ...streamSubjects.social_only].sort()
  }, [streamSubjects, stream])

  function goNext() {
    if (stepIndex + 1 < steps.length) setStepIndex((i) => i + 1)
  }

  async function saveAndNext(fields: Parameters<typeof auth.updateMe>[0]) {
    setSaving(true)
    setError(null)
    try {
      if (Object.keys(fields).length > 0) await auth.updateMe(fields)
      goNext()
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  async function finish() {
    setSaving(true)
    setError(null)
    try {
      await auth.updateMe({}) // marks onboarding seen if nothing already has
      await refreshProfile()
      navigate("/", { replace: true })
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setSaving(false)
    }
  }

  async function skipAll() {
    await finish()
  }

  if (!step) return <FullPageSpinner />

  return (
    <div className="mx-auto flex min-h-dvh max-w-xl flex-col bg-[#f7f8f7] px-5 py-8">
      <div className="mb-6 flex items-center gap-1.5">
        {steps.map((s, i) => (
          <div
            key={s}
            className={
              "h-1.5 flex-1 rounded-full transition-colors " +
              (i <= stepIndex ? "bg-brand-600" : "bg-zinc-200")
            }
          />
        ))}
      </div>

      {error && <ErrorBanner message={error} />}

      {step === "stream" && (
        <div className="flex flex-col gap-5">
          <div>
            <h1 className="text-xl font-semibold text-zinc-900">What's your stream?</h1>
            <p className="mt-1 text-sm text-zinc-500">Grade {gradeLevel} splits into two streams. Pick yours.</p>
          </div>
          <div className="flex flex-col gap-3">
            <CardButton
              className={"flex items-center gap-4 p-4 " + (stream === "natural_science" ? "border-brand-500 ring-1 ring-brand-500" : "")}
              onClick={() => setStream("natural_science")}
            >
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-emerald-50">
                <Atom className="size-5 text-emerald-600" aria-hidden />
              </div>
              <div className="flex-1">
                <p className="font-medium text-zinc-900">Natural Science</p>
                <p className="text-sm text-zinc-500">Biology, Chemistry, Physics, Mathematics</p>
              </div>
              {stream === "natural_science" && <Check className="size-5 text-brand-600" aria-hidden />}
            </CardButton>
            <CardButton
              className={"flex items-center gap-4 p-4 " + (stream === "social_science" ? "border-brand-500 ring-1 ring-brand-500" : "")}
              onClick={() => setStream("social_science")}
            >
              <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-accent-100">
                <Landmark className="size-5 text-accent-600" aria-hidden />
              </div>
              <div className="flex-1">
                <p className="font-medium text-zinc-900">Social Science</p>
                <p className="text-sm text-zinc-500">History, Geography, Economics, Mathematics</p>
              </div>
              {stream === "social_science" && <Check className="size-5 text-brand-600" aria-hidden />}
            </CardButton>
          </div>
          <Button fullWidth disabled={!stream || saving} loading={saving} onClick={() => saveAndNext({ stream: stream! })}>
            Continue
          </Button>
          <button onClick={skipAll} className="text-center text-sm font-medium text-zinc-400 hover:text-zinc-600">
            Skip for now
          </button>
        </div>
      )}

      {step === "subjects" && (
        <div className="flex flex-col gap-5">
          <div>
            <h1 className="text-xl font-semibold text-zinc-900">Which subjects are you focusing on?</h1>
            <p className="mt-1 text-sm text-zinc-500">You can change this later from your profile.</p>
          </div>
          {!streamSubjects ? (
            <FullPageSpinner />
          ) : (
            <div className="grid grid-cols-2 gap-2.5">
              {availableSubjects.map((s) => {
                const checked = subjectsSelected.includes(s)
                return (
                  <button
                    key={s}
                    onClick={() =>
                      setSubjectsSelected((cur) => (checked ? cur.filter((x) => x !== s) : [...cur, s]))
                    }
                    className={
                      "flex items-center justify-between rounded-xl border px-3 py-3 text-left text-sm font-medium capitalize transition-colors " +
                      (checked ? "border-brand-500 bg-brand-50 text-brand-800" : "border-zinc-200 bg-white text-zinc-700 hover:bg-zinc-50")
                    }
                  >
                    {s.replace(/_/g, " ")}
                    {checked && <Check className="size-4 shrink-0 text-brand-600" aria-hidden />}
                  </button>
                )
              })}
            </div>
          )}
          <Button fullWidth disabled={saving} loading={saving} onClick={() => saveAndNext({ subjects_selected: subjectsSelected })}>
            Continue
          </Button>
          <button onClick={skipAll} className="text-center text-sm font-medium text-zinc-400 hover:text-zinc-600">
            Skip for now
          </button>
        </div>
      )}

      {step === "examDate" && (
        <div className="flex flex-col gap-5">
          <div>
            <h1 className="text-xl font-semibold text-zinc-900">When is your ESSLCE?</h1>
            <p className="mt-1 text-sm text-zinc-500">
              This helps us show a countdown and build a revision plan. Leave it blank if you're not sure yet.
            </p>
          </div>
          <input
            type="date"
            value={examDate}
            onChange={(e) => setExamDate(e.target.value)}
            min={new Date().toISOString().slice(0, 10)}
            className="h-12 w-full rounded-lg border border-zinc-300 bg-white px-3 text-base text-zinc-900 focus:border-brand-500 focus:outline-2 focus:outline-brand-500/30"
          />
          <Button
            fullWidth
            disabled={saving}
            loading={saving}
            onClick={() => saveAndNext(examDate ? { exam_date: examDate } : {})}
          >
            Continue
          </Button>
          <button onClick={skipAll} className="text-center text-sm font-medium text-zinc-400 hover:text-zinc-600">
            Skip for now
          </button>
        </div>
      )}

      {step === "goal" && (
        <div className="flex flex-col gap-5">
          <div>
            <h1 className="text-xl font-semibold text-zinc-900">How much time can you study each day?</h1>
            <p className="mt-1 text-sm text-zinc-500">Choose how much time you can dedicate to studying.</p>
          </div>
          <div className="flex flex-col gap-2.5">
            {GOAL_OPTIONS.map((g) => (
              <CardButton
                key={g.minutes}
                className={"flex items-center justify-between p-4 " + (dailyGoalMinutes === g.minutes ? "border-brand-500 ring-1 ring-brand-500" : "")}
                onClick={() => setDailyGoalMinutes(g.minutes)}
              >
                <div>
                  <p className="font-medium text-zinc-900">{g.label}</p>
                  <p className="text-sm text-zinc-500">{g.description}</p>
                </div>
                {dailyGoalMinutes === g.minutes && <Check className="size-5 text-brand-600" aria-hidden />}
              </CardButton>
            ))}
          </div>
          <Button fullWidth disabled={saving} loading={saving} onClick={() => saveAndNext({ daily_goal_minutes: dailyGoalMinutes })}>
            Continue
          </Button>
          <button onClick={skipAll} className="text-center text-sm font-medium text-zinc-400 hover:text-zinc-600">
            Skip for now
          </button>
        </div>
      )}

      {step === "done" && (
        <div className="flex flex-1 flex-col items-center justify-center gap-5 text-center">
          <div className="flex size-16 items-center justify-center rounded-full bg-brand-50">
            <Sparkles className="size-8 text-brand-600" aria-hidden />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-zinc-900">You're all set!</h1>
            <p className="mt-1 text-sm text-zinc-500">Your study plan is ready. Let's get started.</p>
          </div>
          <Card className="w-full p-4 text-left text-sm text-zinc-600">
            {stream && <p className="capitalize">Stream: {stream.replace("_", " ")}</p>}
            {subjectsSelected.length > 0 && <p>Subjects: {subjectsSelected.length} selected</p>}
            {examDate && <p>Exam date: {examDate}</p>}
            <p>Daily goal: {GOAL_OPTIONS.find((g) => g.minutes === dailyGoalMinutes)?.label}</p>
          </Card>
          <Button fullWidth disabled={saving} loading={saving} onClick={finish}>
            Go to Dashboard
          </Button>
        </div>
      )}
    </div>
  )
}
