import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { ChevronRight, GraduationCap } from "lucide-react"
import { CardButton } from "../../components/ui/Card"
import { EmptyState, ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { errorMessage, esslce } from "../../lib/api"

export function EsslceSubjectsPage() {
  const navigate = useNavigate()
  const [subjects, setSubjects] = useState<{ subject: string; questions: number }[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    esslce
      .subjects()
      .then((r) => setSubjects(r.subjects))
      .catch((e) => setError(errorMessage(e)))
  }, [])

  if (error) return <ErrorBanner message={error} />
  if (!subjects) return <FullPageSpinner />
  if (subjects.length === 0) {
    return <EmptyState icon={GraduationCap} title="No exam papers ready yet" />
  }

  return (
    <div className="flex flex-col gap-2.5">
      <p className="mb-1 text-sm text-zinc-500">Grade 12 national exam (ESSLCE) past papers.</p>
      {subjects.map((s) => (
        <CardButton
          key={s.subject}
          onClick={() => navigate(`/esslce/${encodeURIComponent(s.subject)}`)}
          className="flex items-center justify-between p-4"
        >
          <div>
            <p className="font-medium capitalize text-zinc-900">{s.subject.replace(/_/g, " ")}</p>
            <p className="text-sm text-zinc-500">{s.questions} questions</p>
          </div>
          <ChevronRight className="size-5 text-zinc-300" aria-hidden />
        </CardButton>
      ))}
    </div>
  )
}
