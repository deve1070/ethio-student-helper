import { useCallback, useEffect, useRef, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { ArrowLeft, CheckCircle2, Flag, XCircle } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { EmptyState, ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { OptionList } from "../../components/question/OptionList"
import { QuestionNavigator } from "../../components/esslce/QuestionNavigator"
import { ElaboratePanel } from "../../components/esslce/ElaboratePanel"
import { AskChatPanel } from "../../components/esslce/AskChatPanel"
import { ReadingPassage } from "../../components/esslce/ReadingPassage"
import { RichText } from "../../components/ui/RichText"
import { errorMessage, esslce, type EsslceAnswer, type EsslceMode, type EsslceQuestion } from "../../lib/api"
import type { ExamResultItem } from "./EsslceSummary"

export function EsslceSessionPage() {
  const { subject = "" } = useParams()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const mode = (params.get("mode") as EsslceMode) || "practice"
  const paperId = params.get("paperId") ? Number(params.get("paperId")) : undefined
  const incorrectOnly = params.get("incorrectOnly") === "1"
  const unit = params.get("unit") || undefined
  const skill = params.get("skill") || undefined
  const unitGrade = params.get("grade") ? Number(params.get("grade")) : undefined
  const immediateFeedback = mode === "practice"

  const [questions, setQuestions] = useState<EsslceQuestion[] | null>(null)
  const [index, setIndex] = useState(0)
  const [selected, setSelected] = useState<number | null>(null) // immediate-feedback (practice) mode only
  const [feedback, setFeedback] = useState<EsslceAnswer | null>(null) // practice mode only
  const [answers, setAnswers] = useState<Record<number, number>>({}) // exam/diagnostic: question index -> chosen option
  const [flagged, setFlagged] = useState<Set<number>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  // keyed by question_id, not appended - revisiting and changing an answer updates in place instead of
  // leaving a stale duplicate the final summary would double-count.
  const results = useRef<Map<number, ExamResultItem>>(new Map())

  const load = useCallback(() => {
    setQuestions(null)
    setError(null)
    setIndex(0)
    setSelected(null)
    setFeedback(null)
    setAnswers({})
    setFlagged(new Set())
    results.current = new Map()

    const request =
      mode === "diagnostic"
        ? esslce.diagnostic(subject)
        : paperId
          ? esslce.next({ subject, paper_id: paperId })
          : esslce.next({
              subject,
              incorrect_only: incorrectOnly,
              unit,
              skill,
              grade: unitGrade,
              count: 10,
            })

    request.then((r) => setQuestions(r.questions)).catch((e) => setError(errorMessage(e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subject, mode, paperId, incorrectOnly, unit, skill, unitGrade])

  useEffect(load, [load])

  function finish() {
    const ordered = questions
      ? questions.map((q) => results.current.get(q.id)).filter((r): r is ExamResultItem => !!r)
      : []
    navigate(`/esslce/${encodeURIComponent(subject)}/summary`, {
      state: { mode, subject, results: ordered },
      replace: true,
    })
  }

  async function chooseOption(i: number) {
    if (!questions) return
    const q = questions[index]
    setLoading(true)
    if (immediateFeedback) setSelected(i)
    else setAnswers((a) => ({ ...a, [index]: i }))
    try {
      const res = await esslce.answer(q.id, i, mode)
      results.current.set(q.id, {
        itemNo: q.item_no,
        questionId: q.id,
        chosenIndex: i,
        isCorrect: res.is_correct,
        correctIndex: res.correct_index,
        unit: q.unit,
        skill: q.skill,
      })
      if (immediateFeedback) {
        setFeedback(res)
      } else if (index + 1 < questions.length) {
        setIndex((n) => n + 1) // exam/diagnostic: advance automatically, but never auto-submit - that's an explicit button
      }
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  function advance() {
    // practice mode only - the "Next question" button shown after feedback
    if (!questions) return
    if (index + 1 < questions.length) {
      setIndex((n) => n + 1)
      setSelected(null)
      setFeedback(null)
    } else {
      finish()
    }
  }

  function toggleFlag() {
    setFlagged((f) => {
      const next = new Set(f)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  function submitExam() {
    if (!questions) return
    const unanswered = questions.length - Object.keys(answers).length
    if (unanswered > 0 && !window.confirm(`${unanswered} question(s) are still unanswered. Submit anyway?`)) {
      return
    }
    finish()
  }

  const backTo = `/esslce/${encodeURIComponent(subject)}`
  const current = questions?.[index]

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate(backTo)}
          className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
        >
          <ArrowLeft className="size-4" aria-hidden /> {subject.replace(/_/g, " ")}
        </button>
        {questions && questions.length > 0 && (
          <p className="text-sm font-medium text-zinc-400">
            {index + 1} / {questions.length}
          </p>
        )}
      </div>

      {(unit || skill) && (
        <p className="-mt-2 text-sm text-zinc-500">
          Practicing: <span className="font-medium text-zinc-700">{unit ?? skill}</span>
        </p>
      )}

      {error && <ErrorBanner message={error} />}
      {!questions && !error && <FullPageSpinner />}
      {questions && questions.length === 0 && (
        <EmptyState icon={CheckCircle2} title="No questions available for this selection" />
      )}

      {questions && questions.length > 0 && current && (
        <>
          <Card className="flex flex-col gap-3 p-5">
            {!immediateFeedback && (
              <button
                onClick={toggleFlag}
                className={
                  "flex w-fit items-center gap-1.5 self-end text-xs font-medium " +
                  (flagged.has(index) ? "text-amber-600" : "text-zinc-400 hover:text-zinc-600")
                }
              >
                <Flag className={flagged.has(index) ? "size-3.5 fill-amber-400" : "size-3.5"} aria-hidden />
                {flagged.has(index) ? "Marked for review" : "Mark for review"}
              </button>
            )}
            {current.passage_text && (
              <ReadingPassage title={current.passage_title} text={current.passage_text} />
            )}
            {current.diagram_image_base64 && (
              <img
                src={`data:image/jpeg;base64,${current.diagram_image_base64}`}
                alt={`Question ${current.item_no}`}
                className="rounded-lg border border-zinc-100"
              />
            )}
            <p className="text-xs font-medium text-zinc-400">
              {current.year_ec} E.C.{current.booklet_code ? ` · Booklet ${current.booklet_code}` : ""}
            </p>
            <p className="text-[17px] leading-relaxed text-zinc-900">
              <span className="mr-1.5 text-zinc-400">{current.item_no}.</span>
              <RichText text={current.stem} />
            </p>
          </Card>

          <OptionList
            options={current.options}
            selected={immediateFeedback ? selected : (answers[index] ?? null)}
            correctIndex={immediateFeedback ? feedback?.correct_index : undefined}
            onSelect={chooseOption}
            disabled={loading}
            revealAnswer={immediateFeedback}
            lockOnAnswer={immediateFeedback}
          />

          {immediateFeedback && feedback && (
            <Card className="flex flex-col gap-3 p-4">
              <p
                className={
                  "flex items-center gap-2 text-sm font-semibold " +
                  (feedback.is_correct ? "text-emerald-700" : "text-red-700")
                }
              >
                {feedback.is_correct ? (
                  <CheckCircle2 className="size-5" aria-hidden />
                ) : (
                  <XCircle className="size-5" aria-hidden />
                )}
                {feedback.is_correct ? "Correct" : "Not quite"}
              </p>
              {feedback.explanation_image_base64 ? (
                <img
                  src={`data:image/png;base64,${feedback.explanation_image_base64}`}
                  alt="Worked solution"
                  className="rounded-lg border border-zinc-100"
                />
              ) : (
                feedback.explanation && (
                  <p className="text-[15px] leading-relaxed text-zinc-700">{feedback.explanation}</p>
                )
              )}
              <div className="flex flex-wrap gap-2">
                <ElaboratePanel questionId={current.id} />
                <AskChatPanel questionId={current.id} />
              </div>
              <Button onClick={advance} fullWidth>
                {index + 1 < questions.length ? "Next question" : "Finish"}
              </Button>
            </Card>
          )}

          {!immediateFeedback && (
            <>
              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setIndex((n) => Math.max(0, n - 1))}
                  disabled={index === 0}
                >
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setIndex((n) => Math.min(questions.length - 1, n + 1))}
                  disabled={index === questions.length - 1}
                >
                  Next
                </Button>
              </div>

              <Card className="p-4">
                <QuestionNavigator
                  count={questions.length}
                  currentIndex={index}
                  answered={new Set(Object.keys(answers).map(Number))}
                  flagged={flagged}
                  onJump={setIndex}
                />
              </Card>

              <Button variant="primary" fullWidth onClick={submitExam}>
                Submit {mode === "diagnostic" ? "diagnostic" : "exam"}
              </Button>
            </>
          )}
        </>
      )}
    </div>
  )
}
