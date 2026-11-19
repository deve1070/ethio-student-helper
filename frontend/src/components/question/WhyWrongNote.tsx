import { useEffect, useState } from "react"
import { HelpCircle } from "lucide-react"
import { Button } from "../ui/Button"
import { MathText } from "../ui/MathText"
import { Spinner } from "../ui/Primitives"
import type { WrongChoiceNote } from "../../lib/api"
import { useDelayedStatus } from "../../lib/useDelayedStatus"
import { useI18n } from "../../lib/i18n"

const LETTERS = "ABCD"

/**
 * Why the option the student picked looked right, and what is wrong with it.
 *
 * `initial` is the note when the backend already had it stored (sent with the answer or the mistake).
 * Otherwise `load` asks for it: straight away when `autoLoad` is set (right after a wrong answer), or
 * from a button (the mistakes list, where loading every card at once would start one request each).
 * Mount it with a `key` per question and choice, so a new question starts fresh.
 */
export function WhyWrongNote({
  chosenIndex,
  initial,
  load,
  autoLoad,
}: {
  chosenIndex: number
  initial: WrongChoiceNote | null | undefined
  load: () => Promise<WrongChoiceNote>
  autoLoad: boolean
}) {
  const { t } = useI18n()
  const letter = LETTERS[chosenIndex] ?? "?"
  const [note, setNote] = useState<WrongChoiceNote | null>(initial ?? null)
  const [state, setState] = useState<"idle" | "loading" | "error">("idle")
  const loadingLabel = useDelayedStatus(
    state === "loading",
    t("Working out why {letter} looked right...", { letter }),
    t("Still working on it..."),
  )

  async function fetchNote() {
    setState("loading")
    try {
      setNote(await load())
      setState("idle")
    } catch {
      setState("error")
    }
  }

  useEffect(() => {
    if (!note && autoLoad) fetchNote()
    // only on mount: the parent remounts this per question through `key`
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (note) {
    return (
      <div className="flex flex-col gap-2 rounded-lg bg-amber-50 p-3 text-sm leading-relaxed text-amber-950 ring-1 ring-amber-200">
        <p>
          <span className="font-semibold">{t("Why {letter} looked right:", { letter })}</span>{" "}
          <MathText text={note.tempting} />
        </p>
        <p>
          <span className="font-semibold">{t("Why it's wrong:")}</span> <MathText text={note.wrong} />
        </p>
      </div>
    )
  }
  if (state === "loading") {
    return (
      <p className="flex items-center gap-2 text-sm text-zinc-500">
        <Spinner /> {loadingLabel}
      </p>
    )
  }
  if (state === "error") {
    return (
      <p className="text-sm text-zinc-500">
        {t("Couldn't explain {letter} right now.", { letter })}{" "}
        <button onClick={fetchNote} className="font-medium text-brand-700 hover:underline">
          {t("Try again")}
        </button>
      </p>
    )
  }
  if (autoLoad) return null
  return (
    <Button variant="secondary" size="sm" onClick={fetchNote}>
      <HelpCircle className="size-4" aria-hidden /> {t("Why did {letter} look right?", { letter })}
    </Button>
  )
}
