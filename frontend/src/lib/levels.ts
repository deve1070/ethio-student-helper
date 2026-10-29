// Shared vocabulary for the mastery levels the backend computes (practice.selection.classify_level,
// reused by both the QuizQuestion-practice and ESSLCE progress endpoints). One mapping here, not
// redefined per page, so "weak" always reads the same color and label everywhere in the app.
export const LEVEL_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  strong: "success",
  learning: "warning",
  weak: "danger",
  "not enough data": "neutral",
}

export const LEVEL_LABEL: Record<string, string> = {
  strong: "Strong",
  learning: "Improving",
  weak: "Needs practice",
  "not enough data": "Not enough data",
}
