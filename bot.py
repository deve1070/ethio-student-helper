"""Railway deployment entry point only - the real implementation lives in telegram_bot/bot.py.

Railpack's Python auto-detection requires a recognized entry filename (bot.py, main.py, ...) AND
requirements.txt directly at the build root, neither of which is true of telegram_bot/ on its own
(its own code imports itself as `from telegram_bot import ...`, so it must run with the repo root
as the working directory, not telegram_bot/ itself - see railway.json's startCommand). This file
exists purely to satisfy that detection; it carries no logic of its own."""
from telegram_bot.bot import main

if __name__ == "__main__":
    main()
