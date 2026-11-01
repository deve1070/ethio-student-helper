// Reads a Server-Sent Events response from this app's own backend (api/routes_explain.py,
// api/routes_notes.py) as it streams in, instead of waiting for the whole response like
// lib/api.ts's request() does. Uses fetch + a ReadableStream reader rather than the browser's
// native EventSource: EventSource only supports GET with no custom headers, and this app's auth
// is a bearer token in a request header, not a cookie EventSource could send automatically.
//
// Every event on this backend's streams is one JSON object. Every event except the last one
// carries a "stage" label (student-facing progress text); the last one carries "done": true
// plus either the final result fields or an "error" message - streaming already committed to
// an HTTP 200 by the time a mid-pipeline failure (an unavailable LLM, an ungroundable topic) can
// happen, so those failures travel as that last event's "error" field, not an HTTP error status.

import { ApiError, getToken } from "./api"

export interface StreamEvent {
  stage?: string
  done?: boolean
  error?: string
  [key: string]: unknown
}

const BASE = import.meta.env.VITE_API_BASE_URL ?? ""

async function readSseStream(
  res: Response,
  onEvent: (event: StreamEvent) => void,
): Promise<StreamEvent> {
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  let final: StreamEvent | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split("\n\n")
    buffer = parts.pop() ?? ""
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data: "))
      if (!line) continue
      const event: StreamEvent = JSON.parse(line.slice("data: ".length))
      onEvent(event)
      if (event.done) final = event
    }
  }
  if (!final) throw new Error("Stream ended without a final event")
  return final
}

async function streamRequest(
  path: string,
  init: RequestInit,
  onEvent: (event: StreamEvent) => void,
): Promise<StreamEvent> {
  const token = getToken()
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) }
  if (token) headers.Authorization = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  const final = await readSseStream(res, onEvent)
  if (final.error) throw new Error(final.error)
  return final
}

export function streamGet(
  path: string,
  params: Record<string, string | number | boolean>,
  onEvent: (event: StreamEvent) => void,
): Promise<StreamEvent> {
  const qs = "?" + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()
  return streamRequest(`${path}${qs}`, { method: "GET" }, onEvent)
}

export function streamPost(
  path: string,
  body: unknown,
  onEvent: (event: StreamEvent) => void,
): Promise<StreamEvent> {
  return streamRequest(
    path,
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
    onEvent,
  )
}
