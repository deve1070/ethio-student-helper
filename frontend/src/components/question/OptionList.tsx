import clsx from "clsx"
import { Check, X } from "lucide-react"
import { RichText } from "../ui/RichText"

const LETTERS = ["A", "B", "C", "D"]

export function OptionList({
  options,
  selected,
  correctIndex,
  onSelect,
  disabled,
  revealAnswer = true,
  lockOnAnswer = true,
}: {
  options: string[]
  /** index the student picked, once answered; null before answering */
  selected: number | null
  /** only known once answered; undefined while still choosing */
  correctIndex?: number
  onSelect: (index: number) => void
  disabled?: boolean
  /** false for an exam-mode question: a choice is recorded but never shown as right/wrong until the
      exam is submitted - the chosen option gets a neutral "selected" style, not red/green. */
  revealAnswer?: boolean
  /** false for an exam-mode question: the student can change their answer any number of times before
      submitting, so picking one must never disable the others (immediate-feedback practice mode is the
      one case where an answer, once graded, is locked in for good). */
  lockOnAnswer?: boolean
}) {
  const answered = selected !== null
  const reveal = revealAnswer && answered

  return (
    <div className="flex flex-col gap-2.5" role="radiogroup">
      {options.map((option, i) => {
        const isChosen = selected === i
        const isCorrect = reveal && correctIndex === i
        const isWrongChoice = reveal && isChosen && correctIndex !== i
        const isNeutralSelected = !revealAnswer && isChosen

        return (
          <button
            key={i}
            type="button"
            role="radio"
            aria-checked={isChosen}
            disabled={disabled || (lockOnAnswer && answered)}
            onClick={() => onSelect(i)}
            className={clsx(
              "flex w-full items-center gap-3 rounded-xl border px-4 py-3 text-left text-[15px] leading-snug transition-colors",
              "disabled:cursor-default",
              !answered && "border-zinc-200 bg-white hover:border-brand-300 hover:bg-brand-50/40",
              isCorrect && "border-emerald-500 bg-emerald-50",
              isWrongChoice && "border-red-400 bg-red-50",
              isNeutralSelected && "border-brand-500 bg-brand-50",
              answered && !isCorrect && !isWrongChoice && !isNeutralSelected && "border-zinc-200 bg-white opacity-60",
            )}
          >
            <span
              className={clsx(
                "flex size-7 shrink-0 items-center justify-center rounded-full border text-sm font-semibold",
                !answered && "border-zinc-300 text-zinc-600",
                isCorrect && "border-emerald-600 bg-emerald-600 text-white",
                isWrongChoice && "border-red-500 bg-red-500 text-white",
                isNeutralSelected && "border-brand-600 bg-brand-600 text-white",
                answered && !isCorrect && !isWrongChoice && !isNeutralSelected && "border-zinc-300 text-zinc-400",
              )}
            >
              {isCorrect ? <Check className="size-4" /> : isWrongChoice ? <X className="size-4" /> : LETTERS[i]}
            </span>
            <span className="flex-1 text-zinc-900">
              <RichText text={option} />
            </span>
          </button>
        )
      })}
    </div>
  )
}
