import { useEffect, useState } from "react"

/** Chrome/Edge/Android fire this before showing their own install UI - calling preventDefault() lets
 * us show our OWN "Install app" button instead and replay the native prompt whenever the student taps
 * it. Not part of any standard TS DOM lib yet, so typed by hand here. */
interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>
}

function isStandaloneNow(): boolean {
  try {
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      // iOS Safari's own (non-standard) flag - there's no display-mode media query support there
      (window.navigator as unknown as { standalone?: boolean }).standalone === true
    )
  } catch {
    return false
  }
}

/** Drives the "download/install the app" UI (Dashboard banner + Profile row): Android/desktop
 * Chrome/Edge get a real one-tap install via the native beforeinstallprompt event; iOS Safari never
 * fires that event at all, so isIOS tells the caller to show manual "Share -> Add to Home Screen"
 * instructions instead. Nothing is shown once the app is already running standalone (installed). */
export function useInstallPrompt() {
  const [deferredEvent, setDeferredEvent] = useState<BeforeInstallPromptEvent | null>(null)
  const [isStandalone, setIsStandalone] = useState(isStandaloneNow)

  useEffect(() => {
    function onBeforeInstallPrompt(e: Event) {
      e.preventDefault()
      setDeferredEvent(e as BeforeInstallPromptEvent)
    }
    function onInstalled() {
      setDeferredEvent(null)
      setIsStandalone(true)
    }
    window.addEventListener("beforeinstallprompt", onBeforeInstallPrompt)
    window.addEventListener("appinstalled", onInstalled)
    return () => {
      window.removeEventListener("beforeinstallprompt", onBeforeInstallPrompt)
      window.removeEventListener("appinstalled", onInstalled)
    }
  }, [])

  const isIOS = /iphone|ipad|ipod/i.test(window.navigator.userAgent)

  async function promptInstall() {
    if (!deferredEvent) return
    await deferredEvent.prompt()
    const { outcome } = await deferredEvent.userChoice
    if (outcome === "accepted") setIsStandalone(true)
    setDeferredEvent(null) // a prompt can only ever be used once
  }

  return {
    isStandalone,
    canInstall: deferredEvent !== null,
    isIOS: isIOS && !isStandalone,
    promptInstall,
  }
}
