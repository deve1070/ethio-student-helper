import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ArrowRight, CheckCircle2, RefreshCw } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { EmptyState, ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { OptionList } from "../../components/question/OptionList"
import { ReadingPassage } from "../../components/esslce/ReadingPassage"
import { RichText } from "../../components/ui/RichText"
import { useAuth } from "../../lib/auth"
import {
  errorMessage,
  esslce,
  practice,
  type EsslceMistake,
  type PracticeMistake,
} from "../../lib/api"

type Source = "practice" | "esslce"

export function MistakesPage() {
  const { gradeLevel } = useAuth()
  const navigate = useNavigate()

  const [source, setSource] = useState<Source>("practice")
  const [subjects, setSubjects] = useState<string[] | null>(null)
  const [subject, setSubject] = useState<string | null>(null)
  const [subjectsError, setSubjectsError] = useState<string | null>(null)

  const [practiceMistakes, setPracticeMistakes] = useState<PracticeMistake[] | null>(null)
  const [esslceMistakes, setEsslceMistakes] = useState<EsslceMistake[] | null>(null)
  const [dataError, setDataError] = useState<string | null>(null)

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
    setDataError(null)
    const request =
      source === "practice" ? practice.mistakes(gradeLevel, subject) : esslce.mistakes(subject)
    request
      .then((r) => {
        if (source === "practice") setPracticeMistakes(r as PracticeMistake[])
        else setEsslceMistakes(r as EsslceMistake[])
      })
      .catch((e) => setDataError(errorMessage(e)))
  }, [source, subject, gradeLevel])

  function tryAgain(unit: string | null, skill?: string | null) {
    if (!subject) return
    if (source === "practice") {
      if (unit) navigate(`/practice/${encodeURIComponent(subject)}/session?units=${encodeURIComponent(unit)}`)
      else navigate(`/practice/${encodeURIComponent(subject)}/session`)
    } else {
      const params = new URLSearchParams({ mode: "practice" })
      if (unit) params.set("unit", unit)
      else if (skill) params.set("skill", skill)
      else params.set("incorrectOnly", "1")
      navigate(`/esslce/${encodeURIComponent(subject)}/session?${params.toString()}`)
    }
  }

  const items = source === "practice" ? practiceMistakes : esslceMistakes

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
        <EmptyState icon={CheckCircle2} title="Nothing here yet" description="Answer a few questions first, and anything you miss will show up here." />
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

          {dataError && <ErrorBanner message={dataError} />}
          {!dataError && items === null && <FullPageSpinner />}

          {items && items.length === 0 && (
            <EmptyState
              icon={CheckCircle2}
              title="No mistakes to review"
              description="Everything you've answered recently in this subject is correct. Nice work."
            />
          )}

          {items && items.length > 0 && (
            <div className="flex flex-col gap-4">
              {(source === "practice" ? (practiceMistakes ?? []) : []).map((m) => (
                <Card key={m.question_id} className="flex flex-col gap-3 p-4">
                  <p className="text-[15px] leading-relaxed text-zinc-900">{m.question}</p>
                  <OptionList options={m.options} selected={m.chosen_index} correctIndex={m.correct_index} onSelect={() => {}} disabled />
                  {m.explanation && <p className="text-sm leading-relaxed text-zinc-600">{m.explanation}</p>}
                  <Button size="sm" variant="secondary" onClick={() => tryAgain(m.unit)}>
                    <RefreshCw className="size-4" aria-hidden /> Try a similar question <ArrowRight className="size-4" aria-hidden />
                  </Button>
                </Card>
              ))}
              {(source === "esslce" ? (esslceMistakes ?? []) : []).map((m) => (
                <Card key={m.question_id} className="flex flex-col gap-3 p-4">
                  {m.passage_text && <ReadingPassage title={m.passage_title} text={m.passage_text} />}
                  <p className="text-xs font-medium text-zinc-400">
                    {m.year_ec} E.C.{m.booklet_code ? ` · Booklet ${m.booklet_code}` : ""}
                  </p>
                  <p className="text-[15px] leading-relaxed text-zinc-900">
                    <span className="mr-1.5 text-zinc-400">{m.item_no}.</span>
                    <RichText text={m.stem} />
                  </p>
                  <OptionList options={m.options} selected={m.chosen_index} correctIndex={m.correct_index} onSelect={() => {}} disabled />
                  {m.explanation_image_base64 ? (
                    <img
                      src={`data:image/png;base64,${m.explanation_image_base64}`}
                      alt="Worked solution"
                      className="rounded-lg border border-zinc-100"
                    />
                  ) : (
                    m.explanation && <p className="text-sm leading-relaxed text-zinc-600">{m.explanation}</p>
                  )}
                  <Button size="sm" variant="secondary" onClick={() => tryAgain(m.unit, m.skill)}>
                    <RefreshCw className="size-4" aria-hidden /> Try a similar question <ArrowRight className="size-4" aria-hidden />
                  </Button>
                </Card>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
