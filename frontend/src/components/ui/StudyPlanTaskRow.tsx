import { Check } from "lucide-react"
import type { StudyPlanTask } from "../../lib/api"

export function StudyPlanTaskRow({
  task,
  onToggle,
  onOpen,
}: {
  task: StudyPlanTask
  onToggle: () => void
  onOpen: () => void
}) {
  return (
    <div
      className={
        "flex items-center gap-3 rounded-xl border px-3 py-2.5 transition-colors " +
        (task.done ? "border-zinc-100 bg-zinc-50" : "border-zinc-200 bg-white")
      }
    >
      <button
        onClick={onToggle}
        aria-label={task.done ? "Mark not done" : "Mark done"}
        className={
          "flex size-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors " +
          (task.done ? "border-brand-600 bg-brand-600 text-white" : "border-zinc-300")
        }
      >
        {task.done && <Check className="size-3.5" aria-hidden />}
      </button>
      <button onClick={onOpen} className="flex-1 text-left">
        <p className={"text-sm font-medium " + (task.done ? "text-zinc-400 line-through" : "text-zinc-900")}>
          {task.label}
        </p>
        {task.minutes !== null && <p className="text-xs text-zinc-500">{task.minutes} min</p>}
      </button>
    </div>
  )
}
