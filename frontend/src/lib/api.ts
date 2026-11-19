// Thin, typed client over the real backend contract (backend/api/routes_*.py). One fetch
// wrapper handles the bearer token and error shape consistently; everything else here just
// types the request/response bodies so a typo in a field name is a compile error, not a runtime
// one discovered by a student.
//
// The token/ApiError primitives themselves live in ./apiAuth, re-exported below so every
// existing `import { errorMessage, setToken, ... } from "./api"` keeps working unchanged -
// they moved out so lib/sse.ts (which explain.ask/notes.note below depend on) can use them
// without importing this file back and creating a circular module dependency.
import { ApiError, BASE, getToken, notifyUnauthorized, setToken } from "./apiAuth"
import { streamGet, streamPost } from "./sse"
import { signupSource } from "./signupSource"

export * from "./apiAuth"

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; isForm?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
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
    notifyUnauthorized()
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
  referral_code: string
  telegram_channel_url: string | null
  telegram_bot_url: string | null
  private_group_url: string | null
  telegram_linked: boolean
  school_id: number | null
  school_name: string | null
  is_ambassador: boolean
  nudges_off: boolean
}
export interface UpdateProfileBody {
  grade_level?: number
  stream?: "natural_science" | "social_science"
  subjects_selected?: string[]
  exam_date?: string
  daily_goal_minutes?: number
  school_id?: number | null // null clears it
}
export interface PublicConfig {
  telegram_channel_url: string | null
  telegram_bot_url: string | null
  web_app_url: string
  subscription_price_etb: number
  referral_reward_etb: number
  payment_telebirr_number: string
  payment_cbe_account: string
}
export interface PasswordResetRequestResponse {
  status: "code_sent" | "no_telegram_link"
}
export const auth = {
  publicConfig: () => get<PublicConfig>("/v1/auth/public-config"),
  signup: (body: {
    phone_number?: string
    email?: string
    password: string
    full_name?: string
    grade_level?: number
    referral_code?: string
  }) => post<TokenResponse>("/v1/auth/signup", { ...body, signup_source: signupSource() }),
  login: (identifier: string, password: string) =>
    post<TokenResponse>("/v1/auth/login", { identifier, password }),
  streams: () => get<StreamSubjects>("/v1/auth/streams"),
  me: () => get<Profile>("/v1/auth/me"),
  updateMe: (body: UpdateProfileBody) => patch<Profile>("/v1/auth/me", body),
  deleteAccount: (password: string) => post<{ deleted: boolean }>("/v1/auth/me/delete", { password }),
  requestPasswordReset: (identifier: string) =>
    post<PasswordResetRequestResponse>("/v1/auth/password-reset/request", { identifier }),
  confirmPasswordReset: (identifier: string, code: string, new_password: string) =>
    post<TokenResponse>("/v1/auth/password-reset/confirm", { identifier, code, new_password }),
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
}
export const explain = {
  // Streams progress ("Writing an answer...", etc.) via onStage while the backend works through
  // its multi-step pipeline (api/routes_explain.py), resolving with the final answer once done.
  ask: (grade: number, subject: string, question: string, onStage: (stage: string) => void) =>
    streamPost("/v1/explain", { grade, subject, question }, (e) => {
      if (e.stage) onStage(e.stage)
    }).then((e) => e as unknown as ExplainResponse),
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
/** Why the option the student picked looked right, and what is wrong with it. */
export interface WrongChoiceNote {
  chosen_index: number
  tempting: string
  wrong: string
}
export interface PracticeAnswer {
  is_correct: boolean
  correct_index: number
  explanation: string
  supporting_quote: string
  citation: { textbook: string; unit: string | null; page: string | null }
  why_wrong: WrongChoiceNote | null // only when wrong and already stored; otherwise ask practice.whyWrong
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
  why_wrong: WrongChoiceNote | null
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
  whyWrong: (question_id: string, chosen_index: number) =>
    post<WrongChoiceNote>("/v1/practice/why-wrong", { question_id, chosen_index }),
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
  year_ec: number
  booklet_code: string | null
  section: string | null
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
  why_wrong: WrongChoiceNote | null // only when wrong and already stored; otherwise ask esslce.whyWrong
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
  year_ec: number
  booklet_code: string | null
  section: string | null
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
  why_wrong: WrongChoiceNote | null
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
export interface EsslceExamCover {
  paper_id: number
  subject: string
  year_ec: number
  stream: string | null
  region: string | null
  round: string | null
  item_count: number
  sections: string[]
}
export interface UnitInsight {
  available: boolean
  question_count: number
  years_appeared: number
  total_years: number
  per_year: Record<string, number>
  concepts: string[]
  styles: string[]
  tips: string[]
}
export const esslce = {
  subjects: () => get<{ subjects: { subject: string; questions: number }[] }>("/v1/esslce/subjects"),
  papers: (subject: string) => get<{ subject: string; papers: EsslcePaper[] }>("/v1/esslce/papers", { subject }),
  paperCover: (paperId: number) => get<EsslceExamCover>(`/v1/esslce/papers/${paperId}/cover`),
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
    review_due?: boolean
    count?: number
  }) => post<{ paper_id: number | null; questions: EsslceQuestion[] }>("/v1/esslce/next", args),
  answer: (question_id: number, chosen_index: number, mode: EsslceMode) =>
    post<EsslceAnswer>("/v1/esslce/answer", { question_id, chosen_index, mode }),
  whyWrong: (question_id: number, chosen_index: number) =>
    post<WrongChoiceNote>("/v1/esslce/why-wrong", { question_id, chosen_index }),
  elaborate: (question_id: number) =>
    post<EsslceElaboration>("/v1/esslce/elaborate", { question_id }),
  ask: (question_id: number, message: string, history: { role: "user" | "assistant"; content: string }[]) =>
    post<{ reply: string; reply_image_base64: string | null }>("/v1/esslce/ask", {
      question_id,
      message,
      history,
    }),
  unitInsight: (subject: string, unit: string, grade: number) =>
    get<UnitInsight>("/v1/esslce/unit-insight", { subject, unit, grade }),
  reviewCount: () =>
    get<{ total: number; subjects: { subject: string; due: number }[] }>("/v1/esslce/review-count"),
  examSummary: (paper_id: number) => post<ExamSummary>("/v1/esslce/exam-summary", { paper_id }),
}

