import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, Clock, FileText } from "lucide-react"
import { CardButton } from "../../components/ui/Card"
import { Badge, EmptyState, ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { errorMessage, esslce, type EsslcePaper } from "../../lib/api"

function paperLabel(p: EsslcePaper): string {
  const bits = [`${p.year_ec} E.C.`]
  if (p.stream) bits.push(p.stream.replace(/_/g, " "))
  if (p.region) bits.push(p.region)
  if (p.round) bits.push(p.round)
  return bits.join(" - ")
}

export function EsslcePapersPage() {
  const { subject = "" } = useParams()
  const navigate = useNavigate()
  const [papers, setPapers] = useState<EsslcePaper[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    esslce
      .papers(subject)
      .then((r) => setPapers(r.papers))
      .catch((e) => setError(errorMessage(e)))
  }, [subject])

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={() => navigate(`/esslce/${encodeURIComponent(subject)}`)}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> Back
      </button>

      {error && <ErrorBanner message={error} />}
      {!papers && !error && <FullPageSpinner />}
      {papers && papers.length === 0 && (
        <EmptyState icon={FileText} title="No papers ready for a mock exam yet" />
      )}

      {papers && papers.length > 0 && (
        <div className="flex flex-col gap-2.5">
          {papers.map((p) => (
            <CardButton
              key={p.id}
              className="flex items-center justify-between p-4"
              onClick={() =>
                navigate(`/esslce/${encodeURIComponent(subject)}/session?mode=exam&paperId=${p.id}`)
              }
            >
              <div>
                <p className="font-medium text-zinc-900">{paperLabel(p)}</p>
                <div className="mt-1 flex items-center gap-2 text-sm text-zinc-500">
                  <span>{p.ready_for_students} questions</span>
                  {p.duration_minutes && (
                    <span className="flex items-center gap-1">
                      <Clock className="size-3.5" aria-hidden /> {p.duration_minutes} min
                    </span>
                  )}
                </div>
              </div>
              <Badge tone="brand">Start</Badge>
            </CardButton>
          ))}
        </div>
      )}
    </div>
  )
}
