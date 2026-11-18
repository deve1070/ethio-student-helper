# Ethiopian Student Helper

An exam-preparation platform for Ethiopian students in Grades 9–12, built around the
national exam (ESSLCE). It has a web app, an installable PWA, and a Telegram bot, all
backed by one API.

Students get AI explanations grounded in the Ministry of Education textbooks, a bank of
past ESSLCE questions with answers and explanations, practice by unit, study notes, a
weekly study plan, and a daily group practice in Telegram with a leaderboard.

## Features

**Learning**
- **Ask the textbook** — free-text questions answered from the MoE textbooks, scoped to a
  grade and subject, with citations (textbook, unit, page). An answer is returned only if
  it can quote a matching passage; otherwise the app says it doesn't know.
- **ESSLCE past papers** — practice by year, by unit or by skill, or sit a full timed exam
  with results at the end. Math is rendered properly; questions with diagrams show the
  original page photo.
- **Deeper help on a question** — "Explain more" (cached per question) and a free-form
  "Ask about this" chat, both grounded in the textbook.
- **Practice and mistakes** — unit-based practice from the approved question bank, accuracy
  per unit, and a review of past mistakes.
- **Spaced review** — a question answered wrong comes back 1, 3 and 7 days later until it's
  answered right three times in a row; due questions are on the dashboard and in the bot.
- **How each unit is tested** — for every textbook unit: how many past exams included it, how many
  questions, and a summary of recurring concepts, question styles and tips drawn from the real
  past questions.
- **Exam readiness** — a projected score per subject, weighting each unit by how much of the real
  exam it makes up, shown with how much of the exam the estimate rests on.
- **Study notes** — per-topic notes with worked examples and formulas, downloadable as PDF.
- **Study plan** — a multi-day plan paced to the student's exam date.
- **Solve an exam question** — type or photograph a question; answers other students already
  asked come back instantly from a shared cache.

**Daily mass practice (Telegram, subscribers only)**
- A fixed evening time each day, with a heads-up message 10 minutes before.
- Native Telegram polls in a private group, one topic per stream. On a day whose subject is
  not common to both streams, natural-science and social-science students each get their own
  questions.
- The full question is posted in the group so students can discuss it; an "Ask AI" button
  opens the question in the student's own chat.
- Nothing is revealed during the polls. After the last one, the group gets the ranking and
  an answer key with explanations.
- Missed it? `/catchup` answers the same questions privately, with instant results. Those
  answers keep the student's streak but don't count toward the score ranking.
- Students whose streak ends tonight get a private reminder.
- The day's unit is chosen by how often past exams test it and how badly the group does on it,
  skipping units used in the last two weeks; the reveal ends with how that unit is tested.
- Every Sunday each student gets a private summary of their week, with a button into practice on
  their weakest unit.
- Leaderboards on the web: the latest practice, this week, and most consistent days.
- Access is gated by subscription: the bot approves join requests only for subscribers and
  removes lapsed ones daily.

**Accounts and payments**
- One login across web and Telegram, with a phone number or email; password reset goes
  through the linked Telegram chat.
- A one-year subscription (300 ETB). Students pay by bank transfer and submit the receipt;
  a vision model checks it against the amount and transaction id, and an admin approves or
  rejects the rest from Telegram. Before subscribing, every account has a small shared
  allowance of free AI actions.
- Referral codes, with earnings shown on the profile.

**Everywhere**
- English and Amharic. The web app's navigation, login, sign-up and dashboard and the bot's main
  menu are translated (switch in Profile, on the login page, or with `/language`); other screens
  and all exam content stay in English for now.
- Notes, the study plan, mistakes and progress stay readable offline once opened; practice needs
  a connection, since answers are graded on the server.

## How it works

```
 React PWA (Vercel) ──┐
                      ├──►  FastAPI backend (Railway) ──►  Postgres + pgvector (Supabase)
 Telegram bot ────────┘            │                       Supabase Storage (photos, receipts)
 (Railway worker)                  └──►  Groq (answers), Gemini (cross-check), local embeddings
```

- **Retrieval.** Textbooks are split into chunks and embedded with `fastembed`
  (`BAAI/bge-small-en-v1.5`, ONNX Runtime, runs in-process, no API) into pgvector. A question
  is embedded the same way and searched against its grade and subject.
- **Grounding.** The model must return a supporting quote, and the answer is rejected unless
  that quote appears in the retrieved passage. Calculation questions are verified by running
  the generated code and comparing its result with the keyed answer.
- **LLMs.** Groq generates; Gemini is a second, independent model that cross-checks answers.
  Rate-limit and connection errors are retried with backoff (`backend/llm/retry.py`).
- **Exam bank.** Scanned past papers go through a vision-model extraction pipeline, then
  keying (an official key when one exists, AI-proposed and quote-verified otherwise), human
  review, and linking each question to textbook units. Only approved questions reach
  students.
- **The bot is a thin client.** It stores only login sessions and reminders; everything else
  is an HTTP call to the backend.

## Repository layout

```
backend/            FastAPI service
  api/              One router per feature (auth, explain, exam, esslce, practice, notes, ...)
  db/               SQLAlchemy models; migrations/ holds the Alembic history
  exams/            ESSLCE bank: extraction, keying, linking, serving; `python -m exams.cli`
  ingestion/        Textbook ingestion
  retriever/        Embeddings, pgvector store, citations
  llm/              Groq and Gemini clients, retry logic
  payments/         Subscription, free-action quota, receipt verification, referrals
  test/             Standalone test scripts (test_*.py)
frontend/           React 19, TypeScript, Vite, Tailwind (PWA)
telegram_bot/       python-telegram-bot client; mass_challenge.py is the daily practice
docs/               data-model-api.md and dev_plans/ (a design note per feature)
railway.json        Bot service config on Railway; backend/railway.json is the backend's
bot.py              Railway entry point for the bot (delegates to telegram_bot/bot.py)
DEPLOY.md           Step-by-step production deployment
```

