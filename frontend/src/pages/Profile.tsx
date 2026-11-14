import { useState } from "react"
import { Link } from "react-router-dom"
import { Atom, Bot, Calendar, Check, Clock, Copy, Landmark, LogOut, Pencil, Users, User } from "lucide-react"
import { Button } from "../components/ui/Button"
import { Card } from "../components/ui/Card"
import { InstallAppCard } from "../components/ui/InstallAppCard"
import { TelegramIcon } from "../components/ui/icons/TelegramIcon"
import { Badge } from "../components/ui/Primitives"
import { useAuth } from "../lib/auth"
import { LanguageSwitch, useI18n } from "../lib/i18n"

function daysUntil(dateStr: string): number {
  const ms = new Date(dateStr + "T00:00:00").getTime() - new Date().setHours(0, 0, 0, 0)
  return Math.round(ms / 86_400_000)
}

const GOAL_LABELS: Record<number, string> = { 30: "30 minutes", 60: "1 hour", 120: "2 hours", 180: "3+ hours" }

export function ProfilePage() {
  const { logout, gradeLevel, fullProfile } = useAuth()
  const { t } = useI18n()
  const [copied, setCopied] = useState(false)

  async function copyReferralCode() {
    if (!fullProfile) return
    try {
      await navigator.clipboard.writeText(fullProfile.referral_code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard access can fail (older browser, insecure context) - the code is still shown on
      // screen for the student to select/copy by hand
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card className="flex items-center gap-4 p-5">
        <div className="flex size-14 items-center justify-center rounded-full bg-zinc-100">
          <User className="size-7 text-zinc-500" aria-hidden />
        </div>
        <div>
          <p className="font-medium text-zinc-900">Grade {gradeLevel} student</p>
          <p className="text-sm text-zinc-500">Ethiopian Student Helper</p>
        </div>
      </Card>

      <Card className="flex flex-col gap-3 p-4">
        <div className="flex items-center justify-between">
          <p className="text-sm font-semibold text-zinc-900">Study setup</p>
          <Link
            to="/onboarding?edit=1"
            className="flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700"
          >
            <Pencil className="size-3.5" aria-hidden /> Edit
          </Link>
        </div>

        {fullProfile?.stream && (
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-emerald-50">
              {fullProfile.stream === "natural_science" ? (
                <Atom className="size-4 text-emerald-600" aria-hidden />
              ) : (
                <Landmark className="size-4 text-accent-600" aria-hidden />
              )}
            </div>
            <div>
              <p className="text-sm font-medium text-zinc-800 capitalize">
                {fullProfile.stream.replace("_", " ")}
              </p>
              <p className="text-xs text-zinc-500">Stream</p>
            </div>
          </div>
        )}

        {fullProfile?.subjects_selected && fullProfile.subjects_selected.length > 0 && (
          <div>
            <p className="text-xs text-zinc-500">Subjects</p>
            <p className="text-sm text-zinc-800 capitalize">
              {fullProfile.subjects_selected.map((s) => s.replace(/_/g, " ")).join(", ")}
            </p>
          </div>
        )}

        {fullProfile?.exam_date && (
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-brand-50">
              <Calendar className="size-4 text-brand-600" aria-hidden />
            </div>
            <div>
              <p className="text-sm font-medium text-zinc-800">
                {daysUntil(fullProfile.exam_date) >= 0
                  ? `${daysUntil(fullProfile.exam_date)} days to go`
                  : "Exam date has passed"}
              </p>
              <p className="text-xs text-zinc-500">ESSLCE on {fullProfile.exam_date}</p>
            </div>
          </div>
        )}

        {fullProfile?.daily_goal_minutes && (
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-accent-100">
              <Clock className="size-4 text-accent-600" aria-hidden />
            </div>
            <div>
              <p className="text-sm font-medium text-zinc-800">
                {GOAL_LABELS[fullProfile.daily_goal_minutes] ?? `${fullProfile.daily_goal_minutes} minutes`}
              </p>
              <p className="text-xs text-zinc-500">Daily study goal</p>
            </div>
          </div>
        )}

        {fullProfile &&
          !fullProfile.stream &&
          !fullProfile.exam_date &&
          !fullProfile.daily_goal_minutes &&
          (!fullProfile.subjects_selected || fullProfile.subjects_selected.length === 0) && (
            <p className="text-sm text-zinc-500">Nothing set up yet.</p>
          )}
      </Card>

      {fullProfile?.referral_code && (
        <Card className="flex flex-col gap-3 border-brand-200 bg-gradient-to-br from-brand-50 to-white p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Users className="size-4 text-brand-600" aria-hidden />
              <p className="text-sm font-semibold text-zinc-900">Refer & earn</p>
            </div>
            <Badge tone="brand">50 ETB / friend</Badge>
          </div>
          <p className="text-sm text-zinc-600">
            Share your code. When a friend signs up with it and becomes a paying student, you earn
            50 ETB.
          </p>
          <button
            onClick={copyReferralCode}
            className="flex items-center justify-between rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2.5"
          >
            <span className="font-mono text-base font-semibold tracking-wider text-zinc-900">
              {fullProfile.referral_code}
            </span>
            {copied ? (
              <Check className="size-4 text-emerald-600" aria-hidden />
            ) : (
              <Copy className="size-4 text-zinc-400" aria-hidden />
            )}
          </button>
          <div className="flex items-center justify-between rounded-lg bg-white px-3 py-2.5 ring-1 ring-brand-100">
            <div>
              <p className="text-xs text-zinc-500">You've earned</p>
              <p className="text-lg font-bold text-brand-700">
                {fullProfile.referral_earnings_etb.toLocaleString()} ETB
              </p>
            </div>
            <p className="max-w-[55%] text-right text-xs text-zinc-500">
              {fullProfile.referral_paid_count === 0
                ? "No paid referrals yet."
                : `${fullProfile.referral_paid_count} paying student${fullProfile.referral_paid_count === 1 ? "" : "s"} referred`}
            </p>
          </div>
          <p className="text-xs text-zinc-400">
            Payout is sent manually via Telebirr after admin review - contact support if a referral
            is missing.
          </p>
        </Card>
      )}

      <InstallAppCard />

      {fullProfile?.telegram_bot_url && (
        <Card className="flex flex-col gap-2 p-4">
          <div className="flex items-center gap-2">
            <Bot className="size-4 text-brand-600" aria-hidden />
            <p className="text-sm font-semibold text-zinc-900">Telegram account</p>
          </div>
          {fullProfile.telegram_linked ? (
            <p className="flex items-center gap-1.5 text-sm text-emerald-700">
              <Check className="size-4" aria-hidden /> Connected - password reset via Telegram is available.
            </p>
          ) : (
            <>
              <p className="text-sm text-zinc-600">
                Connect your Telegram account to practice from the bot and enable password reset. Open the bot
                below and tap Login (or send:)
              </p>
              <p className="rounded-lg bg-zinc-100 px-3 py-2 font-mono text-xs text-zinc-800">
                /login {fullProfile.email || fullProfile.phone_number || "<phone or email>"} &lt;your password&gt;
              </p>
              <a
                href={fullProfile.telegram_bot_url}
                target="_blank"
                rel="noreferrer"
                className="text-sm font-medium text-brand-700 hover:underline"
              >
                Open @esh_bot on Telegram
              </a>
            </>
          )}
        </Card>
      )}

      {fullProfile?.private_group_url && (
        <Card className="flex items-center gap-4 border-brand-200 bg-brand-50/60 p-4">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-brand-600">
            <TelegramIcon className="size-5 text-white" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-semibold text-zinc-900">Daily mass practice — subscribers only</p>
            <p className="mt-0.5 text-sm text-zinc-600">
              Every evening, the whole group answers the same ESSLCE questions together, then sees
              the answers and the day's ranking. Link your Telegram account first so your request to
              join is approved.
            </p>
            <a
              href={fullProfile.private_group_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline"
            >
              Request to join →
            </a>
          </div>
        </Card>
      )}

      {fullProfile?.telegram_group_url && (
        <Card className="flex items-center gap-4 p-4">
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-[#29A9EB]">
            <TelegramIcon className="size-5 text-white" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-semibold text-zinc-900">Join the student community</p>
            <p className="mt-0.5 text-sm text-zinc-600">
              Discuss exam questions, compare notes, and get help from other students preparing for
              the same ESSLCE.
            </p>
            <a
              href={fullProfile.telegram_group_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline"
            >
              Join the group →
            </a>
          </div>
        </Card>
      )}

      <Card className="flex items-center justify-between gap-3 p-4">
        <p className="text-sm font-semibold text-zinc-900">{t("Language")}</p>
        <LanguageSwitch />
      </Card>

      <Button variant="secondary" onClick={logout}>
        <LogOut className="size-4" aria-hidden /> {t("Log out")}
      </Button>
    </div>
  )
}
