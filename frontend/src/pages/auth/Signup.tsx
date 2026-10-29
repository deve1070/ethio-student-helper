import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { GraduationCap } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Field, TextInput, ErrorBanner } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
import { errorMessage } from "../../lib/api"

const GRADES = [9, 10, 11, 12]

export function SignupPage() {
  const { signup } = useAuth()
  const navigate = useNavigate()
  const [fullName, setFullName] = useState("")
  const [identifier, setIdentifier] = useState("")
  const [password, setPassword] = useState("")
  const [grade, setGrade] = useState(12)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const isEmail = identifier.includes("@")
      await signup({
        full_name: fullName || undefined,
        email: isEmail ? identifier : undefined,
        phone_number: isEmail ? undefined : identifier,
        password,
        grade_level: grade,
      })
      navigate("/", { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[#f7f8f7] px-5 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex size-14 items-center justify-center rounded-2xl bg-brand-600">
            <GraduationCap className="size-7 text-white" aria-hidden />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-zinc-900">Create your account</h1>
            <p className="mt-1 text-sm text-zinc-500">It only takes a minute.</p>
          </div>
        </div>

        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          {error && <ErrorBanner message={error} />}
          <Field label="Full name" htmlFor="fullName">
            <TextInput id="fullName" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Phone or email" htmlFor="identifier">
            <TextInput
              id="identifier"
              autoComplete="username"
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              required
            />
          </Field>
          <Field label="Password" htmlFor="password">
            <TextInput
              id="password"
              type="password"
              autoComplete="new-password"
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
          <Field label="Grade" htmlFor="grade">
            <div className="grid grid-cols-4 gap-2">
              {GRADES.map((g) => (
                <button
                  key={g}
                  type="button"
                  onClick={() => setGrade(g)}
                  className={
                    "h-11 rounded-lg border text-sm font-medium transition-colors " +
                    (grade === g
                      ? "border-brand-600 bg-brand-50 text-brand-700"
                      : "border-zinc-300 text-zinc-600 hover:bg-zinc-50")
                  }
                >
                  Grade {g}
                </button>
              ))}
            </div>
          </Field>
          <Button type="submit" size="lg" fullWidth loading={loading}>
            Create account
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-zinc-500">
          Already have an account?{" "}
          <Link to="/login" className="font-medium text-brand-700 hover:underline">
            Log in
          </Link>
        </p>
      </div>
    </div>
  )
}
