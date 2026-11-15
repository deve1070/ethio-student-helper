import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react"
import { useNavigate } from "react-router-dom"
import {
  ArrowLeft,
  ArrowRight,
  Atom,
  BookOpenCheck,
  BookText,
  Calculator,
  Calendar,
  Check,
  FlaskConical,
  Globe2,
  GraduationCap,
  Landmark,
  Loader2,
  MessageCircleQuestion,
  Sigma,
  Trophy,
} from "lucide-react"
import { ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { TelegramIcon } from "../../components/ui/icons/TelegramIcon"
import { useAuth } from "../../lib/auth"
import { auth, errorMessage, type StreamSubjects } from "../../lib/api"
import { LanguageSwitch, useI18n } from "../../lib/i18n"
import "./onboarding.css"

type Step = "welcome" | "stream" | "subjects" | "examDate" | "goal" | "done"

const FEATURES = [
  { icon: MessageCircleQuestion, title: "Ask a question", description: "Answers from your own textbooks", color: "from-brand-400 to-brand-600" },
  { icon: BookOpenCheck, title: "Practice", description: "Questions by subject and unit", color: "from-accent-400 to-accent-600" },
  { icon: GraduationCap, title: "ESSLCE exam bank", description: "Real past papers and mock exams", color: "from-sky-400 to-indigo-600" },
  { icon: BookText, title: "Study notes", description: "Summaries and worked examples", color: "from-emerald-400 to-teal-600" },
  { icon: Calendar, title: "Study plan", description: "A daily plan to your exam date", color: "from-rose-400 to-pink-600" },
  { icon: TelegramIcon, title: "Daily group practice", description: "Compete with students on Telegram", color: "from-[#5cc8f5] to-[#1f8fd1]" },
]

const GOAL_OPTIONS = [
  { minutes: 30, label: "30 minutes", description: "Good for busy schedules", emoji: "🌱" },
  { minutes: 60, label: "1 hour", description: "Recommended for steady progress", emoji: "📘" },
  { minutes: 120, label: "2 hours", description: "For serious preparation", emoji: "🔥" },
  { minutes: 180, label: "3+ hours", description: "For top performers", emoji: "🏆" },
]

// background glyphs: icon, horizontal position (%), size (px), rise duration (s), start delay (s)
const FLOATERS = [
  [Atom, 6, 34, 19, 0],
  [Sigma, 22, 26, 23, 6],
  [FlaskConical, 40, 30, 21, 11],
  [Globe2, 58, 38, 25, 3],
  [Calculator, 74, 28, 20, 9],
  [BookText, 88, 32, 24, 14],
  [Landmark, 14, 24, 27, 17],
  [Trophy, 66, 22, 22, 20],
] as const

const CONFETTI_COLORS = ["#3fb99a", "#f2a73b", "#71d3b6", "#ffffff", "#f472b6", "#60a5fa"]

const stagger = (i: number) => ({ "--i": i }) as CSSProperties

export function OnboardingPage() {
  const { gradeLevel, fullProfile, refreshProfile } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()

  const steps = useMemo<Step[]>(() => {
    const s: Step[] = ["welcome"]
    if (gradeLevel >= 11) s.push("stream")
    s.push("subjects")
    if (gradeLevel === 12) s.push("examDate")
    s.push("goal")
    s.push("done")
    return s
  }, [gradeLevel])

  const [stepIndex, setStepIndex] = useState(0)
  const [direction, setDirection] = useState<"fwd" | "back">("fwd")
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

  // Prefill once, the first time an already-collected profile is available (re-entering via "Edit
  // setup" on the Profile page). A later refreshProfile() must not overwrite choices made in this pass.
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

  const daysLeft = useMemo(() => {
    if (!examDate) return null
    const ms = new Date(examDate + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime()
    return Math.max(0, Math.round(ms / 86_400_000))
  }, [examDate])

  function goNext() {
    setError(null)
    setDirection("fwd")
    if (stepIndex + 1 < steps.length) setStepIndex((i) => i + 1)
  }

  function goBack() {
    setError(null)
    setDirection("back")
    setStepIndex((i) => Math.max(0, i - 1))
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

  if (!step) return <FullPageSpinner />

  const showChrome = step !== "welcome" && step !== "done"
  const progress = (stepIndex / (steps.length - 1)) * 100

  return (
    <div className="ob-stage relative min-h-dvh overflow-clip text-white">
      <Background />

      <div className="relative z-10 mx-auto flex min-h-dvh max-w-xl flex-col px-5 pt-6 pb-8">
        <header className="mb-6 flex h-9 items-center gap-3">
          {showChrome ? (
            <button
              onClick={goBack}
              aria-label={t("Back")}
              className="flex size-9 shrink-0 items-center justify-center rounded-full bg-white/10 transition hover:bg-white/20"
            >
              <ArrowLeft className="size-4" aria-hidden />
            </button>
          ) : (
            <div className="size-9 shrink-0" />
          )}
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10">
            <div className="ob-progress-fill h-full rounded-full" style={{ width: `${Math.max(progress, 4)}%` }} />
          </div>
          {step === "welcome" ? <LanguageSwitch className="shrink-0" /> : <div className="size-9 shrink-0" />}
        </header>

        {error && (
          <div className="mb-4">
            <ErrorBanner message={error} />
          </div>
        )}

        <div key={step} data-dir={direction} className="ob-step flex flex-1 flex-col">
          {step === "welcome" && (
            <div className="flex flex-1 flex-col">
              <div className="flex flex-col items-center pt-4 text-center">
                <div className="relative mb-7">
                  <span className="ob-ring" />
                  <span className="ob-ring" />
                  <div className="ob-logo relative flex size-20 items-center justify-center rounded-[1.75rem] bg-gradient-to-br from-brand-300 to-brand-600 shadow-[0_20px_50px_-12px_rgba(63,185,154,0.8)]">
                    <GraduationCap className="size-10 text-white" aria-hidden />
                  </div>
                </div>
                <p className="ob-rise-in text-sm font-medium tracking-wide text-brand-200" style={stagger(0)}>
                  {t("Welcome to")}
                </p>
                <h1 className="ob-rise-in ob-shimmer mt-1 text-3xl leading-tight font-bold sm:text-4xl" style={stagger(1)}>
                  {t("Ethiopian Student Helper")}
                </h1>
                <p className="ob-rise-in mt-3 max-w-xs text-[15px] text-white/70" style={stagger(2)}>
                  {t("Everything you need to pass the ESSLCE, in one place.")}
                </p>
              </div>

              <div className="mt-8 grid grid-cols-2 gap-3">
                {FEATURES.map((f, i) => (
                  <div key={f.title} className="ob-glass ob-rise-in rounded-2xl p-3.5" style={stagger(i + 3)}>
                    <div className={`mb-2.5 flex size-10 items-center justify-center rounded-xl bg-gradient-to-br ${f.color} shadow-lg`}>
                      <f.icon className="size-5 text-white" aria-hidden />
                    </div>
                    <p className="text-sm leading-snug font-semibold">{t(f.title)}</p>
                    <p className="mt-0.5 text-xs leading-snug text-white/60">{t(f.description)}</p>
                  </div>
                ))}
              </div>

              <div className="mt-auto pt-8">
                {/* A bare goNext(), not saveAndNext: update_me marks onboarding complete on its first
                    call, and a student who only sees this screen has not completed it. */}
                <Cta onClick={goNext} style={stagger(10)} className="ob-rise-in">
                  {t("Get started")} <ArrowRight className="size-5" aria-hidden />
                </Cta>
              </div>
            </div>
          )}

          {step === "stream" && (
            <StepLayout
              title={t("What's your stream?")}
              subtitle={t("Grade {n} splits into two streams. Pick yours.", { n: gradeLevel })}
              onSkip={finish}
              cta={
                <Cta disabled={!stream} loading={saving} onClick={() => saveAndNext({ stream: stream! })}>
                  {t("Continue")}
                </Cta>
              }
            >
              <div className="flex flex-col gap-3">
                {(
                  [
                    { id: "natural_science", icon: Atom, name: "Natural Science", subjects: "Biology, Chemistry, Physics, Mathematics", tint: "from-emerald-400 to-teal-600" },
                    { id: "social_science", icon: Landmark, name: "Social Science", subjects: "History, Geography, Economics, Mathematics", tint: "from-accent-400 to-rose-500" },
                  ] as const
                ).map((s, i) => (
                  <ChoiceCard key={s.id} on={stream === s.id} onClick={() => setStream(s.id)} index={i}>
                    <div className={`flex size-14 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br ${s.tint} shadow-lg`}>
                      <s.icon className="size-7 text-white" aria-hidden />
                    </div>
                    <div className="flex-1">
                      <p className="text-lg font-semibold">{t(s.name)}</p>
                      <p className="text-sm text-white/60">{s.subjects}</p>
                    </div>
                  </ChoiceCard>
                ))}
              </div>
            </StepLayout>
          )}

          {step === "subjects" && (
            <StepLayout
              title={t("Which subjects are you focusing on?")}
              subtitle={t("You can change this later from your profile.")}
              onSkip={finish}
              cta={
                <Cta loading={saving} onClick={() => saveAndNext({ subjects_selected: subjectsSelected })}>
                  {subjectsSelected.length > 0
                    ? t("Continue with {n} subjects", { n: subjectsSelected.length })
                    : t("Continue")}
                </Cta>
              }
            >
              {!streamSubjects ? (
                <div className="flex justify-center py-10">
                  <Loader2 className="size-7 animate-spin text-brand-300" aria-hidden />
                </div>
              ) : (
                <div className="flex flex-wrap gap-2.5">
                  {availableSubjects.map((s, i) => {
                    const on = subjectsSelected.includes(s)
                    return (
                      <button
                        key={s}
                        data-on={on}
                        style={stagger(i)}
                        onClick={() => setSubjectsSelected((cur) => (on ? cur.filter((x) => x !== s) : [...cur, s]))}
                        className="ob-glass ob-rise-in flex items-center gap-2 rounded-full px-4 py-2.5 text-sm font-medium capitalize"
                      >
                        {on && <Check className="ob-check size-4 text-brand-200" aria-hidden />}
                        {s.replace(/_/g, " ")}
                      </button>
                    )
                  })}
                </div>
              )}
            </StepLayout>
          )}

          {step === "examDate" && (
            <StepLayout
              title={t("When is your ESSLCE?")}
              subtitle={t("We'll count down with you and plan your revision. Leave it blank if you're not sure yet.")}
              onSkip={finish}
              cta={
                <Cta loading={saving} onClick={() => saveAndNext(examDate ? { exam_date: examDate } : {})}>
                  {t("Continue")}
                </Cta>
              }
            >
              <div className="ob-glass ob-rise-in flex flex-col items-center rounded-3xl px-5 py-8 text-center" style={stagger(0)}>
                <div key={daysLeft ?? "none"} className="ob-bump">
                  <span className="bg-gradient-to-b from-white to-brand-200 bg-clip-text text-7xl font-bold text-transparent tabular-nums">
                    {daysLeft ?? "?"}
                  </span>
                </div>
                <p className="mt-1 text-sm font-medium text-white/70">
                  {daysLeft === null ? t("Pick your exam date") : t("days to go")}
                </p>
                <input
                  type="date"
                  value={examDate}
                  onChange={(e) => setExamDate(e.target.value)}
                  min={new Date().toISOString().slice(0, 10)}
                  className="ob-date mt-6 h-12 w-full rounded-xl border border-white/20 bg-white/10 px-3 text-base text-white focus:border-brand-300 focus:outline-none"
                />
              </div>
            </StepLayout>
          )}

          {step === "goal" && (
            <StepLayout
              title={t("How much time can you study each day?")}
              subtitle={t("Small daily sessions beat last-minute cramming.")}
              onSkip={finish}
              cta={
                <Cta loading={saving} onClick={() => saveAndNext({ daily_goal_minutes: dailyGoalMinutes })}>
                  {t("Continue")}
                </Cta>
              }
            >
              <GoalRing minutes={dailyGoalMinutes} />
              <div className="mt-5 grid grid-cols-2 gap-3">
                {GOAL_OPTIONS.map((g, i) => (
                  <button
                    key={g.minutes}
                    data-on={dailyGoalMinutes === g.minutes}
                    style={stagger(i + 1)}
                    onClick={() => setDailyGoalMinutes(g.minutes)}
                    className="ob-glass ob-rise-in rounded-2xl p-3.5 text-left"
                  >
                    <span className="text-2xl" aria-hidden>
                      {g.emoji}
                    </span>
                    <p className="mt-1 font-semibold">{t(g.label)}</p>
                    <p className="text-xs leading-snug text-white/60">{t(g.description)}</p>
                  </button>
                ))}
              </div>
            </StepLayout>
          )}

          {step === "done" && (
            <div className="relative flex flex-1 flex-col items-center justify-center text-center">
              <Confetti />
              <svg viewBox="0 0 110 110" className="size-28" aria-hidden>
                <circle cx="55" cy="55" r="48" fill="rgba(63,185,154,0.15)" stroke="#71d3b6" strokeWidth="5" className="ob-draw-circle" strokeLinecap="round" />
                <path d="M34 57 l14 14 l28 -30" fill="none" stroke="#ffffff" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" className="ob-draw-tick" />
              </svg>
              <h1 className="ob-rise-in ob-shimmer mt-6 text-3xl font-bold" style={stagger(8)}>
                {t("You're all set!")}
              </h1>
              <p className="ob-rise-in mt-2 text-white/70" style={stagger(9)}>
                {t("Your study plan is ready. Let's get started.")}
              </p>

              <div className="mt-7 flex w-full flex-wrap justify-center gap-2">
                {[
                  stream && t(stream === "natural_science" ? "Natural Science" : "Social Science"),
                  subjectsSelected.length > 0 && t("{n} subjects", { n: subjectsSelected.length }),
                  daysLeft !== null && t("{n} days to your ESSLCE", { n: daysLeft }),
                  t(GOAL_OPTIONS.find((g) => g.minutes === dailyGoalMinutes)?.label ?? "") + " / " + t("day"),
                ]
                  .filter(Boolean)
                  .map((chip, i) => (
                    <span key={i} className="ob-glass ob-rise-in rounded-full px-3.5 py-1.5 text-sm" style={stagger(i + 10)}>
                      {chip}
                    </span>
                  ))}
              </div>

              <div className="mt-auto w-full pt-10">
                <Cta loading={saving} onClick={finish} className="ob-rise-in" style={stagger(14)}>
                  {t("Go to Dashboard")} <ArrowRight className="size-5" aria-hidden />
                </Cta>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Background() {
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden>
      <div className="ob-blob -top-24 -left-20 size-80 bg-brand-500" />
      <div className="ob-blob top-1/3 -right-24 size-72 bg-accent-500" style={{ animationDelay: "-6s", opacity: 0.3 }} />
      <div className="ob-blob -bottom-24 left-1/4 size-96 bg-brand-700" style={{ animationDelay: "-12s" }} />
      {FLOATERS.map(([Icon, left, size, duration, delay], i) => (
        <Icon
          key={i}
          className="ob-float"
          style={{ left: `${left}%`, width: size, height: size, animationDuration: `${duration}s`, animationDelay: `${delay}s` }}
        />
      ))}
    </div>
  )
}

function StepLayout({
  title,
  subtitle,
  children,
  cta,
  onSkip,
}: {
  title: string
  subtitle: string
  children: ReactNode
  cta: ReactNode
  onSkip: () => void
}) {
  const { t } = useI18n()
  return (
    <div className="flex flex-1 flex-col">
      <h1 className="ob-rise-in text-2xl leading-tight font-bold" style={stagger(0)}>
        {title}
      </h1>
      <p className="ob-rise-in mt-2 mb-6 text-[15px] text-white/65" style={stagger(1)}>
        {subtitle}
      </p>
      {children}
      <div className="mt-auto flex flex-col gap-3 pt-8">
        {cta}
        <button onClick={onSkip} className="text-center text-sm font-medium text-white/45 transition hover:text-white/80">
          {t("Skip for now")}
        </button>
      </div>
    </div>
  )
}

function ChoiceCard({ on, onClick, index, children }: { on: boolean; onClick: () => void; index: number; children: ReactNode }) {
  return (
    <button
      data-on={on}
      onClick={onClick}
      style={stagger(index + 2)}
      className="ob-glass ob-rise-in relative flex items-center gap-4 rounded-2xl p-4 text-left"
    >
      {children}
      <span
        className={`flex size-7 shrink-0 items-center justify-center rounded-full border-2 transition ${on ? "border-brand-300 bg-brand-400" : "border-white/25"}`}
      >
        {on && <Check className="ob-check size-4 text-white" aria-hidden />}
      </span>
    </button>
  )
}

function Cta({
  children,
  onClick,
  disabled,
  loading,
  className = "",
  style,
}: {
  children: ReactNode
  onClick: () => void
  disabled?: boolean
  loading?: boolean
  className?: string
  style?: CSSProperties
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      style={style}
      className={`ob-cta flex h-14 w-full items-center justify-center gap-2 rounded-2xl text-base font-semibold text-white ${className}`}
    >
      {loading && <Loader2 className="size-5 animate-spin" aria-hidden />}
      {children}
    </button>
  )
}

// A ring that fills toward a 3-hour day; the arc length animates through the stroke-dashoffset transition.
function GoalRing({ minutes }: { minutes: number }) {
  const { t } = useI18n()
  const r = 54
  const circumference = 2 * Math.PI * r
  const fraction = Math.min(minutes / 180, 1)
  const hours = minutes / 60
  return (
    <div className="ob-rise-in flex justify-center" style={stagger(1)}>
      <div className="relative size-40">
        <svg viewBox="0 0 128 128" className="size-full -rotate-90" aria-hidden>
          <defs>
            <linearGradient id="ob-goal" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#3fb99a" />
              <stop offset="100%" stopColor="#f2a73b" />
            </linearGradient>
          </defs>
          <circle cx="64" cy="64" r={r} fill="none" stroke="rgba(255,255,255,0.1)" strokeWidth="11" />
          <circle
            cx="64"
            cy="64"
            r={r}
            fill="none"
            stroke="url(#ob-goal)"
            strokeWidth="11"
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - fraction)}
            className="ob-ring-arc"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span key={minutes} className="ob-bump text-4xl font-bold tabular-nums">
            {hours < 1 ? minutes : hours}
            {minutes >= 180 && "+"}
          </span>
          <span className="text-xs font-medium tracking-wide text-white/60 uppercase">
            {hours < 1 ? t("minutes") : hours === 1 ? t("hour") : t("hours")}
          </span>
        </div>
      </div>
    </div>
  )
}

// 36 pieces fanned out across a half-circle above the checkmark, then falling.
function Confetti() {
  const pieces = useMemo(
    () =>
      Array.from({ length: 36 }, (_, i) => {
        const angle = Math.PI * (i / 35) + Math.PI
        const dist = 120 + (i % 5) * 35
        return {
          x: `${Math.cos(angle) * dist}px`,
          y: `${Math.sin(angle) * dist}px`,
          r: `${(i % 2 ? 1 : -1) * (360 + i * 25)}deg`,
          d: `${(i % 6) * 40}ms`,
          color: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
        }
      }),
    [],
  )
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden>
      {pieces.map((p, i) => (
        <span
          key={i}
          className="ob-confetti"
          style={{ background: p.color, "--x": p.x, "--y": p.y, "--r": p.r, "--d": p.d } as CSSProperties}
        />
      ))}
    </div>
  )
}
