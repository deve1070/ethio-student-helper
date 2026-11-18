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

  // onboarding
  "Welcome to": "እንኳን ወደ",
  "Everything you need to pass the ESSLCE, in one place.": "ESSLCEን ለማለፍ የሚያስፈልግዎ ሁሉ፣ በአንድ ቦታ።",
  "Answers from your own textbooks": "ከራስዎ መማሪያ መጽሐፍት የተገኙ መልሶች",
  "Questions by subject and unit": "በትምህርት ዓይነትና በምዕራፍ የተደራጁ ጥያቄዎች",
  "Real past papers and mock exams": "እውነተኛ ያለፉ ፈተናዎችና የሙከራ ፈተናዎች",
  "Summaries and worked examples": "ማጠቃለያዎችና የተሰሩ ምሳሌዎች",
  "Study plan": "የጥናት እቅድ",
  "A daily plan to your exam date": "እስከ ፈተናዎ ቀን የዕለት እቅድ",
  "Daily group practice": "የዕለት የቡድን ልምምድ",
  "Compete with students on Telegram": "በቴሌግራም ከተማሪዎች ጋር ይወዳደሩ",
  "Get started": "እንጀምር",
  Back: "ተመለስ",
  Continue: "ቀጥል",
  "Skip for now": "ለአሁን ዝለል",
  "What's your stream?": "የትኛው ዘርፍ ነዎት?",
  "Grade {n} splits into two streams. Pick yours.": "{n}ኛ ክፍል በሁለት ዘርፎች ይከፈላል። የእርስዎን ይምረጡ።",
  "Natural Science": "የተፈጥሮ ሳይንስ",
  "Social Science": "የማኅበራዊ ሳይንስ",
  "Which subjects are you focusing on?": "በየትኞቹ ትምህርቶች ላይ ያተኩራሉ?",
  "You can change this later from your profile.": "ይህንን በኋላ ከመገለጫዎ መቀየር ይችላሉ።",
  "Continue with {n} subjects": "በ{n} ትምህርቶች ቀጥል",
  "When is your ESSLCE?": "ESSLCE ፈተናዎ መቼ ነው?",
  "We'll count down with you and plan your revision. Leave it blank if you're not sure yet.":
    "ቀናቱን አብረን እንቆጥራለን፤ የክለሳ እቅድም እናዘጋጃለን። እርግጠኛ ካልሆኑ ባዶ ይተዉት።",
  "Pick your exam date": "የፈተና ቀንዎን ይምረጡ",
  "days to go": "ቀናት ቀርተዋል",
  "How much time can you study each day?": "በቀን ምን ያህል ጊዜ ማጥናት ይችላሉ?",
  "Small daily sessions beat last-minute cramming.": "የዕለት ትንሽ ጥናት ከመጨረሻ ሰዓት ሩጫ ይበልጣል።",
  "30 minutes": "30 ደቂቃ",
  "1 hour": "1 ሰዓት",
  "2 hours": "2 ሰዓት",
  "3+ hours": "3+ ሰዓት",
  "Good for busy schedules": "ለተጣበበ ጊዜ ጥሩ",
  "Recommended for steady progress": "ለተከታታይ እድገት የሚመከር",
  "For serious preparation": "ለጠንካራ ዝግጅት",
  "For top performers": "ለከፍተኛ ውጤት ፈላጊዎች",
  minutes: "ደቂቃ",
  hour: "ሰዓት",
  hours: "ሰዓት",
  day: "ቀን",
  "{n} subjects": "{n} ትምህርቶች",
  "You're all set!": "ሁሉም ዝግጁ ነው!",
  "Your study plan is ready. Let's get started.": "የጥናት እቅድዎ ዝግጁ ነው። እንጀምር።",
  "Go to Dashboard": "ወደ መነሻ ገጽ",

  // account deletion
  "Delete account": "መለያ ሰርዝ",
  "Delete your account permanently": "መለያዎን በቋሚነት ይሰርዙ",
  "Your profile, progress, answers, study plans and Telegram link are deleted. This can't be undone.":
    "መገለጫዎ፣ እድገትዎ፣ መልሶችዎ፣ የጥናት እቅዶችዎና የቴሌግራም ግንኙነትዎ ይሰረዛሉ። ይህ ሊቀለበስ አይችልም።",
  "An active subscription ends with the account and is not refunded.": "ንቁ ምዝገባ ከመለያው ጋር ያበቃል፤ ገንዘቡም አይመለስም።",
  "You'll be removed from the daily practice group.": "ከዕለታዊ የልምምድ ቡድኑ ይወጣሉ።",
  "Records of payments you made are kept for our accounts, without your name or receipt photos.":
    "የከፈሏቸው ክፍያዎች መዝገብ ያለ ስምዎና ያለ ደረሰኝ ፎቶ ለሂሳብ ይቀመጣል።",
  "If you have referral earnings, withdraw them first; deleting is blocked until they're paid.":
    "የጋባዥ ገቢ ካለዎት መጀመሪያ ያውጡት፤ እስኪከፈል ድረስ መሰረዝ አይቻልም።",
  "Your password": "የይለፍ ቃልዎ",
  "Type {word} to confirm": "ለማረጋገጥ {word} ብለው ይጻፉ",
  "Delete my account": "መለያዬን ሰርዝ",
  Cancel: "ተወው",
  "Your account has been deleted.": "መለያዎ ተሰርዟል።",

  // profile
  Edit: "አስተካክል",
  Student: "ተማሪ",
  "Your account": "መለያዎ",
  Active: "ንቁ",
  "Free plan": "ነፃ",
  "Telegram bot": "የቴሌግራም ቦት",
  Connected: "ተገናኝቷል",
  Connect: "አገናኝ",
  "Link your account to practise from the bot and to reset your password through Telegram. Open the bot and send:":
    "ከቦቱ ለመለማመድና የይለፍ ቃልዎን በቴሌግራም ለመቀየር መለያዎን ያገናኙ። ቦቱን ከፍተው ይህንን ይላኩ፦",
  "Open {handle}": "{handle}ን ክፈት",
  Community: "ማኅበረሰብ",
  "Our Telegram channel": "የቴሌግራም ቻናላችን",
  "Updates, exam tips and announcements": "ዜናዎች፣ የፈተና ምክሮችና ማስታወቂያዎች",
  "Daily mass practice group": "የዕለት የጋራ ልምምድ ቡድን",
  "Subscribers only. Link the bot first so your join request is approved.":
    "ለተመዘገቡ ብቻ። የመቀላቀል ጥያቄዎ እንዲፀድቅ መጀመሪያ ቦቱን ያገናኙ።",
  Settings: "ቅንብሮች",
  "Made with": "በ",
  "by Dawit and Betsinat": "ዳዊት እና ብጽናት ያዘጋጁት",
  "{n} days to go": "{n} ቀናት ቀርተዋል",
  "Exam date has passed": "የፈተናው ቀን አልፏል",
  "From your Grade {n} textbooks": "ከ{n}ኛ ክፍል መጽሐፍትዎ",
  "Summaries and formulas": "ማጠቃለያዎችና ቀመሮች",
  "Your week at a glance": "የሳምንቱ እቅድዎ",
  "Accuracy and weak units": "ትክክለኛነትና ደካማ ምዕራፎች",
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
