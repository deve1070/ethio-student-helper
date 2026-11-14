import { useEffect, useState } from "react"
import { Flame, Trophy } from "lucide-react"
import { Card } from "../../components/ui/Card"
import { EmptyState, ErrorBanner, FullPageSpinner, SectionHeading } from "../../components/ui/Primitives"
import {
  type ChallengeLeaderboard,
  type ConsistencyLeaderboardEntry,
  errorMessage,
  massChallenge,
} from "../../lib/api"

const MEDALS = ["🥇", "🥈", "🥉"]

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

export function LeaderboardPage() {
  const [today, setToday] = useState<ChallengeLeaderboard | null | "none">(null)
  const [consistency, setConsistency] = useState<ConsistencyLeaderboardEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    massChallenge
      .latest()
      .then((latest) => (latest ? massChallenge.leaderboard(latest.id) : null))
      .then((board) => setToday(board ?? "none"))
      .catch((e) => setError(errorMessage(e)))

    massChallenge
      .consistencyLeaderboard()
      .then((r) => setConsistency(r.entries))
      .catch((e) => setError(errorMessage(e)))
  }, [])

  if (error) return <ErrorBanner message={error} />
  if (today === null || consistency === null) return <FullPageSpinner />

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-2.5">
        <SectionHeading>Today's mass practice</SectionHeading>
        {today === "none" || today.entries.length === 0 ? (
          <EmptyState
            icon={Trophy}
            title="No results yet"
            description="Join tonight's practice in the Telegram group to show up here."
          />
        ) : (
          <>
            <p className="text-sm text-zinc-500">
              {today.subject.replace(/_/g, " ")} - {today.unit}
            </p>
            <Card className="overflow-hidden">
              {today.entries.map((entry, i) => (
                <RankRow
                  key={entry.user_id}
                  rank={i}
                  name={entry.display_name}
                  primary={`${entry.correct}/${today.total_questions}`}
                  secondary={`${entry.answered} answered`}
                />
              ))}
            </Card>
          </>
        )}
      </section>

      <section className="flex flex-col gap-2.5">
        <SectionHeading>Most consistent</SectionHeading>
        {consistency.length === 0 ? (
          <EmptyState
            icon={Flame}
            title="Nobody has a streak yet"
            description="Days you join the mass practice count toward this."
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
