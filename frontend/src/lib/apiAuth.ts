// The bearer-token/error-shape primitives shared by lib/api.ts (plain request/response calls)
// and lib/sse.ts (streamed calls) - split out so sse.ts can use them without importing api.ts,
// which imports sse.ts back (explain.ask/notes.note stream) and would otherwise be a circular
// module dependency between the two.

export const BASE = import.meta.env.VITE_API_BASE_URL ?? ""

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail))
    this.status = status
    this.detail = detail
  }
}

function friendlyDetail(detail: unknown): string {
  if (typeof detail === "string") return detail
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message)
  }
  return "Something went wrong. Please try again."
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return friendlyDetail(e.detail)
  return "Couldn't reach the server. Check your connection and try again."
}

let token: string | null = localStorage.getItem("esh_token")
let onUnauthorized: (() => void) | null = null

export function setToken(t: string | null) {
  token = t
  if (t) localStorage.setItem("esh_token", t)
  else localStorage.removeItem("esh_token")
}
export function getToken() {
  return token
}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}
export function notifyUnauthorized() {
  onUnauthorized?.()
}
