export function AccuracyRing({ value, size = 112, stroke = 10 }: { value: number | null; size?: number; stroke?: number }) {
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const pct = value ?? 0
  const offset = circumference * (1 - pct / 100)

  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} strokeWidth={stroke} className="stroke-zinc-100" fill="none" />
        {value !== null && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={radius}
            strokeWidth={stroke}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            strokeLinecap="round"
            className="stroke-brand-600 transition-[stroke-dashoffset] duration-700"
            fill="none"
          />
        )}
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-xl font-semibold text-zinc-900">{value !== null ? `${Math.round(value)}%` : "-"}</span>
      </div>
    </div>
  )
}
