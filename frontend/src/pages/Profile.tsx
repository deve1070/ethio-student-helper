import { useEffect, useState, type ReactNode } from "react"
import { Link } from "react-router-dom"
import {
  BarChart3,
  Bot,
  Calendar,
  Check,
  ChevronRight,
  Clock,
  Globe,
  Heart,
  LogOut,
  Megaphone,
  Pencil,
  Trophy,
  Wallet,
} from "lucide-react"
import { Button } from "../components/ui/Button"
import { Card } from "../components/ui/Card"
import { InstallAppCard } from "../components/ui/InstallAppCard"
import { ReferralCard } from "../components/profile/ReferralCard"
import { BotTipsSwitch, SchoolPicker } from "../components/profile/SettingsRows"
import { useAuth } from "../lib/auth"
import { payments } from "../lib/api"
import { LanguageSwitch, useI18n } from "../lib/i18n"

function daysUntil(dateStr: string): number {
  const ms = new Date(dateStr + "T00:00:00").getTime() - new Date().setHours(0, 0, 0, 0)
  return Math.round(ms / 86_400_000)
}

const GOAL_LABELS: Record<number, string> = { 30: "30 minutes", 60: "1 hour", 120: "2 hours", 180: "3+ hours" }
const STREAM_LABELS = { natural_science: "Natural Science", social_science: "Social Science" } as const

// "https://t.me/some_bot" -> "@some_bot", so the link text always names the bot actually configured
function telegramHandle(url: string): string {
  const name = url.replace(/\/+$/, "").split("/").pop()
  return name ? `@${name}` : url
}