// ---------------------------------------------------------------- progress (cross-system)
export interface SubjectReadiness {
  subject: string
  projected: number | null // 0-1; null until the student has answered enough in the subject
  coverage: number // 0-1: share of the exam made up of units with enough answers to count
  answered: number
}
export const progress = {
  streak: () => get<{ streak_days: number }>("/v1/progress/streak"),
  readiness: () =>
    get<{ exam_date: string | null; days_left: number | null; subjects: SubjectReadiness[] }>(
      "/v1/progress/readiness",
    ),
}

// ---------------------------------------------------------------- mass-practice leaderboard
// (the daily subscriber-only Telegram group challenge - backend/api/routes_mass_challenge.py;
// both leaderboard reads are deliberately unauthenticated, see that file's own comment)
export interface ChallengeLeaderboardEntry {
  user_id: string
  display_name: string
  correct: number
  answered: number
}
export interface ChallengeLeaderboard {
  challenge_id: number
  subject: string
  unit: string
  total_questions: number
  entries: ChallengeLeaderboardEntry[]
}
export interface ConsistencyLeaderboardEntry {
  user_id: string
  display_name: string
  questions_answered: number
  days_participated: number
}
export interface WeeklyLeaderboardEntry {
  user_id: string
  display_name: string
  correct: number
  answered: number
  days_participated: number
}
// One day can have two challenges, one per stream, when that day's subject is not common to both.
export interface LatestChallenges {
  date: string
  challenges: { id: number; stream: string; subject: string; unit: string }[]
}
export const massChallenge = {
  latest: () => get<LatestChallenges | null>("/v1/mass-challenge/latest"),
  weeklyLeaderboard: () =>
    get<{ entries: WeeklyLeaderboardEntry[] }>("/v1/mass-challenge/weekly-leaderboard"),
  leaderboard: (challengeId: number) =>
    get<ChallengeLeaderboard>(`/v1/mass-challenge/${challengeId}/leaderboard`),
  consistencyLeaderboard: () =>
    get<{ entries: ConsistencyLeaderboardEntry[] }>("/v1/mass-challenge/consistency-leaderboard"),
}

