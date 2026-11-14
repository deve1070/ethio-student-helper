import { Download, Share, SquarePlus, X } from "lucide-react"
import { useInstallPrompt } from "../../lib/useInstallPrompt"
import { Button } from "./Button"
import { Card } from "./Card"

/** Shown wherever the app wants to offer installing itself as a PWA (Dashboard's dismissible banner,
 * Profile's permanent row) - renders nothing at all once already installed, or on a browser that can
 * neither prompt (Android/desktop Chrome/Edge) nor needs manual iOS instructions. `onDismiss`, if
 * given, adds a close button (the Dashboard banner's own "don't show this again" - Profile's copy
 * passes nothing, so it stays put as a permanent, always-findable row). */
export function InstallAppCard({ onDismiss }: { onDismiss?: () => void }) {
  const { isStandalone, canInstall, isIOS, promptInstall } = useInstallPrompt()

  if (isStandalone || (!canInstall && !isIOS)) return null

  return (
    <Card className="flex items-start gap-3 p-4">
      <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-brand-600">
        <Download className="size-5 text-white" aria-hidden />
      </div>
      <div className="flex-1">
        <p className="text-sm font-semibold text-zinc-900">Install the app</p>
        {canInstall ? (
          <>
            <p className="mt-0.5 text-sm text-zinc-600">Add Ethiopian Student Helper to your home screen for quick, full-screen access.</p>
            <Button size="sm" className="mt-2" onClick={promptInstall}>
              Install
            </Button>
          </>
        ) : (
          <p className="mt-0.5 flex flex-wrap items-center gap-1 text-sm text-zinc-600">
            Tap <Share className="inline size-3.5" aria-hidden /> Share, then{" "}
            <SquarePlus className="inline size-3.5" aria-hidden /> "Add to Home Screen".
          </p>
        )}
      </div>
      {onDismiss && (
        <button onClick={onDismiss} aria-label="Dismiss" className="text-zinc-400 hover:text-zinc-600">
          <X className="size-4" aria-hidden />
        </button>
      )}
    </Card>
  )
}
