"""Bot interface language, per student (/language; kept in store.py's "lang" section). Like the
web app's lib/i18n.tsx, each English string is its own key and anything missing from AM stays in
English. Covers the main menu, /start and /help; the rest of the bot is still English."""

from telegram_bot import store as bot_store

AM = {
    "📝 Practice": "📝 ልምምድ",
    "📊 Progress": "📊 እድገት",
    "🎓 ESSLCE past papers": "🎓 ያለፉ የESSLCE ፈተናዎች",
    "❓ Ask the textbook": "❓ መጽሐፉን ይጠይቁ",
    "📷 Exam question": "📷 የፈተና ጥያቄ",
    "⏰ Reminders": "⏰ ማስታወሻዎች",
    "💳 My status": "💳 የእኔ ሁኔታ",
    "🛒 Subscribe": "🛒 ይመዝገቡ",
    "🔐 Login": "🔐 ግባ",
    "🚪 Logout": "🚪 ውጣ",
    "🆘 Help": "🆘 እገዛ",
    "🌐 Language": "🌐 ቋንቋ",
    (
        "Welcome to the Ethiopian Student Helper! Tap a button below, or type / to see every command.\n\n"
        "Tip: run /login once even if you're already logged in on the app - it links this chat to your "
        "account, which is also what lets you reset your password from the app later if you ever forget it."
    ): (
        "እንኳን ወደ የኢትዮጵያ ተማሪዎች ረዳት በደህና መጡ! ከታች ያለውን ቁልፍ ይጫኑ፣ ወይም ሁሉንም ትዕዛዞች ለማየት / ይጻፉ።\n\n"
        "ጠቃሚ ምክር፦ በመተግበሪያው ቢገቡም አንድ ጊዜ /login ያድርጉ — ይህን ውይይት ከመለያዎ ጋር ያገናኛል፣ "
        "የይለፍ ቃልዎን ቢረሱም ከመተግበሪያው ዳግም ለማስጀመር የሚያስችለውም ይህ ነው።"
    ),
    "Follow our channel for updates and study tips:\n{url}": "ለዜናና የጥናት ምክሮች ቻናላችንን ይከታተሉ፦\n{url}",
    "Developed by Dawit and Betsinat.": "ያዘጋጁት ዳዊት እና ብጽናት ናቸው።",
    "Having trouble? Use /login to link your account, or ask your question with /explain.":
        "ችግር አጋጠመዎት? መለያዎን ለማገናኘት /login ይጠቀሙ፣ ወይም ጥያቄዎን በ/explain ይጠይቁ።",
    "Choose your language:": "ቋንቋ ይምረጡ፦",
    "Language set to English.": "Language set to English.",
    "Language set to Amharic.": "ቋንቋው ወደ አማርኛ ተቀይሯል።",
}


def tr(uid: int, text: str, **values) -> str:
    out = AM.get(text, text) if bot_store.get_store().get_lang(uid) == "am" else text
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out
