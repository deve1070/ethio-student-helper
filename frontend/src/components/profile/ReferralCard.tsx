import { useEffect, useState } from "react"
import { Check, Copy, Users, Wallet } from "lucide-react"
import { Button } from "../ui/Button"
import { Card } from "../ui/Card"
import { Badge, ErrorBanner, Field, TextInput } from "../ui/Primitives"
import { errorMessage, referrals, type ReferralSummary } from "../../lib/api"

const STATUS_TONE = { pending: "warning", paid: "success", rejected: "danger" } as const
const STATUS_LABEL = { pending: "Waiting", paid: "Paid", rejected: "Rejected" } as const
const METHOD_LABEL = { telebirr: "Telebirr", cbe: "CBE" } as const

const etb = (n: number) => `${n.toLocaleString(undefined, { maximumFractionDigits: 2 })} ETB`

// Referral code, earnings and payouts. A student withdraws their whole available balance to a
// Telebirr number or CBE account; an admin sends it by hand and marks it paid from the bot.
export function ReferralCard({ code }: { code: string }) {
  const [summary, setSummary] = useState<ReferralSummary | null>(null)
  const [copied, setCopied] = useState(false)
  const [formOpen, setFormOpen] = useState(false)
  const [method, setMethod] = useState<"telebirr" | "cbe">("telebirr")
  const [accountNumber, setAccountNumber] = useState("")
  const [accountName, setAccountName] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    referrals.summary().then(setSummary).catch(() => {})
  }, [])

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard access can fail (older browser, insecure context); the code stays on screen to copy by hand
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      setSummary(await referrals.requestPayout({ method, account_number: accountNumber, account_name: accountName }))
      setFormOpen(false)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  const reward = summary?.reward_per_referral_etb
  const hasPending = (summary?.pending_etb ?? 0) > 0

  return (
    <Card className="flex flex-col gap-3 border-brand-200 bg-gradient-to-br from-brand-50 to-white p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users className="size-4 text-brand-600" aria-hidden />
          <p className="text-sm font-semibold text-zinc-900">Refer & earn</p>
        </div>
        {reward !== undefined && <Badge tone="brand">{reward} ETB / friend</Badge>}
      </div>
      <p className="text-sm text-zinc-600">
        Share your code. When a friend signs up with it and becomes a paying student, you earn{" "}
        {reward !== undefined ? `${reward} ETB` : "a reward"}.
      </p>
      <button
        onClick={copyCode}
        className="flex items-center justify-between rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2.5"
      >
        <span className="font-mono text-base font-semibold tracking-wider text-zinc-900">{code}</span>
        {copied ? <Check className="size-4 text-emerald-600" aria-hidden /> : <Copy className="size-4 text-zinc-400" aria-hidden />}
      </button>

      {summary && (
        <>
          <div className="grid grid-cols-3 gap-2 text-center">
            <Stat label="Earned" value={etb(summary.earned_etb)} />
            <Stat label="Withdrawn" value={etb(summary.paid_etb)} />
            <Stat label="Available" value={etb(summary.available_etb)} highlight />
          </div>
          <p className="text-xs text-zinc-500">
            {summary.paid_referrals === 0
              ? "No paid referrals yet."
              : `${summary.paid_referrals} paying student${summary.paid_referrals === 1 ? "" : "s"} referred`}
          </p>

          {hasPending && (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
              {etb(summary.pending_etb)} is on its way. You'll get a Telegram message when it's sent.
            </p>
          )}

          {!hasPending && summary.available_etb > 0 && !formOpen && (
            <Button onClick={() => setFormOpen(true)}>
              <Wallet className="size-4" aria-hidden /> Withdraw {etb(summary.available_etb)}
            </Button>
          )}

          {formOpen && (
            <form onSubmit={submit} className="flex flex-col gap-3 rounded-xl bg-white p-3 ring-1 ring-brand-100">
              {error && <ErrorBanner message={error} />}
              <div className="grid grid-cols-2 gap-2">
                {(["telebirr", "cbe"] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMethod(m)}
                    className={
                      "h-10 rounded-lg border text-sm font-medium transition-colors " +
                      (method === m ? "border-brand-600 bg-brand-50 text-brand-700" : "border-zinc-300 text-zinc-600 hover:bg-zinc-50")
                    }
                  >
                    {METHOD_LABEL[m]}
                  </button>
                ))}
              </div>
              <Field label={method === "telebirr" ? "Telebirr phone number" : "CBE account number"} htmlFor="payoutAccount">
                <TextInput
                  id="payoutAccount"
                  inputMode="numeric"
                  value={accountNumber}
                  onChange={(e) => setAccountNumber(e.target.value)}
                  placeholder={method === "telebirr" ? "09XXXXXXXX" : "1000XXXXXXXXX"}
                  required
                />
              </Field>
              <Field label="Full name on the account" htmlFor="payoutName">
                <TextInput id="payoutName" value={accountName} onChange={(e) => setAccountName(e.target.value)} required />
              </Field>
              <div className="flex gap-2">
                <Button type="button" variant="secondary" onClick={() => setFormOpen(false)}>
                  Cancel
                </Button>
                <Button type="submit" fullWidth loading={submitting}>
                  Request {etb(summary.available_etb)}
                </Button>
              </div>
            </form>
          )}

          {summary.requests.length > 0 && (
            <div className="flex flex-col divide-y divide-zinc-100 rounded-lg bg-white ring-1 ring-zinc-100">
              {summary.requests.map((r) => (
                <div key={r.payout_id} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
                  <div className="min-w-0">
                    <p className="font-medium text-zinc-900">{etb(r.amount_etb)}</p>
                    <p className="truncate text-xs text-zinc-500">
                      {METHOD_LABEL[r.method]} {r.account_number} · {new Date(r.created_at).toLocaleDateString()}
                    </p>
                    {r.admin_note && <p className="truncate text-xs text-zinc-500">{r.admin_note}</p>}
                  </div>
                  <Badge tone={STATUS_TONE[r.status]}>{STATUS_LABEL[r.status]}</Badge>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Card>
  )
}

function Stat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className={"rounded-lg px-2 py-2 " + (highlight ? "bg-brand-600 text-white" : "bg-white ring-1 ring-brand-100")}>
      <p className={"text-[11px] " + (highlight ? "text-brand-100" : "text-zinc-500")}>{label}</p>
      <p className={"text-sm font-bold " + (highlight ? "" : "text-zinc-900")}>{value}</p>
    </div>
  )
}
