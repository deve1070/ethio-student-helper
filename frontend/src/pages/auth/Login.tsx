import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { GraduationCap } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Field, TextInput, ErrorBanner } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
import { errorMessage } from "../../lib/api"

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [identifier, setIdentifier] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await login(identifier, password)
      navigate("/", { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-[#f7f8f7] px-5">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-3 text-center">
          <div className="flex size-14 items-center justify-center rounded-2xl bg-brand-600">
            <GraduationCap className="size-7 text-white" aria-hidden />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-zinc-900">Welcome back</h1>
            <p className="mt-1 text-sm text-zinc-500">Log in to continue studying.</p>
          </div>
        </div>

        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          {error && <ErrorBanner message={error} />}
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
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
          <Button type="submit" size="lg" fullWidth loading={loading}>
            Log in
          </Button>
        </form>

        <p className="mt-6 text-center text-sm text-zinc-500">
          New here?{" "}
          <Link to="/signup" className="font-medium text-brand-700 hover:underline">
            Create an account
          </Link>
        </p>
      </div>
    </div>
  )
}
