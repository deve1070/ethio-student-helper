import { useEffect, useState } from "react"
import { useNavigate, useParams, useSearchParams } from "react-router-dom"
import { ArrowLeft, FileText } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { MathText } from "../../components/ui/MathText"
import { errorMessage, esslce, type EsslceExamCover } from "../../lib/api"

function regionLabel(cover: EsslceExamCover): string {
  const bits = [`${cover.year_ec} E.C.`]
  if (cover.stream) bits.push(cover.stream.replace(/_/g, " "))
  if (cover.region) bits.push(cover.region)
  if (cover.round) bits.push(cover.round)
  return bits.join(" · ")
}

// The real printed cover of these past papers (NEAEA / EUEE) - confirmed against the source scans -
// only ever shows "BOOKLET CODE: 00" / "TIME ALLOWED: 00" as unfilled placeholders, never a real
// value, so this page shows only what the paper actually carries: its own identity and its own
// section directions, never a fabricated code or time limit.
export function EsslceCoverPage() {
  const { subject = "" } = useParams()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const paperId = params.get("paperId") ? Number(params.get("paperId")) : undefined

  const [cover, setCover] = useState<EsslceExamCover | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!paperId) {
      setError("No paper selected.")
      return
    }
    esslce
      .paperCover(paperId)
      .then(setCover)
      .catch((e) => setError(errorMessage(e)))
  }, [paperId])

  const backTo = `/esslce/${encodeURIComponent(subject)}/papers`

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={() => navigate(backTo)}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> Back
      </button>

      {error && <ErrorBanner message={error} />}
      {!cover && !error && <FullPageSpinner />}

      {cover && (
        <>
          <Card className="flex flex-col items-center gap-1 p-6 text-center">
            <FileText className="size-6 text-zinc-400" aria-hidden />
            <p className="mt-1 text-xs font-semibold uppercase tracking-wide text-zinc-500">
              National Educational Assessment and Examinations Agency
            </p>
            <p className="text-xs uppercase tracking-wide text-zinc-400">
              Ethiopian Secondary School Leaving Certificate Examination
            </p>
            <p className="mt-2 text-lg font-bold capitalize text-zinc-900">
              {subject.replace(/_/g, " ")} Examination
            </p>
            <p className="text-sm text-zinc-500">{regionLabel(cover)}</p>
            <div className="mt-3 w-full border-t border-zinc-100 pt-3 text-sm text-zinc-600">
              Number of items: <span className="font-semibold text-zinc-900">{cover.item_count}</span>
            </div>
          </Card>

          {cover.sections.length > 0 && (
            <Card className="flex flex-col gap-3 p-5">
              <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500">
                General directions
              </p>
              {cover.sections.map((s, i) => (
                <p key={i} className="text-sm leading-relaxed text-zinc-700">
                  <MathText text={s} />
                </p>
              ))}
            </Card>
          )}

          <Button
            variant="primary"
            fullWidth
            size="lg"
            onClick={() =>
              navigate(`/esslce/${encodeURIComponent(subject)}/session?mode=exam&paperId=${cover.paper_id}`)
            }
          >
            Begin exam
          </Button>
        </>
      )}
    </div>
  )
}
