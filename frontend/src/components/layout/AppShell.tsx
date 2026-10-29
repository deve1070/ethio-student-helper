import { NavLink, Outlet, useLocation } from "react-router-dom"
import clsx from "clsx"
import { BarChart3, BookOpenCheck, GraduationCap, Home, User, Wallet } from "lucide-react"

const NAV_ITEMS = [
  { to: "/", label: "Home", icon: Home, end: true },
  { to: "/practice", label: "Practice", icon: BookOpenCheck },
  { to: "/esslce", label: "ESSLCE", icon: GraduationCap },
  { to: "/progress", label: "Progress", icon: BarChart3 },
  { to: "/credits", label: "Credits", icon: Wallet },
  { to: "/profile", label: "Profile", icon: User },
]

const TITLES: Record<string, string> = {
  "/": "Ethiopian Student Helper",
  "/practice": "Practice",
  "/esslce": "ESSLCE Exam Bank",
  "/progress": "Progress",
  "/mistakes": "Mistake Review",
  "/notes": "Study Notes",
  "/credits": "Credits",
  "/profile": "Profile",
}

function currentTitle(pathname: string): string {
  if (TITLES[pathname]) return TITLES[pathname]
  const root = "/" + pathname.split("/")[1]
  return TITLES[root] ?? "Ethiopian Student Helper"
}

export function AppShell() {
  const location = useLocation()

  return (
    <div className="mx-auto flex min-h-dvh max-w-xl flex-col bg-[#f7f8f7]">
      <header
        className="sticky top-0 z-10 flex h-14 shrink-0 items-center border-b border-zinc-200/70 bg-white/90 px-4 backdrop-blur"
        style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}
      >
        <h1 className="text-[17px] font-semibold text-zinc-900">{currentTitle(location.pathname)}</h1>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-5">
        <Outlet />
      </main>

      <nav
        className="sticky bottom-0 z-10 flex shrink-0 justify-around border-t border-zinc-200/70 bg-white/95 backdrop-blur"
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}
      >
        {NAV_ITEMS.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              clsx(
                "flex flex-1 flex-col items-center gap-1 py-2.5 text-xs font-medium transition-colors",
                isActive ? "text-brand-700" : "text-zinc-400 hover:text-zinc-600",
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon className="size-5" strokeWidth={isActive ? 2.25 : 2} aria-hidden />
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
