import { Link } from "react-router-dom"
import { Atom, Calendar, Clock, Landmark, LogOut, Pencil, User } from "lucide-react"
import { Button } from "../components/ui/Button"
import { Card } from "../components/ui/Card"
import { useAuth } from "../lib/auth"

function daysUntil(dateStr: string): number {
  const ms = new Date(dateStr + "T00:00:00").getTime() - new Date().setHours(0, 0, 0, 0)
  return Math.round(ms / 86_400_000)
}

const GOAL_LABELS: Record<number, string> = { 30: "30 minutes", 60: "1 hour", 120: "2 hours", 180: "3+ hours" }

export function ProfilePage() {
  const { logout, gradeLevel, fullProfile } = useAuth()

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

      <Button variant="secondary" onClick={logout}>
        <LogOut className="size-4" aria-hidden /> Log out
      </Button>
    </div>
  )
}
