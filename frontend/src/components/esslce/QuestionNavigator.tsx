import clsx from "clsx"
import { Flag } from "lucide-react"

export function QuestionNavigator({
  count,
  currentIndex,
  answered,
  flagged,
  onJump,
}: {
  count: number
  currentIndex: number
  answered: Set<number>
  flagged: Set<number>
  onJump: (index: number) => void
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-4 text-xs text-zinc-500">
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full bg-brand-600" /> Answered
        </span>
        <span className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full border-2 border-brand-600" /> Current
        </span>
        <span className="flex items-center gap-1.5">
          <Flag className="size-3 text-amber-500" aria-hidden /> Marked
        </span>
      </div>
      <div className="grid grid-cols-8 gap-2">
        {Array.from({ length: count }, (_, i) => {
          const isCurrent = i === currentIndex
          const isAnswered = answered.has(i)
          const isFlagged = flagged.has(i)
          return (
            <button
              key={i}
              onClick={() => onJump(i)}
              className={clsx(
                "relative flex size-9 items-center justify-center rounded-lg text-sm font-medium transition-colors",
                isCurrent && "border-2 border-brand-600 text-brand-700",
                !isCurrent && isAnswered && "bg-brand-600 text-white",
                !isCurrent && !isAnswered && "bg-zinc-100 text-zinc-500 hover:bg-zinc-200",
              )}
            >
              {i + 1}
              {isFlagged && (
                <Flag className="absolute -right-1 -top-1 size-3.5 fill-amber-400 text-amber-500" aria-hidden />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
