import { useState } from "react"
import { ChevronDown, TrendingUp } from "lucide-react"
import { Spinner } from "../ui/Primitives"
import { errorMessage, esslce, type UnitInsight } from "../../lib/api"

// "How this unit is tested" under a unit in the ESSLCE unit list. Fetched only when opened: the
// first request for a unit generates the summary (several seconds), every later one is cached.
export function UnitInsightPanel({ subject, unit, grade }: { subject: string; unit: string; grade: number }) {
  const [open, setOpen] = useState(false)
  const [insight, setInsight] = useState<UnitInsight | null>(null)
  const [error, setError] = useState<string | null>(null)

  function toggle() {
    const next = !open
    setOpen(next)
    if (next && !insight && !error) {
      esslce
        .unitInsight(subject, unit, grade)
        .then(setInsight)
        .catch((e) => setError(errorMessage(e)))
    }
  }

  return (
    <div className="-mt-1 px-1">
      <button
        onClick={toggle}
        className="flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline"
      >
        <TrendingUp className="size-3.5" aria-hidden /> How it's tested
        <ChevronDown className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {open && (
        <div className="mt-2 rounded-xl border border-zinc-200/70 bg-white p-3 text-sm text-zinc-700">
          {error && <p className="text-red-700">{error}</p>}
          {!insight && !error && (
            <p className="flex items-center gap-2 text-zinc-500">
              <Spinner className="size-4" /> Reading past exams...
            </p>
          )}
          {insight && !insight.available && (
            <p className="text-zinc-500">
              {insight.question_count === 0
                ? "No past exam questions are linked to this unit yet."
                : `Only ${insight.question_count} past question${insight.question_count === 1 ? "" : "s"} from this unit so far - not enough to show a pattern.`}
            </p>
          )}
          {insight?.available && (
            <div className="flex flex-col gap-2.5">
              <p className="font-medium text-zinc-900">
                In {insight.years_appeared} of the {insight.total_years} past exams in the bank (
                {insight.question_count} questions)
              </p>
              <InsightList title="Comes up again and again" items={insight.concepts} />
              <InsightList title="How it's asked" items={insight.styles} />
              <InsightList title="Tips" items={insight.tips} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function InsightList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{title}</p>
      <ul className="mt-1 list-disc pl-5">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}
