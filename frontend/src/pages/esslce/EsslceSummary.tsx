import { useLocation, useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, Check, PartyPopper, X } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { ProgressBar } from "../../components/ui/Primitives"

export interface ExamResultItem {
  itemNo: number
  questionId: number
  chosenIndex: number
  isCorrect: boolean
  correctIndex: number
  unit: string | null
  skill: string | null
}

interface LocationState {
  mode: string
  subject: string
  results: ExamResultItem[]
}

export function EsslceSummaryPage() {
  const { subject: subjectParam = "" } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const state = location.state as LocationState | null

  if (!state) {
    navigate(`/esslce/${encodeURIComponent(subjectParam)}`, { replace: true })
    return null
  }

  const { mode, subject, results } = state
  const correct = results.filter((r) => r.isCorrect).length
  const pct = results.length ? Math.round((correct / results.length) * 100) : 0

  return (
    <div className="flex flex-col gap-5">
      <button
        onClick={() => navigate(`/esslce/${encodeURIComponent(subject)}`)}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> {subject.replace(/_/g, " ")}
      </button>

      <Card className="flex flex-col items-center gap-2 p-6 text-center">
        <div className="flex size-12 items-center justify-center rounded-full bg-brand-100">
          <PartyPopper className="size-6 text-brand-700" aria-hidden />
        </div>
        <p className="text-2xl font-semibold text-zinc-900">
          {correct} / {results.length}
        </p>
        <p className="text-sm text-zinc-500">
          {mode === "diagnostic" ? "Diagnostic test complete" : "Mock exam complete"} - {pct}%
        </p>
        <ProgressBar value={pct} className="mt-2 w-full" />
      </Card>

      {mode === "diagnostic" && (
        <p className="text-sm text-zinc-500">
          This is a quick baseline spread across topics - not enough attempts per topic yet to call any one
          of them "weak". Use Practice to build up a real picture per unit.
        </p>
      )}

      <div className="flex flex-col gap-1.5">
        <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">Item by item</p>
        {results.map((r) => (
          <div key={r.questionId} className="flex items-center justify-between rounded-lg px-3 py-2 even:bg-zinc-50">
            <div className="flex items-center gap-2">
              <span
                className={
                  "flex size-6 items-center justify-center rounded-full " +
                  (r.isCorrect ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-600")
                }
              >
                {r.isCorrect ? <Check className="size-3.5" /> : <X className="size-3.5" />}
              </span>
              <span className="text-sm text-zinc-700">Item {r.itemNo}</span>
            </div>
            {(r.unit || r.skill) && <span className="text-xs text-zinc-400">{r.unit ?? r.skill}</span>}
          </div>
        ))}
      </div>

      <Button onClick={() => navigate(`/esslce/${encodeURIComponent(subject)}`)} fullWidth>
        Done
      </Button>
    </div>
  )
}
