import { useState } from "react"
import type { TrendPoint } from "../../lib/api"

const WIDTH = 320
const HEIGHT = 110
const PAD_X = 10
const PAD_TOP = 14
const PAD_BOTTOM = 22

function weekdayLabel(dateStr: string): string {
  return new Date(dateStr + "T00:00:00").toLocaleDateString(undefined, { weekday: "short" })
}

export function TrendChart({ points }: { points: TrendPoint[] }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null)

  if (points.length === 0) return null

  const plotWidth = WIDTH - PAD_X * 2
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM
  const stepX = points.length > 1 ? plotWidth / (points.length - 1) : 0
  const xAt = (i: number) => PAD_X + i * stepX
  const yAt = (accuracy: number) => PAD_TOP + (1 - accuracy) * plotHeight

  // Line is drawn as separate segments, broken wherever a day has no attempts (accuracy === null) -
  // a quiet day is a gap, never interpolated as a false 0%.
  const segments: { d: string }[] = []
  let current: string[] = []
  points.forEach((p, i) => {
    if (p.accuracy === null) {
      if (current.length > 1) segments.push({ d: current.join(" ") })
      current = []
      return
    }
    current.push(`${i === 0 || current.length === 0 ? "M" : "L"} ${xAt(i)} ${yAt(p.accuracy)}`)
  })
  if (current.length > 1) segments.push({ d: current.join(" ") })

  const lastWithData = [...points].reverse().find((p) => p.accuracy !== null)
  const lastIndex = lastWithData ? points.indexOf(lastWithData) : -1

  function onMove(e: React.PointerEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect()
    const relX = ((e.clientX - rect.left) / rect.width) * WIDTH
    const i = Math.round((relX - PAD_X) / (stepX || 1))
    setHoverIndex(Math.max(0, Math.min(points.length - 1, i)))
  }

  const hovered = hoverIndex !== null ? points[hoverIndex] : null

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="w-full touch-none"
        onPointerMove={onMove}
        onPointerLeave={() => setHoverIndex(null)}
        role="img"
        aria-label="Accuracy over the last 7 days"
      >
        <line
          x1={PAD_X}
          y1={PAD_TOP + plotHeight}
          x2={WIDTH - PAD_X}
          y2={PAD_TOP + plotHeight}
          className="stroke-zinc-200"
          strokeWidth={1}
        />

        {segments.map((seg, i) => (
          <path key={i} d={seg.d} fill="none" className="stroke-brand-600" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        ))}

        {lastIndex >= 0 && lastWithData && (
          <circle cx={xAt(lastIndex)} cy={yAt(lastWithData.accuracy!)} r={4} className="fill-brand-600 stroke-white" strokeWidth={2} />
        )}

        {hoverIndex !== null && (
          <line
            x1={xAt(hoverIndex)}
            y1={PAD_TOP}
            x2={xAt(hoverIndex)}
            y2={PAD_TOP + plotHeight}
            className="stroke-zinc-300"
            strokeWidth={1}
          />
        )}

        {points.map((p, i) => (
          <text key={p.date} x={xAt(i)} y={HEIGHT - 4} textAnchor="middle" className="fill-zinc-400 text-[9px]">
            {weekdayLabel(p.date)}
          </text>
        ))}
      </svg>

      {hovered && (
        <div
          className="pointer-events-none absolute top-0 -translate-x-1/2 rounded-lg bg-zinc-900 px-2 py-1 text-xs text-white shadow-md"
          style={{ left: `${(xAt(hoverIndex!) / WIDTH) * 100}%` }}
        >
          <span className="font-semibold">
            {hovered.accuracy !== null ? `${Math.round(hovered.accuracy * 100)}%` : "No activity"}
          </span>
        </div>
      )}
    </div>
  )
}
