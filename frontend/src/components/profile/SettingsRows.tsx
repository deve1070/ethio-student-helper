import { useEffect, useState } from "react"
import { School as SchoolIcon } from "lucide-react"
import { auth, growth, schools, type School } from "../../lib/api"
import { useAuth } from "../../lib/auth"
import { useI18n } from "../../lib/i18n"

// The student's school, for the weekly top-schools ranking in the channel. Schools are added by an
// admin, so the list is a choice, not free text. Hidden until at least one school exists.
export function SchoolPicker() {
  const { fullProfile, refreshProfile } = useAuth()
  const { t } = useI18n()
  const [list, setList] = useState<School[] | null>(null)
  const [saving, setSaving] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    schools.list().then(setList).catch(() => setList([]))
  }, [])

  if (!list || list.length === 0) return null

  async function choose(value: string) {
    setSaving(true)
    setFailed(false)
    try {
      await auth.updateMe({ school_id: value ? Number(value) : null })
      await refreshProfile()
    } catch {
      setFailed(true)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-1.5 px-4 py-3">
      <label htmlFor="school" className="flex items-center gap-3 text-sm font-medium text-zinc-900">
        <SchoolIcon className="size-4.5 text-zinc-500" aria-hidden /> {t("Your school")}
        {fullProfile?.is_ambassador && (
          <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">{t("Ambassador")}</span>
        )}
      </label>
      <select
        id="school"
        value={fullProfile?.school_id ?? ""}
        disabled={saving}
        onChange={(e) => choose(e.target.value)}
        className="h-10 w-full rounded-lg border border-zinc-300 bg-white px-3 text-sm text-zinc-900 focus:border-brand-500 focus:outline-2 focus:outline-brand-500/30"
      >
        <option value="">{t("Not chosen")}</option>
        {list.map((s) => (
          <option key={s.id} value={s.id}>
            {s.name}
          </option>
        ))}
      </select>
      <p className="text-xs text-zinc-500">
        {failed ? t("Couldn't save. Try again.") : t("Every question you answer counts for your school in the weekly ranking.")}
      </p>
    </div>
  )
}

export function BotTipsSwitch() {
  const { fullProfile, refreshProfile } = useAuth()
  const { t } = useI18n()
  const [saving, setSaving] = useState(false)
  if (!fullProfile?.telegram_linked) return null
  const on = !fullProfile.nudges_off

  async function toggle() {
    setSaving(true)
    try {
      await growth.setTips(on)
      await refreshProfile()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-3">
      <span className="min-w-0">
        <span className="block text-sm font-medium text-zinc-900">{t("Tips from the bot")}</span>
        <span className="block text-xs text-zinc-500">{t("Exam countdown and reminders when you've been away, at most one a day")}</span>
      </span>
      <button
        role="switch"
        aria-checked={on}
        disabled={saving}
        onClick={toggle}
        className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${on ? "bg-brand-600" : "bg-zinc-300"}`}
      >
        <span className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
        <span className="sr-only">{t("Tips from the bot")}</span>
      </button>
    </div>
  )
}
