// Thin, typed client over the real backend contract (backend/api/routes_*.py). One fetch
// wrapper handles the bearer token and error shape consistently; everything else here just
// types the request/response bodies so a typo in a field name is a compile error, not a runtime
// one discovered by a student.

const BASE = import.meta.env.VITE_API_BASE_URL ?? ""

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

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; isForm?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (options.isForm) {
    body = options.body as FormData
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json"
    body = JSON.stringify(options.body)
  }
  const res = await fetch(`${BASE}${path}`, { method: options.method ?? "GET", headers, body })
  if (res.status === 401) {
    setToken(null)
    onUnauthorized?.()
  }
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

const get = <T>(path: string, params?: Record<string, string | number | boolean | undefined>) => {
  const qs = params
    ? "?" +
      new URLSearchParams(
        Object.entries(params)
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)]),
      ).toString()
    : ""
  return request<T>(`${path}${qs}`)
}
const post = <T>(path: string, body?: unknown) => request<T>(path, { method: "POST", body })
const patch = <T>(path: string, body?: unknown) => request<T>(path, { method: "PATCH", body })

// ---------------------------------------------------------------- auth
export interface TokenResponse {
  access_token: string
  token_type: string
  user_id: string
}
export interface StreamSubjects {
  natural_only: string[]
  social_only: string[]
  common: string[]
}
export interface Profile {
  user_id: string
  full_name: string | null
  email: string | null
  phone_number: string | null
  grade_level: number | null
  stream: "natural_science" | "social_science" | null
  subjects_selected: string[] | null
  exam_date: string | null
  daily_goal_minutes: number | null
  onboarding_completed: boolean
}
export interface UpdateProfileBody {
  grade_level?: number
  stream?: "natural_science" | "social_science"
  subjects_selected?: string[]
  exam_date?: string
  daily_goal_minutes?: number
}
export const auth = {
  signup: (body: {
    phone_number?: string
    email?: string
    password: string
    full_name?: string
    grade_level?: number
  }) => post<TokenResponse>("/v1/auth/signup", body),
  login: (identifier: string, password: string) =>
    post<TokenResponse>("/v1/auth/login", { identifier, password }),
  streams: () => get<StreamSubjects>("/v1/auth/streams"),
  me: () => get<Profile>("/v1/auth/me"),
  updateMe: (body: UpdateProfileBody) => patch<Profile>("/v1/auth/me", body),
}

// ---------------------------------------------------------------- explain
export interface Citation {
  textbook: string
  unit: string
  page: string | null
}
export interface ExplainResponse {
  answer: string
  citations: Citation[]
  credits_charged: number
}
export const explain = {
  ask: (grade: number, subject: string, question: string) =>
    post<ExplainResponse>("/v1/explain", { grade, subject, question }),
}

// ---------------------------------------------------------------- practice
export interface PracticeQuestion {
  id: string
  question: string
  options: string[]
  unit: string | null
  difficulty: string
}
export interface PracticeUnit {
  unit: string
  questions: number
  attempts: number
  accuracy: number | null
  level: string
}
export interface PracticeAnswer {
  is_correct: boolean
  correct_index: number
  explanation: string
  supporting_quote: string
  citation: { textbook: string; unit: string | null; page: string | null }
}
export interface TrendPoint {
  date: string
  attempts: number
  accuracy: number | null
}
export interface PracticeUnitProgress {
  unit: string
  attempts: number
  correct: number
  accuracy: number
  level: string
}
export interface PracticeMistake {
  question_id: string
  question: string
  options: string[]
  chosen_index: number
  correct_index: number
  explanation: string
  unit: string | null
}
export interface PracticeProgress {
  grade: number
  subject: string
  attempts: number
  accuracy: number | null
  weakest_units: string[]
  units: PracticeUnitProgress[]
  trend: TrendPoint[]
}
export const practice = {
  subjects: (grade: number) =>
    get<{ grade: number; subjects: { subject: string; questions: number }[] }>(
      "/v1/practice/subjects",
      { grade },
    ),
  units: (grade: number, subject: string) =>
    get<{ grade: number; subject: string; units: PracticeUnit[] }>("/v1/practice/units", {
      grade,
      subject,
    }),
  next: (grade: number, subject: string, count = 5, units?: string[]) =>
    post<{ questions: PracticeQuestion[] }>("/v1/practice/next", {
      grade,
      subject,
      count,
      ...(units ? { units } : {}),
    }),
  answer: (question_id: string, chosen_index: number) =>
    post<PracticeAnswer>("/v1/practice/answer", { question_id, chosen_index }),
  progress: (grade: number, subject: string) =>
    get<PracticeProgress>("/v1/practice/progress", { grade, subject }),
  mistakes: (grade: number, subject: string, count = 20) =>
    get<PracticeMistake[]>("/v1/practice/mistakes", { grade, subject, count }),
  report: (question_id: string, reason?: string) =>
    post<{ ok: boolean }>("/v1/practice/report", { question_id, reason }),
}

