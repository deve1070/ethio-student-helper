import type { HTMLAttributes, InputHTMLAttributes, LabelHTMLAttributes } from "react"
import clsx from "clsx"
import { Loader2, type LucideIcon } from "lucide-react"

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("size-5 animate-spin text-brand-600", className)} aria-label="Loading" />
}

export function FullPageSpinner() {
  return (
    <div className="flex h-full min-h-[50vh] items-center justify-center">
      <Spinner />
    </div>
  )
}

export function Field({
  label,
  htmlFor,
  error,
  children,
}: {
  label: string
  htmlFor: string
  error?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium text-zinc-700">
        {label}
      </label>
      {children}
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  )
}

export function TextInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={clsx(
        "h-11 w-full rounded-lg border border-zinc-300 bg-white px-3 text-base text-zinc-900",
        "placeholder:text-zinc-400 focus:border-brand-500 focus:outline-2 focus:outline-brand-500/30",
        className,
      )}
      {...rest}
    />
  )
}

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: React.ReactNode
  tone?: "neutral" | "brand" | "success" | "danger" | "warning"
  className?: string
}) {
  const tones: Record<string, string> = {
    neutral: "bg-zinc-100 text-zinc-700",
    brand: "bg-brand-100 text-brand-800",
    success: "bg-emerald-100 text-emerald-800",
    danger: "bg-red-100 text-red-700",
    warning: "bg-amber-100 text-amber-800",
  }
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", tones[tone], className)}>
      {children}
    </span>
  )
}

export function ProgressBar({ value, className }: { value: number; className?: string }) {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div className={clsx("h-2 w-full overflow-hidden rounded-full bg-zinc-100", className)}>
      <div
        className="h-full rounded-full bg-brand-600 transition-[width] duration-500"
        style={{ width: `${pct}%` }}
      />
    </div>
  )
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
}: {
  icon: LucideIcon
  title: string
  description?: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl border border-dashed border-zinc-300 px-6 py-12 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-zinc-100">
        <Icon className="size-6 text-zinc-500" aria-hidden />
      </div>
      <div>
        <p className="font-medium text-zinc-900">{title}</p>
        {description && <p className="mt-1 text-sm text-zinc-500">{description}</p>}
      </div>
      {action}
    </div>
  )
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
      {message}
    </div>
  )
}

export function SectionHeading({ children, ...rest }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2 className="text-lg font-semibold text-zinc-900" {...rest}>
      {children}
    </h2>
  )
}

export function VisuallyHidden({ children, ...rest }: LabelHTMLAttributes<HTMLSpanElement>) {
  return (
    <span className="sr-only" {...rest}>
      {children}
    </span>
  )
}
