import type { StudyPlanTask } from "./api"

/** Shared by Dashboard.tsx's compact "today" widget and studyplan/StudyPlanPage.tsx's full week view -
 * both render the same task shape, just at different day indices. */
export function taskHref(subject: string | null, t: StudyPlanTask): string {
  if (t.kind === "ask") return "/explain"
  if (t.kind === "notes" && subject) {
    return t.unit ? `/notes/${encodeURIComponent(subject)}/${encodeURIComponent(t.unit)}` : `/notes/${encodeURIComponent(subject)}`
  }
  if (t.kind === "practice" && subject) {
    return t.unit ? `/practice/${encodeURIComponent(subject)}/session?units=${encodeURIComponent(t.unit)}` : `/practice/${encodeURIComponent(subject)}`
  }
  if (t.kind === "esslce" && subject) {
    const params = new URLSearchParams({ mode: "practice" })
    if (t.unit) params.set("unit", t.unit)
    else if (t.skill) params.set("skill", t.skill)
    return t.unit || t.skill ? `/esslce/${encodeURIComponent(subject)}/session?${params.toString()}` : `/esslce/${encodeURIComponent(subject)}`
  }
  return "/"
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}
