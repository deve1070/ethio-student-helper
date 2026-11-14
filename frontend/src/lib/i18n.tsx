import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react"

// Interface language. Each English string is its own key: a string missing from AM below shows in
// English, so a screen that isn't translated yet still works. Placeholders are written {name} and
// filled from t()'s second argument. Exam content (questions, notes, explanations) stays in English,
// the language the ESSLCE itself is set in.
export type Lang = "en" | "am"

const STORAGE_KEY = "esh_lang"

const AM: Record<string, string> = {
  // navigation and page titles
  Home: "መነሻ",
  Practice: "ልምምድ",
  Ranks: "ደረጃ",
  Progress: "እድገት",
  Subscription: "ምዝገባ",
  Profile: "መገለጫ",
  "Ethiopian Student Helper": "የኢትዮጵያ ተማሪዎች ረዳት",
  "ESSLCE Exam Bank": "የESSLCE ፈተና ባንክ",
  Leaderboard: "የደረጃ ሰንጠረዥ",
  "Mistake Review": "የስህተት ክለሳ",
  "Study Notes": "የጥናት ማስታወሻዎች",
  "You're offline. Notes and plans you've opened are still here; practice needs a connection.":
    "ከመስመር ውጭ ነዎት። የከፈቷቸው ማስታወሻዎችና እቅዶች አሉ፤ ልምምድ ግን ኢንተርኔት ይፈልጋል።",

  // login and sign-up
  "Welcome back": "እንኳን በደህና ተመለሱ",
  "Log in to continue studying.": "ጥናትዎን ለመቀጠል ይግቡ።",
  "Phone or email": "ስልክ ወይም ኢሜይል",
  Password: "የይለፍ ቃል",
  "Log in": "ግባ",
  "Forgot password?": "የይለፍ ቃልዎን ረሱ?",
  "New here?": "አዲስ ነዎት?",
  "Create an account": "መለያ ይፍጠሩ",
  "Create your account": "መለያዎን ይፍጠሩ",
  "It only takes a minute.": "አንድ ደቂቃ ብቻ ይወስዳል።",
  "Full name": "ሙሉ ስም",
  Grade: "ክፍል",
  "Grade {n}": "{n}ኛ ክፍል",
  "Referral code (optional)": "የጋባዥ ኮድ (አማራጭ)",
  "Create account": "መለያ ፍጠር",
  "Already have an account?": "መለያ አለዎት?",

  // dashboard
  "{n} days to your ESSLCE": "ለESSLCE ፈተናዎ {n} ቀናት ቀርተዋል",
  "Your ESSLCE date has passed": "የESSLCE ፈተና ቀንዎ አልፏል",
  "Due for review today": "ዛሬ የሚከለሱ ጥያቄዎች",
  "Questions you got wrong come back after 1, 3 and 7 days until you get them right.":
    "የተሳሳቷቸው ጥያቄዎች በትክክል እስኪመልሷቸው ድረስ ከ1፣ 3 እና 7 ቀናት በኋላ ይመለሳሉ።",
  "Today's study plan": "የዛሬ የጥናት እቅድ",
  "View full week": "ሙሉ ሳምንቱን ይመልከቱ",
  "Set up your profile to get a personalized plan here.": "እዚህ የግል እቅድ ለማግኘት መገለጫዎን ያዘጋጁ።",
  "There isn't quite enough time to cover everything before your exam - this plan prioritizes what's tested most.":
    "ከፈተናዎ በፊት ሁሉንም ለመሸፈን በቂ ጊዜ የለም — ይህ እቅድ በብዛት የሚፈተኑትን ያስቀድማል።",
  "What would you like to study today?": "ዛሬ ምን ማጥናት ይፈልጋሉ?",
  "Ask a question": "ጥያቄ ይጠይቁ",
  "Get a grounded explanation from your Grade {n} textbooks.":
    "ከ{n}ኛ ክፍል መማሪያ መጽሐፍትዎ የተደገፈ ማብራሪያ ያግኙ።",
  "Multiple-choice questions from your textbooks, by subject and unit.":
    "ከመማሪያ መጽሐፍትዎ የተወሰዱ ምርጫ ጥያቄዎች፣ በትምህርት ዓይነትና በምዕራፍ።",
  "ESSLCE exam bank": "የESSLCE ፈተና ባንክ",
  "Grade 12 national exam past papers - practice, mock exams, and diagnostics.":
    "ያለፉ የ12ኛ ክፍል ብሔራዊ ፈተናዎች — ልምምድ፣ የሙከራ ፈተና እና የደረጃ መለኪያ።",
  "Study notes": "የጥናት ማስታወሻዎች",
  "Topic summaries, key formulas, and worked examples from your textbooks.":
    "ከመማሪያ መጽሐፍትዎ የርዕስ ማጠቃለያዎች፣ ዋና ቀመሮች እና የተሰሩ ምሳሌዎች።",
  "Exam readiness": "የፈተና ዝግጁነት",
  "Answer {n} more to see a projection": "ግምቱን ለማየት {n} ተጨማሪ ይመልሱ",
  "Based on {p}% of the exam - practise more units to firm it up":
    "በፈተናው {p}% ላይ የተመሰረተ — ለማጠናከር ተጨማሪ ምዕራፎችን ይለማመዱ",

  // profile
  Language: "ቋንቋ",
  "Log out": "ውጣ",
}

const DICTIONARIES: Record<Lang, Record<string, string>> = { en: {}, am: AM }

function initialLang(): Lang {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === "en" || saved === "am") return saved
  } catch {
    // storage can be unavailable (private browsing); fall through to the browser's language
  }
  return navigator.language?.toLowerCase().startsWith("am") ? "am" : "en"
}

type Translate = (text: string, vars?: Record<string, string | number>) => string
const I18nContext = createContext<{ lang: Lang; setLang: (lang: Lang) => void; t: Translate } | null>(null)

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(initialLang)

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // best-effort; the choice still applies for this visit
    }
  }, [])

  const t = useCallback<Translate>(
    (text, vars) => {
      let out = DICTIONARIES[lang][text] ?? text
      for (const [k, v] of Object.entries(vars ?? {})) out = out.split(`{${k}}`).join(String(v))
      return out
    },
    [lang],
  )

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t])
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const ctx = useContext(I18nContext)
  if (!ctx) throw new Error("useI18n must be used inside I18nProvider")
  return ctx
}

export function LanguageSwitch({ className = "" }: { className?: string }) {
  const { lang, setLang } = useI18n()
  return (
    <div className={`inline-flex rounded-lg border border-zinc-200 bg-white p-0.5 text-sm ${className}`}>
      {(["en", "am"] as const).map((l) => (
        <button
          key={l}
          type="button"
          onClick={() => setLang(l)}
          className={`rounded-md px-3 py-1 font-medium ${lang === l ? "bg-brand-600 text-white" : "text-zinc-600 hover:text-zinc-900"}`}
        >
          {l === "en" ? "English" : "አማርኛ"}
        </button>
      ))}
    </div>
  )
}
