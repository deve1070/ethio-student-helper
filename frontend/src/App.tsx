import { lazy, Suspense } from "react"
import { Navigate, Route, Routes, useSearchParams } from "react-router-dom"
import { AppShell } from "./components/layout/AppShell"
import { FullPageSpinner } from "./components/ui/Primitives"
import { useAuth } from "./lib/auth"
import { LoginPage } from "./pages/auth/Login"
import { SignupPage } from "./pages/auth/Signup"
const ForgotPasswordPage = lazy(() => import("./pages/auth/ForgotPassword").then((m) => ({ default: m.ForgotPasswordPage })))
const OnboardingPage = lazy(() => import("./pages/onboarding/OnboardingPage").then((m) => ({ default: m.OnboardingPage })))
import { DashboardPage } from "./pages/Dashboard"
const ExplainPage = lazy(() => import("./pages/explain/ExplainPage").then((m) => ({ default: m.ExplainPage })))
const PracticeSubjectsPage = lazy(() => import("./pages/practice/PracticeSubjects").then((m) => ({ default: m.PracticeSubjectsPage })))
const PracticeUnitsPage = lazy(() => import("./pages/practice/PracticeUnits").then((m) => ({ default: m.PracticeUnitsPage })))
const PracticeSessionPage = lazy(() => import("./pages/practice/PracticeSession").then((m) => ({ default: m.PracticeSessionPage })))
const ProgressPage = lazy(() => import("./pages/progress/ProgressPage").then((m) => ({ default: m.ProgressPage })))
const LeaderboardPage = lazy(() => import("./pages/leaderboard/LeaderboardPage").then((m) => ({ default: m.LeaderboardPage })))
const MistakesPage = lazy(() => import("./pages/mistakes/MistakesPage").then((m) => ({ default: m.MistakesPage })))
const NotesSubjectsPage = lazy(() => import("./pages/notes/NotesSubjects").then((m) => ({ default: m.NotesSubjectsPage })))
const NotesUnitsPage = lazy(() => import("./pages/notes/NotesUnits").then((m) => ({ default: m.NotesUnitsPage })))
const NotesDetailPage = lazy(() => import("./pages/notes/NotesDetail").then((m) => ({ default: m.NotesDetailPage })))
const EsslceSubjectsPage = lazy(() => import("./pages/esslce/EsslceSubjects").then((m) => ({ default: m.EsslceSubjectsPage })))
const EsslceModePickerPage = lazy(() => import("./pages/esslce/EsslceModePicker").then((m) => ({ default: m.EsslceModePickerPage })))
const EsslcePapersPage = lazy(() => import("./pages/esslce/EsslcePapers").then((m) => ({ default: m.EsslcePapersPage })))
const EsslceCoverPage = lazy(() => import("./pages/esslce/EsslceCover").then((m) => ({ default: m.EsslceCoverPage })))
const EsslceUnitsPage = lazy(() => import("./pages/esslce/EsslceUnits").then((m) => ({ default: m.EsslceUnitsPage })))
const EsslceSessionPage = lazy(() => import("./pages/esslce/EsslceSession").then((m) => ({ default: m.EsslceSessionPage })))
const EsslceSummaryPage = lazy(() => import("./pages/esslce/EsslceSummary").then((m) => ({ default: m.EsslceSummaryPage })))
const CreditsPage = lazy(() => import("./pages/payments/CreditsPage").then((m) => ({ default: m.CreditsPage })))
const BuyPage = lazy(() => import("./pages/payments/BuyPage").then((m) => ({ default: m.BuyPage })))
const ProfilePage = lazy(() => import("./pages/Profile").then((m) => ({ default: m.ProfilePage })))
const StudyPlanPage = lazy(() => import("./pages/studyplan/StudyPlanPage").then((m) => ({ default: m.StudyPlanPage })))

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <>{children}</>
}

function RedirectIfAuthed({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth()
  if (isAuthenticated) return <Navigate to="/" replace />
  return <>{children}</>
}

function RequireOnboarding({ children }: { children: React.ReactNode }) {
  const { fullProfile } = useAuth()
  if (fullProfile === null) return <FullPageSpinner />
  if (!fullProfile.onboarding_completed) return <Navigate to="/onboarding" replace />
  return <>{children}</>
}

function RedirectIfOnboarded({ children }: { children: React.ReactNode }) {
  const { fullProfile } = useAuth()
  const [params] = useSearchParams()
  if (fullProfile === null) return <FullPageSpinner />
  if (fullProfile.onboarding_completed && params.get("edit") !== "1") return <Navigate to="/" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Suspense fallback={<FullPageSpinner />}>
    <Routes>
      <Route
        path="/login"
        element={
          <RedirectIfAuthed>
            <LoginPage />
          </RedirectIfAuthed>
        }
      />
      <Route
        path="/signup"
        element={
          <RedirectIfAuthed>
            <SignupPage />
          </RedirectIfAuthed>
        }
      />
      <Route
        path="/forgot-password"
        element={
          <RedirectIfAuthed>
            <ForgotPasswordPage />
          </RedirectIfAuthed>
        }
      />

      <Route
        path="/onboarding"
        element={
          <RequireAuth>
            <RedirectIfOnboarded>
              <OnboardingPage />
            </RedirectIfOnboarded>
          </RequireAuth>
        }
      />

      <Route
        element={
          <RequireAuth>
            <RequireOnboarding>
              <AppShell />
            </RequireOnboarding>
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/explain" element={<ExplainPage />} />

        <Route path="/practice" element={<PracticeSubjectsPage />} />
        <Route path="/practice/:subject" element={<PracticeUnitsPage />} />
        <Route path="/practice/:subject/session" element={<PracticeSessionPage />} />
        <Route path="/progress" element={<ProgressPage />} />
        <Route path="/mistakes" element={<MistakesPage />} />
        <Route path="/leaderboard" element={<LeaderboardPage />} />

        <Route path="/notes" element={<NotesSubjectsPage />} />
        <Route path="/notes/:subject" element={<NotesUnitsPage />} />
        <Route path="/notes/:subject/:unit" element={<NotesDetailPage />} />

        <Route path="/esslce" element={<EsslceSubjectsPage />} />
        <Route path="/esslce/:subject" element={<EsslceModePickerPage />} />
        <Route path="/esslce/:subject/papers" element={<EsslcePapersPage />} />
        <Route path="/esslce/:subject/start" element={<EsslceCoverPage />} />
        <Route path="/esslce/:subject/units" element={<EsslceUnitsPage />} />
        <Route path="/esslce/:subject/session" element={<EsslceSessionPage />} />
        <Route path="/esslce/:subject/summary" element={<EsslceSummaryPage />} />

        <Route path="/subscription" element={<CreditsPage />} />
        <Route path="/subscribe" element={<BuyPage />} />

        <Route path="/profile" element={<ProfilePage />} />
        <Route path="/study-plan" element={<StudyPlanPage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    </Suspense>
  )
}
