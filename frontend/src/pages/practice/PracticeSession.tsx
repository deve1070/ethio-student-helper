import { useCallback, useEffect, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { ArrowLeft, BookMarked, CheckCircle2, RotateCcw, XCircle } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { EmptyState, ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { OptionList } from "../../components/question/OptionList"
import { useAuth } from "../../lib/auth"
import { errorMessage, practice, type PracticeAnswer, type PracticeQuestion } from "../../lib/api"

const BATCH_SIZE = 5

export function PracticeSessionPage() {
  const { subject = "" } = useParams()
  const { gradeLevel } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const units = params.get("units")?.split("|")

  const [questions, setQuestions] = useState<PracticeQuestion[] | null>(null)
  const [index, setIndex] = useState(0)
  const [selected, setSelected] = useState<number | null>(null)
  const [feedback, setFeedback] = useState<PracticeAnswer | null>(null)
  const [score, setScore] = useState({ correct: 0, total: 0 })
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const loadBatch = useCallback(() => {
    setQuestions(null)
    setError(null)
    setIndex(0)
    setSelected(null)
    setFeedback(null)
    practice
      .next(gradeLevel, subject, BATCH_SIZE, units)
      .then((r) => setQuestions(r.questions))
      .catch((e) => setError(errorMessage(e)))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gradeLevel, subject])

  useEffect(loadBatch, [loadBatch])

  async function chooseOption(i: number) {
    if (!questions) return
    setSelected(i)
    setLoading(true)
    try {
      const res = await practice.answer(questions[index].id, i)
      setFeedback(res)
      setScore((s) => ({ correct: s.correct + (res.is_correct ? 1 : 0), total: s.total + 1 }))
    } catch (e) {
      setError(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }

  function next() {
    if (!questions) return
    if (index + 1 < questions.length) {
      setIndex(index + 1)
      setSelected(null)
      setFeedback(null)
    } else {
      setQuestions(null)
      loadBatch()
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <button
          onClick={() => navigate(`/practice/${encodeURIComponent(subject)}`)}
          className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
        >
          <ArrowLeft className="size-4" aria-hidden /> {subject.replace(/_/g, " ")}
        </button>
        {score.total > 0 && (
          <p className="text-sm font-medium text-zinc-500">
            {score.correct}/{score.total} correct
          </p>
        )}
      </div>

      {error && <ErrorBanner message={error} />}
      {!questions && !error && <FullPageSpinner />}

      {questions && questions.length === 0 && (
        <EmptyState
          icon={CheckCircle2}
          title="Nothing to practice here yet"
          description="Try a different unit, or check back once more questions are added."
        />
      )}

      {questions && questions.length > 0 && (
        <>
          <p className="text-sm font-medium text-zinc-400">
            Question {index + 1} of {questions.length}
          </p>
          <Card className="p-5">
            <p className="text-[17px] leading-relaxed text-zinc-900">{questions[index].question}</p>
          </Card>

          <OptionList
            options={questions[index].options}
            selected={selected}
            correctIndex={feedback?.correct_index}
            onSelect={chooseOption}
            disabled={loading}
          />

          {feedback && (
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
              <p className="text-[15px] leading-relaxed text-zinc-700">{feedback.explanation}</p>
              <p className="rounded-lg bg-zinc-50 p-3 text-sm italic text-zinc-500">
                "{feedback.supporting_quote}"
              </p>
              <p className="flex items-center gap-1.5 text-xs text-zinc-400">
                <BookMarked className="size-3.5" aria-hidden />
                {feedback.citation.textbook}
                {feedback.citation.unit ? ` - ${feedback.citation.unit}` : ""}
                {feedback.citation.page ? `, p. ${feedback.citation.page}` : ""}
              </p>
              <Button onClick={next} fullWidth>
                {index + 1 < questions.length ? "Next question" : "New set"}
                <RotateCcw className="size-4" aria-hidden />
              </Button>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
