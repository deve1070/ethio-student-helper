import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { AlertTriangle, ArrowLeft } from "lucide-react"
import { Button } from "../../components/ui/Button"
import { Card } from "../../components/ui/Card"
import { ErrorBanner, Field, PasswordInput, TextInput } from "../../components/ui/Primitives"
import { useAuth } from "../../lib/auth"
import { auth, errorMessage } from "../../lib/api"
import { useI18n } from "../../lib/i18n"

const CONFIRM_WORD = "DELETE"

// What deleting removes and keeps is decided in backend/accounts/deletion.py; this page states it.
export function DeleteAccountPage() {
  const { logout } = useAuth()
  const { t } = useI18n()
  const navigate = useNavigate()
  const [password, setPassword] = useState("")
  const [confirm, setConfirm] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function onDelete(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      await auth.deleteAccount(password)
      // logout() makes the login guard redirect at once, which drops router state, so the login page's
      // "account deleted" notice is passed through sessionStorage instead
      try {
        sessionStorage.setItem("esh_account_deleted", "1")
      } catch {
        // storage blocked: the notice is skipped, the deletion still happened
      }
      logout()
      navigate("/login", { replace: true })
    } catch (err) {
      setError(errorMessage(err))
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <Link to="/profile" className="flex items-center gap-1.5 text-sm font-medium text-zinc-500 hover:text-zinc-700">
        <ArrowLeft className="size-4" aria-hidden /> {t("Profile")}
      </Link>

      <Card className="flex flex-col gap-3 border-red-200 bg-red-50/60 p-4">
        <p className="flex items-center gap-2 font-semibold text-red-800">
          <AlertTriangle className="size-5" aria-hidden /> {t("Delete your account permanently")}
        </p>
        <ul className="flex list-disc flex-col gap-1.5 pl-5 text-sm text-zinc-700">
          <li>{t("Your profile, progress, answers, study plans and Telegram link are deleted. This can't be undone.")}</li>
          <li>{t("An active subscription ends with the account and is not refunded.")}</li>
          <li>{t("You'll be removed from the daily practice group.")}</li>
          <li>{t("Records of payments you made are kept for our accounts, without your name or receipt photos.")}</li>
          <li>{t("If you have referral earnings, withdraw them first; deleting is blocked until they're paid.")}</li>
        </ul>
      </Card>

      <form onSubmit={onDelete} className="flex flex-col gap-4">
        {error && <ErrorBanner message={error} />}
        <Field label={t("Your password")} htmlFor="password">
          <PasswordInput id="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Field>
        <Field label={t("Type {word} to confirm", { word: CONFIRM_WORD })} htmlFor="confirm">
          <TextInput id="confirm" autoCapitalize="characters" autoComplete="off" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </Field>
        <Button type="submit" variant="danger" size="lg" fullWidth loading={loading} disabled={!password || confirm.trim().toUpperCase() !== CONFIRM_WORD}>
          {t("Delete my account")}
        </Button>
        <Link to="/profile" className="text-center text-sm font-medium text-zinc-500 hover:text-zinc-700">
          {t("Cancel")}
        </Link>
      </form>
    </div>
  )
}
