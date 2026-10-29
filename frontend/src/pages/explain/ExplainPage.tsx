import { useEffect, useState } from "react"
import { BookMarked, Send } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { ErrorBanner, Field, Spinner, TextInput } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
import { errorMessage, explain, practice, type Citation } from "../../lib/api"

const GRADES = [9, 10, 11, 12]

export function ExplainPage() {
  const { gradeLevel, setGradeLevel } = useAuth()
  const [subject, setSubject] = useState("")
  const [subjectOptions, setSubjectOptions] = useState<string[]>([])
  const [question, setQuestion] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ answer: string; citations: Citation[] } | null>(null)

  useEffect(() => {
    practice
      .subjects(gradeLevel)
      .then((r) => setSubjectOptions(r.subjects.map((s) => s.subject)))
      .catch(() => setSubjectOptions([]))
  }, [gradeLevel])

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setResult(null)
    setLoading(true)
    try {
      const res = await explain.ask(gradeLevel, subject, question)
      setResult(res)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}

        <Field label="Grade" htmlFor="grade">
          <div className="grid grid-cols-4 gap-2">
            {GRADES.map((g) => (
              <button
                key={g}
                type="button"
                onClick={() => setGradeLevel(g)}
                className={
                  "h-10 rounded-lg border text-sm font-medium transition-colors " +
                  (gradeLevel === g
                    ? "border-brand-600 bg-brand-50 text-brand-700"
                    : "border-zinc-300 text-zinc-600 hover:bg-zinc-50")
                }
              >
                {g}
              </button>
            ))}
          </div>
        </Field>

        <Field label="Subject" htmlFor="subject">
          <TextInput
            id="subject"
            list="subject-options"
            placeholder="e.g. Biology"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            required
          />
          <datalist id="subject-options">
            {subjectOptions.map((s) => (
              <option key={s} value={s} />
            ))}
          </datalist>
        </Field>

        <Field label="Your question" htmlFor="question">
          <textarea
            id="question"
            rows={4}
            className="w-full resize-none rounded-lg border border-zinc-300 bg-white p-3 text-base text-zinc-900 placeholder:text-zinc-400 focus:border-brand-500 focus:outline-2 focus:outline-brand-500/30"
            placeholder="What is the difference between mitosis and meiosis?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            required
          />
        </Field>

        <Button type="submit" size="lg" loading={loading}>
          <Send className="size-4" aria-hidden />
          Ask
        </Button>
      </form>

      {loading && (
        <Card className="flex items-center gap-3 p-4 text-sm text-zinc-500">
          <Spinner /> Finding the answer in your textbooks...
        </Card>
      )}

      {result && (
        <Card className="flex flex-col gap-4 p-5">
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-zinc-900">{result.answer}</p>
          {result.citations.length > 0 && (
            <div className="flex flex-col gap-2 border-t border-zinc-100 pt-4">
              <p className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-zinc-400">
                <BookMarked className="size-3.5" aria-hidden /> Sources
              </p>
              {result.citations.map((c, i) => (
                <p key={i} className="text-sm text-zinc-600">
                  {c.textbook} - {c.unit}
                  {c.page ? `, p. ${c.page}` : ""}
                </p>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  )
}
