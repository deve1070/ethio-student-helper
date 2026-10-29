import { useState } from "react"
import { BookMarked, Lightbulb } from "lucide-react"
import { Button } from "../ui/Button"
import { Card } from "../ui/Card"
import { Spinner } from "../ui/Primitives"
import { errorMessage, esslce, type EsslceElaboration } from "../../lib/api"

export function ElaboratePanel({ questionId }: { questionId: number }) {
  const [state, setState] = useState<"idle" | "loading" | "error" | "done">("idle")
  const [data, setData] = useState<EsslceElaboration | null>(null)
  const [error, setError] = useState("")

  async function load() {
    setState("loading")
    try {
      const res = await esslce.elaborate(questionId)
      setData(res)
      setState("done")
    } catch (e) {
      setError(errorMessage(e))
      setState("error")
    }
  }

  if (state === "idle") {
    return (
      <Button variant="secondary" size="sm" onClick={load}>
        <Lightbulb className="size-4" aria-hidden /> Explain more
      </Button>
    )
  }

  return (
    <Card className="flex flex-col gap-3 p-4">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-zinc-900">
        <Lightbulb className="size-4 text-accent-600" aria-hidden /> Deeper explanation
      </p>
      {state === "loading" && (
        <div className="flex items-center gap-2 text-sm text-zinc-500">
          <Spinner /> Working it out...
        </div>
      )}
      {state === "error" && <p className="text-sm text-red-600">{error}</p>}
      {state === "done" && data && (
        <>
          {data.content_image_base64 ? (
            <img
              src={`data:image/png;base64,${data.content_image_base64}`}
              alt="Worked explanation"
              className="rounded-lg border border-zinc-100"
            />
          ) : (
            <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-zinc-700">{data.content}</p>
          )}
          {data.citation && (
            <p className="flex items-center gap-1.5 text-xs text-zinc-400">
              <BookMarked className="size-3.5" aria-hidden />
              {data.citation.textbook}, Grade {data.citation.grade}
              {data.citation.unit_or_chapter ? ` - ${data.citation.unit_or_chapter}` : ""}
              {data.citation.section ? ` - ${data.citation.section}` : ""}
              {data.citation.page_start ? `, p. ${data.citation.page_start}` : ""}
            </p>
          )}
        </>
      )}
    </Card>
  )
}
