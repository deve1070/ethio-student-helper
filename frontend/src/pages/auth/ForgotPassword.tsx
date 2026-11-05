import { useEffect, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { GraduationCap } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Field, TextInput, ErrorBanner } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
import { auth as authApi, errorMessage } from "../../lib/api"

type Step = "identifier" | "no_link" | "code"

export function ForgotPasswordPage() {
  const { confirmPasswordReset } = useAuth()
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>("identifier")
  const [identifier, setIdentifier] = useState("")
  const [code, setCode] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [groupUrl, setGroupUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    authApi.publicConfig().then((c) => setGroupUrl(c.telegram_group_url)).catch(() => {})
  }, [])

  async function onRequest(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const res = await authApi.requestPasswordReset(identifier)
      setStep(res.status === "code_sent" ? "code" : "no_link")
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }

  async function onConfirm(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await confirmPasswordReset(identifier, code, newPassword)
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
            <h1 className="text-xl font-semibold text-zinc-900">Reset your password</h1>
            <p className="mt-1 text-sm text-zinc-500">
              {step === "code"
                ? "Check Telegram for your code."
                : "We'll send a code to your linked Telegram account."}
            </p>
          </div>
        </div>

        {error && <div className="mb-4"><ErrorBanner message={error} /></div>}

        {step === "identifier" && (
          <form onSubmit={onRequest} className="flex flex-col gap-4">
            <Field label="Phone or email" htmlFor="identifier">
              <TextInput
                id="identifier"
                autoComplete="username"
                value={identifier}
                onChange={(e) => setIdentifier(e.target.value)}
                required
              />
            </Field>
            <Button type="submit" size="lg" fullWidth loading={loading}>
              Send reset code
            </Button>
          </form>
        )}

        {step === "no_link" && (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-zinc-700">
              We can't send a reset code for this account yet - Telegram-based reset only works once
              you've linked your Telegram account. Open our Telegram bot and send:
            </p>
            <p className="rounded-lg bg-zinc-100 px-3 py-2 font-mono text-sm text-zinc-800">
              /login {identifier || "<phone or email>"} &lt;your current password&gt;
            </p>
            <p className="text-sm text-zinc-700">
              Then come back and try again. If you don't remember your password at all and have never
              linked Telegram, we can't recover it automatically{groupUrl ? " - message us" : "."}
              {groupUrl && (
                <>
                  {" "}in our{" "}
                  <a href={groupUrl} target="_blank" rel="noreferrer" className="font-medium text-brand-700 hover:underline">
                    Telegram group
                  </a>
                  {" "}for help.
                </>
              )}
            </p>
            <Button variant="secondary" fullWidth onClick={() => setStep("identifier")}>
              Try a different phone or email
            </Button>
            <Link to="/login" className="text-center text-sm font-medium text-brand-700 hover:underline">
              Back to login
            </Link>
          </div>
        )}

        {step === "code" && (
          <form onSubmit={onConfirm} className="flex flex-col gap-4">
            <Field label="6-digit code" htmlFor="code">
              <TextInput
                id="code"
                inputMode="numeric"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
              />
            </Field>
            <Field label="New password" htmlFor="newPassword">
              <TextInput
                id="newPassword"
                type="password"
                autoComplete="new-password"
                minLength={8}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
              />
            </Field>
            <Button type="submit" size="lg" fullWidth loading={loading}>
              Reset password
            </Button>
          </form>
        )}

        <p className="mt-6 text-center text-sm text-zinc-500">
          <Link to="/login" className="font-medium text-brand-700 hover:underline">
            Back to login
          </Link>
        </p>
      </div>
    </div>
  )
}