// ---------------------------------------------------------------- esslce
export interface EsslceQuestion {
  id: number
  item_no: number
  stem: string
  options: string[]
  passage_text: string | null
  passage_title: string | null
  unit: string | null
  skill: string | null
  diagram_image_base64: string | null
}
export interface EsslcePaper {
  id: number
  subject: string
  stream: string | null
  year_ec: number
  round: string | null
  region: string | null
  delivery_mode: string | null
  duration_minutes: number | null
  ready_for_students: number
}
export type EsslceMode = "practice" | "exam" | "diagnostic"
export interface EsslceAnswer {
  is_correct: boolean
  correct_index: number
  explanation: string | null
  supporting_quote: string | null
  explanation_image_base64: string | null
}
export interface EsslceCitation {
  textbook: string
  grade: number
  subject: string
  unit_or_chapter: string | null
  section: string | null
  page_start: number | null
  page_end: number | null
}
export interface EsslceElaboration {
  content: string
  is_calculation: boolean
  content_image_base64: string | null
  citation: EsslceCitation | null
}
export interface EsslceUnitProgress {
  grade: number
  unit: string
  attempted: number
  correct: number
  accuracy: number
  level: string
}
export interface EsslceSkillProgress {
  skill: string
  attempted: number
  correct: number
  accuracy: number
  level: string
}
export interface EsslceRecommendation {
  kind: "unit" | "skill"
  grade: number | null
  unit: string | null
  skill: string | null
  attempted: number
  correct: number
  accuracy: number
}
export interface EsslceProgress {
  subject: string
  attempted: number
  correct: number
  units: EsslceUnitProgress[]
  skills: EsslceSkillProgress[]
  recommendation: EsslceRecommendation | null
  trend: TrendPoint[]
}
export interface EsslceMistake {
  question_id: number
  item_no: number
  stem: string
  options: string[]
  passage_text: string | null
  passage_title: string | null
  chosen_index: number
  correct_index: number
  explanation: string | null
  explanation_image_base64: string | null
  unit: string | null
  skill: string | null
}
export interface ExamSummary {
  paper_id: number
  attempted: number
  correct: number
  total_eligible: number
  results: {
    item_no: number
    question_id: number
    chosen_index: number
    is_correct: boolean
    correct_index: number
  }[]
}
export const esslce = {
  subjects: () => get<{ subjects: { subject: string; questions: number }[] }>("/v1/esslce/subjects"),
  papers: (subject: string) => get<{ subject: string; papers: EsslcePaper[] }>("/v1/esslce/papers", { subject }),
  units: (subject: string) =>
    get<{ subject: string; units: { unit: string; grade: number; questions: number }[] }>(
      "/v1/esslce/units",
      { subject },
    ),
  skills: (subject: string) =>
    get<{ subject: string; skills: { skill: string; questions: number }[] }>("/v1/esslce/skills", {
      subject,
    }),
  progress: (subject: string) => get<EsslceProgress>("/v1/esslce/progress", { subject }),
  mistakes: (subject: string, count = 20) =>
    get<EsslceMistake[]>("/v1/esslce/mistakes", { subject, count }),
  diagnostic: (subject: string, count = 15, stream?: string) =>
    post<{ paper_id: number | null; questions: EsslceQuestion[] }>("/v1/esslce/diagnostic", {
      subject,
      count,
      ...(stream ? { stream } : {}),
    }),
  next: (args: {
    subject: string
    paper_id?: number
    stream?: string
    unit?: string
    grade?: number
    skill?: string
    incorrect_only?: boolean
    count?: number
  }) => post<{ paper_id: number | null; questions: EsslceQuestion[] }>("/v1/esslce/next", args),
  answer: (question_id: number, chosen_index: number, mode: EsslceMode) =>
    post<EsslceAnswer>("/v1/esslce/answer", { question_id, chosen_index, mode }),
  elaborate: (question_id: number) =>
    post<EsslceElaboration>("/v1/esslce/elaborate", { question_id }),
  ask: (question_id: number, message: string, history: { role: "user" | "assistant"; content: string }[]) =>
    post<{ reply: string; reply_image_base64: string | null }>("/v1/esslce/ask", {
      question_id,
      message,
      history,
    }),
  examSummary: (paper_id: number) => post<ExamSummary>("/v1/esslce/exam-summary", { paper_id }),
}

