import { useEffect, useState } from "react"

// For a single-LLM-call feature (ElaboratePanel, AskChatPanel) where the backend has no
// internal stages to report - unlike /explain or notes generation, there's nothing more
// specific happening server-side than "the one call is still running". Returns `initial` right
// away, then switches to `later` once `delayMs` has passed without the caller unmounting/
// resetting this hook - one honest escalation ("still working") rather than a fabricated
// multi-step sequence implying progress that was never actually made.
export function useDelayedStatus(active: boolean, initial: string, later: string, delayMs = 4000): string {
  const [label, setLabel] = useState(initial)

  useEffect(() => {
    if (!active) {
      setLabel(initial)
      return
    }
    const timer = setTimeout(() => setLabel(later), delayMs)
    return () => clearTimeout(timer)
  }, [active, initial, later, delayMs])

  return label
}
