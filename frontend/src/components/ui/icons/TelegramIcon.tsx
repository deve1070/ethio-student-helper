// lucide-react has no Telegram glyph, and no other brand icon exists in this codebase to borrow
// from - this is the one custom-SVG icon in the app, kept as small/dependency-free as every
// lucide icon it sits next to (fill="currentColor" so it inherits text color the same way).
export function TelegramIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 240 240" className={className} fill="currentColor" aria-hidden>
      <path d="M100 144l-4 56c6 0 9-3 12-6l29-28 60 44c11 6 19 3 22-10l40-188c4-16-6-23-17-19L12 106c-16 6-16 15-3 19l55 17 127-80c6-4 11-2 7 2z" />
    </svg>
  )
}
