import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import { auth as authApi, getToken, setToken, setUnauthorizedHandler, type Profile } from "./api"

interface LocalProfile {
  userId: string
  gradeLevel: number
}

interface AuthContextValue {
  isAuthenticated: boolean
  profile: LocalProfile | null
  gradeLevel: number
  setGradeLevel: (g: number) => void
  /** null while the real profile hasn't been fetched yet; a routing gate should wait, not redirect */
  fullProfile: Profile | null
  refreshProfile: () => Promise<void>
  login: (identifier: string, password: string) => Promise<void>
  signup: (body: {
    phone_number?: string
    email?: string
    password: string
    full_name?: string
    grade_level?: number
  }) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

const GRADE_KEY = "esh_grade"

export function AuthProvider({ children }: { children: ReactNode }) {
  const [profile, setProfile] = useState<LocalProfile | null>(() => {
    const userId = localStorage.getItem("esh_user_id")
    const grade = Number(localStorage.getItem(GRADE_KEY) ?? 12)
    return getToken() && userId ? { userId, gradeLevel: grade } : null
  })
  const [fullProfile, setFullProfile] = useState<Profile | null>(null)

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setProfile(null)
      setFullProfile(null)
    })
  }, [])

  async function refreshProfile() {
    const p = await authApi.me()
    setFullProfile(p)
    if (p.grade_level) {
      localStorage.setItem(GRADE_KEY, String(p.grade_level))
      setProfile((cur) => (cur ? { ...cur, gradeLevel: p.grade_level! } : cur))
    }
  }

  useEffect(() => {
    if (profile) refreshProfile().catch(() => {}) // non-fatal - the gate just waits/retries on next mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile?.userId])

  const applySession = (token: string, userId: string, gradeLevel?: number) => {
    setToken(token)
    localStorage.setItem("esh_user_id", userId)
    const grade = gradeLevel ?? Number(localStorage.getItem(GRADE_KEY) ?? 12)
    localStorage.setItem(GRADE_KEY, String(grade))
    setFullProfile(null) // force the gate to wait for a fresh fetch under the new session
    setProfile({ userId, gradeLevel: grade })
  }

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated: profile !== null,
      profile,
      gradeLevel: profile?.gradeLevel ?? 12,
      setGradeLevel: (g: number) => {
        localStorage.setItem(GRADE_KEY, String(g))
        setProfile((p) => (p ? { ...p, gradeLevel: g } : p))
      },
      fullProfile,
      refreshProfile,
      login: async (identifier, password) => {
        const res = await authApi.login(identifier, password)
        applySession(res.access_token, res.user_id)
      },
      signup: async (body) => {
        const res = await authApi.signup(body)
        applySession(res.access_token, res.user_id, body.grade_level)
      },
      logout: () => {
        setToken(null)
        localStorage.removeItem("esh_user_id")
        setProfile(null)
        setFullProfile(null)
      },
    }),
    [profile, fullProfile],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within AuthProvider")
  return ctx
}
