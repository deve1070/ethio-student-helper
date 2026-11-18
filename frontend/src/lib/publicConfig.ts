import { useEffect, useState } from "react"
import { auth, type PublicConfig } from "./api"

// The price, payment accounts and public links, set once in the backend's settings. Fetched once per
// page load and shared by every component that asks; a failed fetch is retried on the next mount.
let pending: Promise<PublicConfig> | null = null

export function usePublicConfig(): PublicConfig | null {
  const [config, setConfig] = useState<PublicConfig | null>(null)
  useEffect(() => {
    let live = true
    pending ??= auth.publicConfig().catch((e) => {
      pending = null
      throw e
    })
    pending.then((c) => live && setConfig(c)).catch(() => {})
    return () => {
      live = false
    }
  }, [])
  return config
}
