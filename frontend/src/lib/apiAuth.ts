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

// A stream (explain/notes) that already committed to an HTTP 200 reports a mid-pipeline failure
// as its final SSE event's "error" field, not an HTTP error status (lib/sse.ts's readSseStream)
// - that's a specific, real reason from the backend, not a network problem, so it's kept distinct
// from a genuine fetch failure (which throws a plain, generic Error) rather than being swallowed
// into the same "couldn't reach the server" fallback below.
export class StreamError extends Error {}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return friendlyDetail(e.detail)
  if (e instanceof StreamError) return e.message
  return "Couldn't reach the server. Check your connection and try again."
}

// A gated AI feature (explain/notes/elaborate/ask/exam-solve) answers "out of free actions,
// not subscribed" with HTTP 402 - callers use this to show a Subscribe CTA instead of a plain
// error banner. friendlyDetail() above still extracts a sensible message either way.
export function isPaywallError(e: unknown): boolean {
  return e instanceof ApiError && e.status === 402
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
