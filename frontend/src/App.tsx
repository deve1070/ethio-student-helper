import { Navigate, Route, Routes, useSearchParams } from "react-router-dom"
import { AppShell } from "./components/layout/AppShell"
import { FullPageSpinner } from "./components/ui/Primitives"
import { useAuth } from "./lib/auth"
import { LoginPage } from "./pages/auth/Login"
import { SignupPage } from "./pages/auth/Signup"
import { OnboardingPage } from "./pages/onboarding/OnboardingPage"
import { DashboardPage } from "./pages/Dashboard"
import { ExplainPage } from "./pages/explain/ExplainPage"
import { PracticeSubjectsPage } from "./pages/practice/PracticeSubjects"
import { PracticeUnitsPage } from "./pages/practice/PracticeUnits"
import { PracticeSessionPage } from "./pages/practice/PracticeSession"
import { ProgressPage } from "./pages/progress/ProgressPage"
import { MistakesPage } from "./pages/mistakes/MistakesPage"
import { NotesSubjectsPage } from "./pages/notes/NotesSubjects"
import { NotesUnitsPage } from "./pages/notes/NotesUnits"
import { NotesDetailPage } from "./pages/notes/NotesDetail"
import { EsslceSubjectsPage } from "./pages/esslce/EsslceSubjects"
import { EsslceModePickerPage } from "./pages/esslce/EsslceModePicker"
import { EsslcePapersPage } from "./pages/esslce/EsslcePapers"
import { EsslceUnitsPage } from "./pages/esslce/EsslceUnits"
import { EsslceSessionPage } from "./pages/esslce/EsslceSession"
import { EsslceSummaryPage } from "./pages/esslce/EsslceSummary"
import { CreditsPage } from "./pages/payments/CreditsPage"
import { BuyPage } from "./pages/payments/BuyPage"
import { ProfilePage } from "./pages/Profile"

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

        <Route path="/notes" element={<NotesSubjectsPage />} />
        <Route path="/notes/:subject" element={<NotesUnitsPage />} />
        <Route path="/notes/:subject/:unit" element={<NotesDetailPage />} />

        <Route path="/esslce" element={<EsslceSubjectsPage />} />
        <Route path="/esslce/:subject" element={<EsslceModePickerPage />} />
        <Route path="/esslce/:subject/papers" element={<EsslcePapersPage />} />
        <Route path="/esslce/:subject/units" element={<EsslceUnitsPage />} />
        <Route path="/esslce/:subject/session" element={<EsslceSessionPage />} />
        <Route path="/esslce/:subject/summary" element={<EsslceSummaryPage />} />

        <Route path="/credits" element={<CreditsPage />} />
        <Route path="/credits/buy" element={<BuyPage />} />

        <Route path="/profile" element={<ProfilePage />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
