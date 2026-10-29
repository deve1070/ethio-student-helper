import type { HTMLAttributes } from "react"
import clsx from "clsx"

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx("rounded-2xl bg-white border border-zinc-200/70 shadow-[var(--shadow-card)]", className)}
      {...rest}
    />
  )
}

export function CardButton({
  className,
  ...rest
}: HTMLAttributes<HTMLButtonElement> & { onClick?: () => void }) {
  return (
    <button
      className={clsx(
        "w-full text-left rounded-2xl bg-white border border-zinc-200/70 shadow-[var(--shadow-card)]",
        "transition-all hover:border-brand-300 hover:shadow-[var(--shadow-raised)] active:scale-[0.99]",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600",
        className,
      )}
      {...rest}
    />
  )
}