export function ProfilePage() {
  const { logout, gradeLevel, fullProfile } = useAuth()
  const { t } = useI18n()
  const [subscribed, setSubscribed] = useState<boolean | null>(null)
  const [showLinkHelp, setShowLinkHelp] = useState(false)

  useEffect(() => {
    payments
      .entitlement()
      .then((e) => setSubscribed(e.has_active_subscription))
      .catch(() => setSubscribed(null))
  }, [])

  const p = fullProfile
  const initial = (p?.full_name || p?.email || p?.phone_number || "S").trim().charAt(0).toUpperCase()
  const setupChips = [
    p?.exam_date && {
      icon: Calendar,
      text: daysUntil(p.exam_date) >= 0 ? t("{n} days to go", { n: daysUntil(p.exam_date) }) : t("Exam date has passed"),
    },
    p?.daily_goal_minutes && { icon: Clock, text: t(GOAL_LABELS[p.daily_goal_minutes] ?? `${p.daily_goal_minutes} minutes`) + " / " + t("day") },
    p?.subjects_selected?.length && { icon: Check, text: t("{n} subjects", { n: p.subjects_selected.length }) },
  ].filter(Boolean) as { icon: typeof Calendar; text: string }[]

  return (
    <div className="flex flex-col gap-5">
      <Card className="flex flex-col gap-4 p-4">
        <div className="flex items-center gap-3.5">
          <div className="flex size-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-brand-700 text-xl font-semibold text-white">
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold text-zinc-900">{p?.full_name || t("Student")}</p>
            <p className="truncate text-sm text-zinc-500">
              {t("Grade {n}", { n: gradeLevel })}
              {p?.stream && ` · ${t(STREAM_LABELS[p.stream])}`}
            </p>
          </div>
          <Link
            to="/onboarding?edit=1"
            className="flex shrink-0 items-center gap-1 rounded-full bg-zinc-100 px-3 py-1.5 text-xs font-medium text-zinc-700 hover:bg-zinc-200"
          >
            <Pencil className="size-3.5" aria-hidden /> {t("Edit")}
          </Link>
        </div>
        {setupChips.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {setupChips.map((c) => (
              <span key={c.text} className="flex items-center gap-1.5 rounded-full bg-zinc-50 px-2.5 py-1 text-xs text-zinc-600 ring-1 ring-zinc-200">
                <c.icon className="size-3.5 text-brand-600" aria-hidden /> {c.text}
              </span>
            ))}
          </div>
        )}
      </Card>

      <Section title={t("Your account")}>
        <Row
          to="/subscription"
          icon={Wallet}
          label={t("Subscription")}
          value={subscribed === null ? undefined : subscribed ? t("Active") : t("Free plan")}
          valueTone={subscribed ? "good" : undefined}
        />
        <Row to="/progress" icon={BarChart3} label={t("Progress")} />
        {p?.telegram_bot_url && (
          <>
            <Row
              icon={Bot}
              label={t("Telegram bot")}
              value={p.telegram_linked ? t("Connected") : t("Connect")}
              valueTone={p.telegram_linked ? "good" : "action"}
              onClick={p.telegram_linked ? undefined : () => setShowLinkHelp((v) => !v)}
            />
            {!p.telegram_linked && showLinkHelp && (
              <div className="flex flex-col gap-2 px-4 pb-4 text-sm text-zinc-600">
                <p>{t("Link your account to practise from the bot and to reset your password through Telegram. Open the bot and send:")}</p>
                <p className="rounded-lg bg-zinc-100 px-3 py-2 font-mono text-xs text-zinc-800">
                  /login {p.email || p.phone_number || "<phone or email>"} &lt;your password&gt;
                </p>
                <a href={p.telegram_bot_url} target="_blank" rel="noreferrer" className="font-medium text-brand-700 hover:underline">
                  {t("Open {handle}", { handle: telegramHandle(p.telegram_bot_url) })} →
                </a>
              </div>
            )}
          </>
        )}
      </Section>

      {p?.referral_code && <ReferralCard code={p.referral_code} />}

      {(p?.telegram_channel_url || p?.private_group_url) && (
        <Section title={t("Community")}>
          {p.telegram_channel_url && (
            <Row
              href={p.telegram_channel_url}
              icon={Megaphone}
              label={t("Our Telegram channel")}
              hint={t("Updates, exam tips and announcements")}
            />
          )}
          {p.private_group_url && (
            <Row
              href={p.private_group_url}
              icon={Trophy}
              label={t("Daily mass practice group")}
              hint={t("Subscribers only. Link the bot first so your join request is approved.")}
            />
          )}
        </Section>
      )}

      <Section title={t("Settings")}>
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <span className="flex items-center gap-3 text-sm font-medium text-zinc-900">
            <Globe className="size-4.5 text-zinc-500" aria-hidden /> {t("Language")}
          </span>
          <LanguageSwitch />
        </div>
        <SchoolPicker />
        <BotTipsSwitch />
      </Section>

      <InstallAppCard />

      <Button variant="secondary" onClick={logout}>
        <LogOut className="size-4" aria-hidden /> {t("Log out")}
      </Button>

      <Link to="/delete-account" className="text-center text-sm font-medium text-red-600 hover:text-red-700">
        {t("Delete account")}
      </Link>

      <p className="flex items-center justify-center gap-1.5 pb-2 text-xs text-zinc-400">
        {t("Ethiopian Student Helper")} · {t("Made with")} <Heart className="size-3 fill-current text-rose-400" aria-hidden />{" "}
        {t("by Dawit and Betsinat")}
      </p>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="px-1 text-xs font-semibold tracking-wide text-zinc-500 uppercase">{title}</h2>
      <Card className="flex flex-col divide-y divide-zinc-100 overflow-hidden">{children}</Card>
    </section>
  )
}

const VALUE_TONES = { good: "text-emerald-700", action: "text-brand-700" } as const

function Row({
  icon: Icon,
  label,
  hint,
  value,
  valueTone,
  to,
  href,
  onClick,
}: {
  icon: typeof Wallet
  label: string
  hint?: string
  value?: string
  valueTone?: keyof typeof VALUE_TONES
  to?: string
  href?: string
  onClick?: () => void
}) {
  const body = (
    <>
      <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-brand-50">
        <Icon className="size-4.5 text-brand-700" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-medium text-zinc-900">{label}</span>
        {hint && <span className="block text-xs text-zinc-500">{hint}</span>}
      </span>
      {value && <span className={`shrink-0 text-sm ${valueTone ? VALUE_TONES[valueTone] : "text-zinc-500"}`}>{value}</span>}
      {(to || href || onClick) && <ChevronRight className="size-4 shrink-0 text-zinc-300" aria-hidden />}
    </>
  )
  const cls = "flex w-full items-center gap-3 px-4 py-3 text-left transition-colors"
  if (to) return <Link to={to} className={`${cls} hover:bg-zinc-50`}>{body}</Link>
  if (href)
    return (
      <a href={href} target="_blank" rel="noreferrer" className={`${cls} hover:bg-zinc-50`}>
        {body}
      </a>
    )
  if (onClick)
    return (
      <button onClick={onClick} className={`${cls} hover:bg-zinc-50`}>
        {body}
      </button>
    )
  return <div className={cls}>{body}</div>
}
