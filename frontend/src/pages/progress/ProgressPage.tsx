import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowRight, CheckCircle2, ClipboardList, Flame, Lightbulb, Target, TrendingUp, XCircle } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { Badge, EmptyState, ErrorBanner, FullPageSpinner, ProgressBar } from "../../components/ui/Primitives"
import { AccuracyRing } from "../../components/progress/AccuracyRing"
import { TrendChart } from "../../components/progress/TrendChart"
import { LEVEL_LABEL, LEVEL_TONE } from "../../lib/levels"
import { useAuth } from "../../lib/auth"
import {
  errorMessage,
  esslce,
  practice,
  progress as progressApi,
  type EsslceProgress,
  type PracticeProgress,
  type TrendPoint,
} from "../../lib/api"

type Source = "practice" | "esslce"

interface MasteryRow {
  key: string
  label: string
  attempts: number
  correct: number
  accuracy: number
  level: string
  kind: "unit" | "skill"
  grade?: number
}

export function ProgressPage() {
  const { gradeLevel } = useAuth()
  const navigate = useNavigate()

  const [source, setSource] = useState<Source>("practice")
  const [subjects, setSubjects] = useState<string[] | null>(null)
  const [subject, setSubject] = useState<string | null>(null)
  const [subjectsError, setSubjectsError] = useState<string | null>(null)

  const [streakDays, setStreakDays] = useState<number | null>(null)

  const [practiceData, setPracticeData] = useState<PracticeProgress | null>(null)
  const [esslceData, setEsslceData] = useState<EsslceProgress | null>(null)
  const [dataError, setDataError] = useState<string | null>(null)
  const [loadingData, setLoadingData] = useState(false)

  useEffect(() => {
    progressApi
      .streak()
      .then((r) => setStreakDays(r.streak_days))
      .catch(() => setStreakDays(null)) // non-critical - the page still works without it
  }, [])

  useEffect(() => {
    setSubjects(null)
    setSubject(null)
    setSubjectsError(null)
    const request = source === "practice" ? practice.subjects(gradeLevel) : esslce.subjects()
    request
      .then((r) => {
        const names = r.subjects.map((s) => s.subject)
        setSubjects(names)
        setSubject(names[0] ?? null)
      })
      .catch((e) => setSubjectsError(errorMessage(e)))
  }, [source, gradeLevel])

  useEffect(() => {
    if (!subject) return
    setLoadingData(true)
    setDataError(null)
    const request = source === "practice" ? practice.progress(gradeLevel, subject) : esslce.progress(subject)
    request
      .then((r) => {
        if (source === "practice") setPracticeData(r as PracticeProgress)
        else setEsslceData(r as EsslceProgress)
      })
      .catch((e) => setDataError(errorMessage(e)))
      .finally(() => setLoadingData(false))
  }, [source, subject, gradeLevel])

  const attempts = source === "practice" ? practiceData?.attempts ?? 0 : esslceData?.attempted ?? 0
  const correct =
    source === "practice"
      ? practiceData?.units.reduce((sum, u) => sum + u.correct, 0) ?? 0
      : esslceData?.correct ?? 0
  const accuracyPct = attempts > 0 ? (correct / attempts) * 100 : null
  const trend: TrendPoint[] = (source === "practice" ? practiceData?.trend : esslceData?.trend) ?? []

  const masteryRows: MasteryRow[] =
    source === "practice"
      ? (practiceData?.units ?? []).map((u) => ({
          key: u.unit,
          label: u.unit,
          attempts: u.attempts,
          correct: u.correct,
          accuracy: u.accuracy,
          level: u.level,
          kind: "unit" as const,
        }))
      : [
          ...(esslceData?.units ?? []).map((u) => ({
            key: `unit:${u.unit}`,
            label: u.unit,
            attempts: u.attempted,
            correct: u.correct,
            accuracy: u.accuracy,
            level: u.level,
            kind: "unit" as const,
            grade: u.grade,
          })),
          ...(esslceData?.skills ?? []).map((s) => ({
            key: `skill:${s.skill}`,
            label: s.skill,
            attempts: s.attempted,
            correct: s.correct,
            accuracy: s.accuracy,
            level: s.level,
            kind: "skill" as const,
          })),
        ]

  const weakRow = masteryRows.find((r) => r.level === "weak")

  function startWeakPractice() {
    if (!subject) return
    if (source === "practice") {
      if (weakRow) {
        navigate(`/practice/${encodeURIComponent(subject)}/session?units=${encodeURIComponent(weakRow.label)}`)
      } else {
        navigate(`/practice/${encodeURIComponent(subject)}/session`)
      }
    } else if (weakRow) {
      const params = new URLSearchParams({ mode: "practice" })
      if (weakRow.kind === "unit") {
        params.set("unit", weakRow.label)
        if (weakRow.grade) params.set("grade", String(weakRow.grade))
      } else {
        params.set("skill", weakRow.label)
      }
      navigate(`/esslce/${encodeURIComponent(subject)}/session?${params.toString()}`)
    } else {
      navigate(`/esslce/${encodeURIComponent(subject)}/session?mode=practice&incorrectOnly=1`)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex gap-2 rounded-xl bg-zinc-100 p-1">
        {(["practice", "esslce"] as Source[]).map((s) => (
          <button
            key={s}
            onClick={() => setSource(s)}
            className={
              "flex-1 rounded-lg py-2 text-sm font-medium transition-colors " +
              (source === s ? "bg-white text-brand-700 shadow-sm" : "text-zinc-500 hover:text-zinc-700")
            }
          >
            {s === "practice" ? "Practice" : "ESSLCE"}
          </button>
        ))}
      </div>

      {subjectsError && <ErrorBanner message={subjectsError} />}
      {!subjects && !subjectsError && <FullPageSpinner />}

      {subjects && subjects.length === 0 && (
        <EmptyState icon={Target} title="No progress yet" description="Answer a few questions and your stats will show up here." />
      )}

      {subjects && subjects.length > 0 && (
        <>
          <select
            value={subject ?? ""}
            onChange={(e) => setSubject(e.target.value)}
            className="h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-base capitalize text-zinc-900 focus:border-brand-500 focus:outline-2 focus:outline-brand-500/30"
          >
            {subjects.map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ")}
              </option>
            ))}
          </select>

          {streakDays !== null && streakDays > 0 && (
            <Card className="flex items-center gap-3 p-3.5">
              <div className="flex size-9 items-center justify-center rounded-lg bg-accent-100">
                <Flame className="size-5 text-accent-600" aria-hidden />
              </div>
              <p className="text-sm text-zinc-700">
                <span className="font-semibold text-zinc-900">{streakDays}-day</span> study streak
              </p>
            </Card>
          )}

          {dataError && <ErrorBanner message={dataError} />}
          {loadingData && !dataError && <FullPageSpinner />}

          {!loadingData && !dataError && (practiceData || esslceData) && (
            <>
              <Card className="flex items-center gap-5 p-5">
                <AccuracyRing value={accuracyPct} />
                <div className="flex flex-1 flex-col gap-2.5">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-zinc-500">Questions attempted</span>
                    <span className="font-semibold text-zinc-900">{attempts}</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-1.5 text-zinc-500">
                      <CheckCircle2 className="size-4 text-emerald-600" aria-hidden /> Correct
                    </span>
                    <span className="font-semibold text-zinc-900">{correct}</span>
                  </div>
                  <div className="flex items-center justify-between text-sm">
                    <span className="flex items-center gap-1.5 text-zinc-500">
                      <XCircle className="size-4 text-red-500" aria-hidden /> Incorrect
                    </span>
                    <span className="font-semibold text-zinc-900">{attempts - correct}</span>
                  </div>
                </div>
              </Card>

              <Card className="p-4">
                <p className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
                  <TrendingUp className="size-4 text-brand-600" aria-hidden /> Last 7 days
                </p>
                <TrendChart points={trend} />
              </Card>

              {masteryRows.length > 0 && (
                <Card className="flex flex-col gap-3 p-4">
                  <p className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
                    <Target className="size-4 text-brand-600" aria-hidden /> Topic mastery
                  </p>
                  <div className="flex flex-col gap-3">
                    {masteryRows.map((r) => (
                      <div key={r.key}>
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-sm font-medium text-zinc-800">{r.label}</p>
                          <Badge tone={LEVEL_TONE[r.level] ?? "neutral"}>{LEVEL_LABEL[r.level] ?? r.level}</Badge>
                        </div>
                        <ProgressBar value={r.accuracy * 100} className="mt-1.5" />
                      </div>
                    ))}
                  </div>
                  <button
                    onClick={() => navigate("/mistakes")}
                    className="mt-1 flex items-center justify-between rounded-lg px-1 py-2 text-left transition-colors hover:bg-zinc-50"
                  >
                    <span className="flex items-center gap-1.5 text-sm font-medium text-zinc-700">
                      <ClipboardList className="size-4 text-zinc-400" aria-hidden /> Review your mistakes
                    </span>
                    <ArrowRight className="size-4 text-zinc-300" aria-hidden />
                  </button>
                </Card>
              )}

              {weakRow && (
                <Card className="flex items-center justify-between gap-3 p-4">
                  <div className="flex items-center gap-3">
                    <div className="flex size-9 items-center justify-center rounded-lg bg-amber-50">
                      <Lightbulb className="size-4 text-amber-600" aria-hidden />
                    </div>
                    <div>
                      <p className="font-medium text-zinc-900">Focus on {weakRow.label}</p>
                      <p className="text-sm text-zinc-500">{Math.round(weakRow.accuracy * 100)}% accuracy so far</p>
                    </div>
                  </div>
                  <Button size="sm" onClick={startWeakPractice}>
                    Practice <ArrowRight className="size-4" aria-hidden />
                  </Button>
                </Card>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
