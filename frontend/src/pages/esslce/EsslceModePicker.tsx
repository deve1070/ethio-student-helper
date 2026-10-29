import { useEffect, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { ArrowLeft, ClipboardList, Layers, ListChecks, Target, TrendingDown } from "lucide-react"
import { CardButton } from "../../components/ui/Card"
import { Badge, ErrorBanner, FullPageSpinner } from "../../components/ui/Primitives"
import { errorMessage, esslce, type EsslceProgress } from "../../lib/api"

export function EsslceModePickerPage() {
  const { subject = "" } = useParams()
  const navigate = useNavigate()
  const [progress, setProgress] = useState<EsslceProgress | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    esslce
      .progress(subject)
      .then(setProgress)
      .catch((e) => setError(errorMessage(e)))
  }, [subject])

  const rec = progress?.recommendation
  const recLabel = rec ? (rec.kind === "unit" ? rec.unit : rec.skill) : null

  return (
    <div className="flex flex-col gap-4">
      <button
        onClick={() => navigate("/esslce")}
        className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700"
      >
        <ArrowLeft className="size-4" aria-hidden /> Subjects
      </button>
      <h2 className="-mt-2 text-xl font-semibold capitalize text-zinc-900">{subject.replace(/_/g, " ")}</h2>

      {error && <ErrorBanner message={error} />}
      {!progress && !error && <FullPageSpinner />}

      {progress && (
        <>
          {progress.attempted > 0 && (
            <p className="text-sm text-zinc-500">
              {progress.correct}/{progress.attempted} correct so far
              {recLabel ? (
                <>
                  {" "}
                  - weakest area: <span className="font-medium text-zinc-700">{recLabel}</span>
                </>
              ) : null}
            </p>
          )}

          <CardButton
            className="flex items-center gap-4 p-4"
            onClick={() => navigate(`/esslce/${encodeURIComponent(subject)}/session?mode=practice`)}
          >
            <IconBubble icon={ListChecks} tone="brand" />
            <div className="flex-1">
              <p className="font-medium text-zinc-900">Practice</p>
              <p className="text-sm text-zinc-500">One question at a time, with feedback right away.</p>
            </div>
          </CardButton>

          {recLabel && (
            <CardButton
              className="flex items-center gap-4 p-4"
              onClick={() =>
                navigate(
                  `/esslce/${encodeURIComponent(subject)}/session?mode=practice&incorrectOnly=1`,
                )
              }
            >
              <IconBubble icon={TrendingDown} tone="danger" />
              <div className="flex-1">
                <p className="font-medium text-zinc-900">Review what you got wrong</p>
                <p className="text-sm text-zinc-500">Questions your last attempt missed.</p>
              </div>
            </CardButton>
          )}

          <CardButton
            className="flex items-center gap-4 p-4"
            onClick={() => navigate(`/esslce/${encodeURIComponent(subject)}/units`)}
          >
            <IconBubble icon={Layers} tone="zinc" />
            <div className="flex-1">
              <p className="font-medium text-zinc-900">Practice by topic</p>
              <p className="text-sm text-zinc-500">
                Pick a unit, then practice questions on it pooled across every past paper.
              </p>
            </div>
          </CardButton>

          <CardButton
            className="flex items-center gap-4 p-4"
            onClick={() => navigate(`/esslce/${encodeURIComponent(subject)}/papers`)}
          >
            <IconBubble icon={ClipboardList} tone="zinc" />
            <div className="flex-1">
              <p className="font-medium text-zinc-900">Mock exam</p>
              <p className="text-sm text-zinc-500">A full past paper, timed, results at the end.</p>
            </div>
          </CardButton>

          <CardButton
            className="flex items-center gap-4 p-4"
            onClick={() => navigate(`/esslce/${encodeURIComponent(subject)}/session?mode=diagnostic`)}
          >
            <IconBubble icon={Target} tone="accent" />
            <div className="flex-1">
              <p className="font-medium text-zinc-900">Diagnostic test</p>
              <p className="text-sm text-zinc-500">15 questions spread across every topic - a quick baseline.</p>
            </div>
          </CardButton>

          {progress.units.length > 0 && (
            <div className="mt-2 flex flex-col gap-1.5">
              <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">By unit</p>
              {progress.units.map((u) => (
                <button
                  key={u.unit + u.grade}
                  onClick={() =>
                    navigate(
                      `/esslce/${encodeURIComponent(subject)}/session?mode=practice&unit=${encodeURIComponent(u.unit)}&grade=${u.grade}`,
                    )
                  }
                  className="flex items-center justify-between py-1 text-sm"
                >
                  <span className="text-zinc-700">{u.unit}</span>
                  <Badge tone={u.accuracy >= 0.7 ? "success" : u.accuracy >= 0.4 ? "warning" : "danger"}>
                    {Math.round(u.accuracy * 100)}%
                  </Badge>
                </button>
              ))}
            </div>
          )}
          {progress.skills.length > 0 && (
            <div className="mt-2 flex flex-col gap-1.5">
              <p className="text-xs font-medium uppercase tracking-wide text-zinc-400">By skill</p>
              {progress.skills.map((s) => (
                <button
                  key={s.skill}
                  onClick={() =>
                    navigate(
                      `/esslce/${encodeURIComponent(subject)}/session?mode=practice&skill=${encodeURIComponent(s.skill)}`,
                    )
                  }
                  className="flex items-center justify-between py-1 text-sm"
                >
                  <span className="text-zinc-700">{s.skill}</span>
                  <Badge tone={s.accuracy >= 0.7 ? "success" : s.accuracy >= 0.4 ? "warning" : "danger"}>
                    {Math.round(s.accuracy * 100)}%
                  </Badge>
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function IconBubble({
  icon: Icon,
  tone,
}: {
  icon: typeof ListChecks
  tone: "brand" | "danger" | "zinc" | "accent"
}) {
  const tones: Record<string, string> = {
    brand: "bg-brand-100 text-brand-700",
    danger: "bg-red-100 text-red-600",
    zinc: "bg-zinc-100 text-zinc-700",
    accent: "bg-accent-400/20 text-accent-600",
  }
  return (
    <div className={`flex size-10 shrink-0 items-center justify-center rounded-xl ${tones[tone]}`}>
      <Icon className="size-5" aria-hidden />
    </div>
  )
}
