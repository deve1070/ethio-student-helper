// Where a student came from, for counting which links bring signups (the bot's /channel_stats).
// A link like https://…/?src=channel tags the visit; the first tag seen on this device is kept until
// signup, so a student who taps a channel post, looks around, and signs up days later still counts.
// Storage can be unavailable (private windows, blocked site data): then nothing is recorded.

const KEY = "esh_signup_source"
const VALID = /^[a-z0-9_-]{1,32}$/

export function rememberSignupSource(search: string = window.location.search): void {
  const src = new URLSearchParams(search).get("src")?.trim().toLowerCase()
  if (!src || !VALID.test(src)) return
  try {
    if (!localStorage.getItem(KEY)) localStorage.setItem(KEY, src)
  } catch {
    // storage blocked: the signup is simply untagged
  }
}

export function signupSource(): string | undefined {
  try {
    return localStorage.getItem(KEY) ?? undefined
  } catch {
    return undefined
  }
}