## Getting started

Requirements: Python 3.11, Node 20+, PostgreSQL with the
[pgvector](https://github.com/pgvector/pgvector) extension, a free
[Groq](https://console.groq.com) key and a free [Gemini](https://aistudio.google.com) key.

### Backend

```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt          # what the server runs (about 700MB)
cp .env.example .env                     # fill in the keys and DATABASE_URL
alembic upgrade head                     # create the tables
uvicorn main:app --reload                # http://localhost:8000, health check at /health
```

`requirements.txt` is only what the server imports. Ingesting textbooks, OCR and exam
extraction need the full set, which pulls in torch: `pip install -r requirements-dev.txt`.

### Frontend

```bash
cd frontend
npm ci
npm run dev                              # http://localhost:5173
```

In development Vite proxies `/v1` to `http://localhost:8000`. For a deployed build, set
`VITE_API_BASE_URL` to the backend's URL. `npm run build` type-checks and builds;
`npm run lint` runs ESLint.

### Telegram bot

```bash
pip install -r requirements.txt          # from the repository root
# the bot reads backend/.env; TELEGRAM_BOT_TOKEN comes from @BotFather
python -m telegram_bot.bot               # run from the repository root
```

Run a single bot process: login sessions live in one file, which is not safe to share
between processes. Commands: `/start /login /logout /practice /progress /esslce /explain
/exam /remind /catchup /status /subscribe /help /language`.

### Loading content

Textbooks and exam papers are loaded offline, on your own machine, straight into the database
the server reads. The server never embeds a book.

```bash
cd backend
# textbooks: PDFs under content/moe_textbooks/grade_<N>/<subject>/
python -m ingestion.textbook_ingest

# one past paper, end to end
python -m exams.cli extract "Biology 2016 ESSLCE.pdf" --subject biology --year-ec 2016 \
    --provider gemini --vision-model gemini-3.5-flash-lite --out exams_out
python -m exams.cli load  exams_out/biology_2016
python -m exams.cli solve biology 2016         # propose answers and textbook links
python -m exams.cli approve biology 2016 --all-clean
python -m exams.cli index biology 2016
```

`python -m exams.cli --help` lists every step and option (some papers need `--stream`,
`--region` or `--delivery-mode`). Source PDFs are kept as
`content/<natural|social|common>/<subject>/<subject>_<ec>_<gc>_esslce.pdf`.

## Configuration

Every variable is documented in `backend/.env.example`. The important ones:

| Variable | Purpose |
|---|---|
| `DATABASE_URL`, `VECTOR_DATABASE_URL` | Postgres (the second uses the psycopg3 driver) |
| `GROQ_API_KEY`, `GEMINI_API_KEY` | Answer generation and cross-checking |
| `JWT_SECRET_KEY` | Signs login tokens; the server refuses the default in production |
| `ENVIRONMENT` | `production` turns on the startup checks |
| `ALLOWED_ORIGINS` | The deployed frontend's origin(s), for CORS |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Storage for diagram photos and receipts (empty = local disk) |
| `TELEGRAM_BOT_TOKEN`, `BOT_INTERNAL_TOKEN` | The bot, and its shared secret with the backend |
| `TELEGRAM_PRIVATE_GROUP_ID`, `MASS_CHALLENGE_*` | The daily practice (an id of 0 disables it) |
| `BOT_DATA_DIR` | Where the bot keeps its state file |
| `SUBSCRIPTION_PRICE_ETB`, `PAYMENT_TELEBIRR_NUMBER`, `PAYMENT_CBE_ACCOUNT` | The price and where students send it; set on the backend, read by the app and the bot |
| `REFERRAL_REWARD_ETB` | What a referral earns; a change applies to later referrals only |
| `TELEGRAM_CHANNEL_URL` | The public channel students are invited to |

## Tests

Each `backend/test/test_*.py` is a standalone script with its own in-memory database, so no
services are needed.

```bash
cd backend
for f in test/test_*.py; do python "$f" || break; done
```

CI (`.github/workflows/ci.yml`) runs these and the frontend build on every push and pull
request to `main` and `dev`.

## Deployment

The frontend runs on Vercel, the backend and the bot on Railway, and the data on Supabase.
See [DEPLOY.md](DEPLOY.md), which also covers error reporting (Sentry), an uptime monitor and the
nightly encrypted database backup (`.github/workflows/backup.yml`). Two things to know: run the backend as a single worker, because
each worker loads its own copy of the embedding model (about 280MB); and give the bot service
a volume, or every deploy logs all students out.

## Status

Pre-launch. Known gaps:
- Vector search has no ANN (HNSW) index, on purpose. Every textbook search filters by grade and
  subject first, which the metadata index narrows to about a thousand chunks, then sorts those
  exactly: measured at about 50ms on the full 26,000-chunk collection. An HNSW index would make
  those filtered searches approximate and could return fewer than the requested results. Worth
  revisiting only if unfiltered searches become common or the corpus grows by an order of
  magnitude.
- Mass practice runs on in-memory scheduled jobs. A restart resumes from the polls already
  recorded, but a long outage can still lose a day's event.
- There is no Flutter client yet; the PWA is the mobile app for now.

More design detail is in `docs/dev_plans/` and `docs/data-model-api.md`.

## Authors

Built by Dawit and Betsinat.
