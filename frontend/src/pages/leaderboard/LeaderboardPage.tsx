import { useEffect, useState } from "react"
import { CalendarDays, Flame, Trophy } from "lucide-react"
import { Card } from "../../components/ui/Card"
import { EmptyState, ErrorBanner, FullPageSpinner, SectionHeading } from "../../components/ui/Primitives"
import {
  type ChallengeLeaderboard,
  type ConsistencyLeaderboardEntry,
  type WeeklyLeaderboardEntry,
  errorMessage,
  massChallenge,
} from "../../lib/api"

const MEDALS = ["🥇", "🥈", "🥉"]
const STREAM_NAMES: Record<string, string> = {
  natural_science: "Natural stream",
  social_science: "Social stream",
}

function RankRow({
  rank,
  name,
  primary,
  secondary,
}: {
  rank: number
  name: string
  primary: string
  secondary: string
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-zinc-100 px-4 py-3 last:border-0">
      <div className="flex items-center gap-3">
        <span className="w-6 text-center text-sm font-medium text-zinc-400">
          {MEDALS[rank] ?? rank + 1}
        </span>
        <p className="font-medium text-zinc-900">{name}</p>
      </div>
      <div className="text-right">
        <p className="font-semibold text-zinc-900">{primary}</p>
        <p className="text-xs text-zinc-500">{secondary}</p>
      </div>
    </div>
  )
}

type DayBoard = ChallengeLeaderboard & { stream: string }

export function LeaderboardPage() {
  const [latest, setLatest] = useState<DayBoard[] | null>(null)
  const [weekly, setWeekly] = useState<WeeklyLeaderboardEntry[] | null>(null)
  const [consistency, setConsistency] = useState<ConsistencyLeaderboardEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    massChallenge
      .latest()
      .then((day) =>
        Promise.all(
          (day?.challenges ?? []).map((c) =>
            massChallenge.leaderboard(c.id).then((board) => ({ ...board, stream: c.stream })),
          ),
        ),
      )
      .then(setLatest)
      .catch((e) => setError(errorMessage(e)))

    massChallenge
      .weeklyLeaderboard()
      .then((r) => setWeekly(r.entries))
      .catch((e) => setError(errorMessage(e)))

    massChallenge
      .consistencyLeaderboard()
      .then((r) => setConsistency(r.entries))
      .catch((e) => setError(errorMessage(e)))
  }, [])

  if (error) return <ErrorBanner message={error} />
  if (latest === null || weekly === null || consistency === null) return <FullPageSpinner />

  const played = latest.filter((board) => board.entries.length > 0)

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-2.5">
        <SectionHeading>Latest mass practice</SectionHeading>
        {played.length === 0 ? (
          <EmptyState
            icon={Trophy}
            title="No results yet"
            description="Join tonight's practice in the Telegram group to show up here."
          />
        ) : (
          played.map((board) => (
            <div key={board.challenge_id} className="flex flex-col gap-2">
              <p className="text-sm text-zinc-500">
                {STREAM_NAMES[board.stream] ? `${STREAM_NAMES[board.stream]} · ` : ""}
                <span className="capitalize">{board.subject.replace(/_/g, " ")}</span> — {board.unit}
              </p>
              <Card className="overflow-hidden">
                {board.entries.map((entry, i) => (
                  <RankRow
                    key={entry.user_id}
                    rank={i}
                    name={entry.display_name}
                    primary={`${entry.correct}/${board.total_questions}`}
                    secondary={`${entry.answered} answered`}
                  />
                ))}
              </Card>
            </div>
          ))
        )}
      </section>

      <section className="flex flex-col gap-2.5">
        <SectionHeading>This week</SectionHeading>
        {weekly.length === 0 ? (
          <EmptyState
            icon={CalendarDays}
            title="No answers this week yet"
            description="Correct answers in the last 7 days of mass practice are counted here."
          />
        ) : (
          <Card className="overflow-hidden">
            {weekly.map((entry, i) => (
              <RankRow
                key={entry.user_id}
                rank={i}
                name={entry.display_name}
                primary={`${entry.correct} correct`}
                secondary={`${entry.answered} answered · ${entry.days_participated} days`}
              />
            ))}
          </Card>
        )}
      </section>

      <section className="flex flex-col gap-2.5">
        <SectionHeading>Most consistent</SectionHeading>
        {consistency.length === 0 ? (
          <EmptyState
            icon={Flame}
            title="Nobody has taken part yet"
            description="Each day you answer the mass practice, live or by catching up, counts here."
          />
        ) : (
          <Card className="overflow-hidden">
            {consistency.map((entry, i) => (
              <RankRow
                key={entry.user_id}
                rank={i}
                name={entry.display_name}
                primary={`${entry.days_participated} days`}
                secondary={`${entry.questions_answered} questions`}
              />
            ))}
          </Card>
        )}
      </section>
    </div>
  )
}