// ---------------------------------------------------------------- study plan (cross-system)
export interface StudyPlanTask {
  kind: "notes" | "practice" | "esslce" | "ask"
  label: string
  subject: string | null
  unit: string | null
  skill: string | null
  minutes: number | null
  done: boolean
}
export interface StudyPlanDay {
  date: string
  rationale: string
  tasks: StudyPlanTask[]
}
export interface StudyPlanResponse {
  week_start_date: string
  days_remaining: number | null
  realistic: boolean
  shortfall_minutes: number
  missing_subjects: string[]
  coverage: Record<string, number | null>
  weekly_note: string
  days: StudyPlanDay[]
}
export const studyPlan = {
  week: () => get<StudyPlanResponse>("/v1/study-plan/week"),
  markDone: (dayIndex: number, taskIndex: number, done: boolean) =>
    post<StudyPlanResponse>(`/v1/study-plan/week/days/${dayIndex}/tasks/${taskIndex}/done?done=${done}`),
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
  examples: string[] // worked examples for THIS subtopic's own formula - only ever non-empty for a
  // calculation subject; rendered via MathText, same as summary (see notes/store.py's CALC_UNIT_PROMPT)
  citation: StudyNoteCitation | null
}
export interface StudyNote {
  subject: string
  unit: string
  overview: string
  sections: StudyNoteSection[]
  is_calculation: boolean
}
export const notes = {
  subjects: (grade: number) => get<{ grade: number; subjects: string[] }>("/v1/notes/subjects", { grade }),
  units: (grade: number, subject: string) =>
    get<{ grade: number; subject: string; units: string[] }>("/v1/notes/units", { grade, subject }),
  // Streams progress ("Reading your textbook...", etc.) via onStage while the backend works
  // through notes/store.py's generation steps, resolving with the finished note (cache hits
  // resolve immediately with no stage events at all - there's nothing to report).
  note: (grade: number, subject: string, unit: string, onStage: (stage: string) => void) =>
    streamGet("/v1/notes/note", { grade, subject, unit }, (e) => {
      if (e.stage) onStage(e.stage)
    }).then((e) => e as unknown as StudyNote),
}

// ---------------------------------------------------------------- payments
export interface EntitlementResponse {
  has_active_subscription: boolean
  subscription_expires_at: string | null
  free_actions_used: number
  free_actions_quota: number
}
export interface SubmitReceiptResponse {
  payment_id: string
  status: "completed" | "pending"
  message: string
}
export interface ReferralPayout {
  payout_id: string
  amount_etb: number
  method: "telebirr" | "cbe"
  account_number: string
  account_name: string
  status: "pending" | "paid" | "rejected"
  admin_note: string | null
  created_at: string
  reviewed_at: string | null
}
export interface ReferralSummary {
  reward_per_referral_etb: number
  paid_referrals: number
  earned_etb: number
  paid_etb: number
  pending_etb: number
  available_etb: number
  requests: ReferralPayout[]
}
export interface School {
  id: number
  name: string
}
export const schools = {
  list: () => get<School[]>("/v1/schools"),
}
export const growth = {
  setTips: (off: boolean) => post<{ off: boolean }>("/v1/growth/nudges-setting", { off }),
}

export const referrals = {
  summary: () => get<ReferralSummary>("/v1/referrals/payouts"),
  requestPayout: (body: { method: "telebirr" | "cbe"; account_number: string; account_name: string }) =>
    post<ReferralSummary>("/v1/referrals/payouts", body),
}

export const payments = {
  entitlement: () => get<EntitlementResponse>("/v1/me/entitlement"),
  submitReceipt: (transactionId: string, file: File) => {
    const form = new FormData()
    form.append("plan", "yearly")
    form.append("transaction_id", transactionId)
    form.append("receipt", file)
    return request<SubmitReceiptResponse>("/v1/payments/submit-receipt", {
      method: "POST",
      body: form,
      isForm: true,
    })
  },
}