// ---------------------------------------------------------------- progress (cross-system)
export const progress = {
  streak: () => get<{ streak_days: number }>("/v1/progress/streak"),
}

// ---------------------------------------------------------------- study plan (cross-system)
export interface StudyPlanTask {
  kind: "practice" | "esslce" | "mistakes" | "ask"
  label: string
  subject: string | null
  unit: string | null
  skill: string | null
  minutes: number | null
  done: boolean
}
export interface StudyPlanResponse {
  plan_date: string
  tasks: StudyPlanTask[]
}
export const studyPlan = {
  today: () => get<StudyPlanResponse>("/v1/study-plan/today"),
  markDone: (index: number, done: boolean) =>
    post<StudyPlanResponse>(`/v1/study-plan/today/tasks/${index}/done?done=${done}`),
}

// ---------------------------------------------------------------- study notes
export interface StudyNoteCitation {
  textbook: string
  grade: number
  subject: string
  unit_or_chapter: string | null
  section: string | null
  page_start: number | null
  page_end: number | null
}
export interface StudyNoteSection {
  number: string
  heading: string
  summary: string
  citation: StudyNoteCitation | null
}
export interface StudyNote {
  subject: string
  unit: string
  overview: string
  sections: StudyNoteSection[]
  key_formulas: string[] | null
  formulas_image_base64: string | null
  worked_example: string | null
  worked_example_image_base64: string | null
  is_calculation: boolean
}
export const notes = {
  subjects: (grade: number) => get<{ grade: number; subjects: string[] }>("/v1/notes/subjects", { grade }),
  units: (grade: number, subject: string) =>
    get<{ grade: number; subject: string; units: string[] }>("/v1/notes/units", { grade, subject }),
  note: (grade: number, subject: string, unit: string) =>
    get<StudyNote>("/v1/notes/note", { grade, subject, unit }),
}

// ---------------------------------------------------------------- payments
export interface CreditsResponse {
  balance: number
  has_active_subscription: boolean
}
export interface SubmitReceiptResponse {
  payment_id: string
  status: "completed" | "pending"
  message: string
}
export const payments = {
  credits: () => get<CreditsResponse>("/v1/me/credits"),
  submitReceipt: (bundle: string, transactionId: string, file: File) => {
    const form = new FormData()
    form.append("bundle", bundle)
    form.append("transaction_id", transactionId)
    form.append("receipt", file)
    return request<SubmitReceiptResponse>("/v1/payments/submit-receipt", {
      method: "POST",
      body: form,
      isForm: true,
    })
  },
}
