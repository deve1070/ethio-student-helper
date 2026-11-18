import { Suspense, useEffect, useState } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import clsx from "clsx"
import { FullPageSpinner } from "../ui/Primitives"
import { BookOpenCheck, GraduationCap, Home, Trophy, User } from "lucide-react"
import { useI18n } from "../../lib/i18n"
import { useOnline } from "../../lib/useOnline"

// Five tabs fit a phone with readable labels. Progress is reached from Home, Subscription from Profile.
const NAV_ITEMS = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/practice", label: "Practice", icon: BookOpenCheck },
  { to: "/esslce", label: "ESSLCE", icon: GraduationCap },
  { to: "/leaderboard", label: "Ranks", icon: Trophy },
  { to: "/profile", label: "Profile", icon: User },
]

const TITLES: Record<string, string> = {
  "/": "Ethiopian Student Helper",
  "/practice": "Practice",
  "/esslce": "ESSLCE Exam Bank",
  "/leaderboard": "Leaderboard",
  "/progress": "Progress",
  "/mistakes": "Mistake Review",
  "/notes": "Study Notes",
  "/subscription": "Subscription",
  "/subscribe": "Subscription",
  "/profile": "Profile",
  "/delete-account": "Delete account",
  "/explain": "Ask a question",
  "/study-plan": "Study plan",
}

function currentTitle(pathname: string): string {
  if (TITLES[pathname]) return TITLES[pathname]
  const root = "/" + pathname.split("/")[1]
  return TITLES[root] ?? "Ethiopian Student Helper"
}

// True while the on-screen keyboard is up. The visual viewport shrinks by the keyboard's height while
// the layout viewport does not, so a gap of more than 150px between them means a keyboard, not a
// browser toolbar collapsing. Hiding the tab bar then keeps it from sitting on top of the keyboard.
function useKeyboardOpen(): boolean {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const update = () => setOpen(window.innerHeight - vv.height > 150)
    vv.addEventListener("resize", update)
    return () => vv.removeEventListener("resize", update)
  }, [])
  return open
}

export function AppShell() {
  const location = useLocation()
  const { t } = useI18n()
  const online = useOnline()
  const keyboardOpen = useKeyboardOpen()

  // a new page starts at its top, not wherever the previous one was scrolled to
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [location.pathname])

  return (
    <div className="mx-auto flex min-h-dvh max-w-xl flex-col bg-[#f7f8f7]">
      <header
        className="sticky top-0 z-20 shrink-0 border-b border-zinc-200/70 bg-white/90 backdrop-blur"
        style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}
      >
        <div className="flex h-14 items-center px-4">
          <h1 className="truncate text-[17px] font-semibold text-zinc-900">{t(currentTitle(location.pathname))}</h1>
        </div>
      </header>

      {!online && (
        <p className="bg-amber-50 px-4 py-2 text-center text-xs text-amber-800">
          {t("You're offline. Notes and plans you've opened are still here; practice needs a connection.")}
        </p>
      )}

      {/* The bottom padding reserves the tab bar's height plus the phone's home-indicator area, so the
          last item on a page is never hidden underneath the bar. */}
      <main className="flex-1 px-4 pt-5 pb-[calc(5.5rem+env(safe-area-inset-bottom,0px))]">
        <Suspense fallback={<FullPageSpinner />}>
          <Outlet />
        </Suspense>
      </main>

      <nav
        className={clsx(
          "fixed inset-x-0 bottom-0 z-20 mx-auto max-w-xl border-t border-zinc-200/70 bg-white/95 backdrop-blur transition-transform duration-200",
          keyboardOpen && "translate-y-full",
        )}
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      >
        <div className="flex h-16 items-stretch">
          {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                clsx(
                  "flex min-w-0 flex-1 flex-col items-center justify-center gap-1 text-[11px] font-medium transition-colors",
                  isActive ? "text-brand-700" : "text-zinc-400 hover:text-zinc-600",
                )
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    className={clsx(
                      "flex h-7 w-12 items-center justify-center rounded-full transition-colors",
                      isActive && "bg-brand-50",
                    )}
                  >
                    <Icon className="size-5" strokeWidth={isActive ? 2.25 : 2} aria-hidden />
                  </span>
                  <span className="max-w-full truncate px-1">{t(label)}</span>
                </>
              )}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  )
}
