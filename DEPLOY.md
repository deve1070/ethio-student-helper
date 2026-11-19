# Deploying

Frontend on Vercel, backend + Telegram bot on Railway, all persistent state (Postgres,
vector search, exam diagram photos, payment receipts) on Supabase's free tier. See
`docs/dev_plans/deploy_vercel_render_supabase.md` for why the data-layer split in
particular; Railway replaced Render specifically because Render's free tier has no
way to run the Telegram bot as an always-on background worker (only a web service
with a public port) - Render's steps are kept below as a backend-only fallback.

## 1. Supabase (data)

1. Create a project at supabase.com (free tier).
2. SQL Editor → run `CREATE EXTENSION IF NOT EXISTS vector;` (PGVector's own
   `create_extension=True` also tries this automatically, but doing it once up
   front avoids a race on first deploy).
3. Project Settings → Database → Connection string → URI. Use it twice:
   - as `DATABASE_URL`, with `postgresql+psycopg2://` in place of `postgresql://`
   - as `VECTOR_DATABASE_URL`, with `postgresql+psycopg://` in place of `postgresql://`
4. Storage → create two buckets: `exam-pages` and `receipts` (both private - this
   app reads them with its own service key, never a public URL).
5. Project Settings → API → copy the Project URL (`SUPABASE_URL`) and the
   `service_role` key (`SUPABASE_SERVICE_KEY` - server-side only, never ships to
   the frontend).

## 2. Migrate existing local data (skip on a fresh install with no local data yet)

From `backend/`, venv active, with the `.env` vars above already set to point at
Supabase:

```
# relational data (users, questions, payments, ...)
pg_dump postgresql://postgres:postgres@localhost:5544/ethio_student_helper \
  | psql "<supabase connection string>"

# vectors (reuses each document's existing embedding, doesn't recompute)
python -m scripts.migrate_vectors_to_pgvector

# exam diagram photos + payment receipts
python -m scripts.migrate_storage_to_supabase
```

## 3. Railway (backend + Telegram bot)

One Railway project, **two services**, both pointed at this same repo - their
`railway.json` files live at different paths specifically because of how each
one's Python imports work (see the comment at the top of `bot.py`), not by
accident:

### 3a. Backend service

- New Service → Deploy from GitHub repo → this repo.
- Settings → Root Directory: `backend`. It picks up `backend/railway.json`
  automatically (build: `pip install -r requirements.txt`; start: `uvicorn
  main:app --host 0.0.0.0 --port $PORT` - deliberately no `--workers` flag, since
  each worker would load its own separate copy of the ~280MB embedding model).
  Before each deploy goes live it runs `alembic upgrade head` (`preDeployCommand`), so
  new database migrations apply themselves; a failed migration stops the deploy and
  the previous version keeps serving.
  `backend/requirements.txt` is the slim production set (only what the live server
  imports); the offline ingestion/OCR/extraction tooling lives in
  `backend/requirements-dev.txt`, which is what to install on a development machine.
- Settings → Resource limits: set a ceiling (not a reservation - Railway bills
  actual usage either way) of around 1 vCPU / 1GB RAM. Measured locally, the
  worker process sits around 330-400MB RSS with the embedding model loaded; 1GB
  leaves real headroom for request spikes without being wasteful.
- Variables: `DATABASE_URL`, `VECTOR_DATABASE_URL`, `SUPABASE_URL`,
  `SUPABASE_SERVICE_KEY`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `JWT_SECRET_KEY`
  (generate a real random value, don't reuse the dev default),
  `BOT_INTERNAL_TOKEN` (generate one - must match the bot service's value
  exactly), `TELEGRAM_BOT_TOKEN`, `TELEGRAM_PRIVATE_GROUP_ID`, `TELEGRAM_PRIVATE_GROUP_URL`
  (the subscriber group's invite link, shown on the Profile page to subscribers only),
  `ENVIRONMENT=production`. Optional, with working defaults: `TELEGRAM_CHANNEL_URL` (the public
  channel), `SUBSCRIPTION_PRICE_ETB`, `PAYMENT_TELEBIRR_NUMBER`, `PAYMENT_CBE_ACCOUNT`,
  `REFERRAL_REWARD_ETB`. The app and the bot read the price and accounts from the backend, so a
  change here needs only a backend redeploy.
  `ALLOWED_ORIGINS` (fill in once you have the Vercel URL from step 4).
- Generate a public domain for this service (Settings → Networking) - you'll
  need its URL for both the frontend's `VITE_API_BASE_URL` and the bot's
  `BACKEND_BASE_URL` below.

### 3b. Telegram bot service

- Same Railway project → New Service → Deploy from GitHub repo → this repo again.
- Settings → Root Directory: leave as the **repo root** (not `telegram_bot`) -
  its code imports itself as `from telegram_bot import ...`, which only resolves
  correctly when the repo root is the working directory. It picks up the
  repo-root `railway.json` (start: `python bot.py`, a thin wrapper that exists
  only so Railway's Python auto-detection finds an entry file at the root - see
  that file's own docstring).
- **Volume (required):** add a Railway volume to this service, mounted at `/data`,
  and set `BOT_DATA_DIR=/data`. The bot keeps every student's login session, daily
  reminder and subject preference in one file (`state.json`, see
  `telegram_bot/store.py`). A Railway container's own disk is replaced on every
  deploy, so without the volume each deploy logs every student out and deletes
  every reminder.
- Settings → Resource limits: much lighter than the backend - measured locally
  at ~56MB RSS idle, no embedding model, no torch. 0.5 vCPU / 0.5GB is generous.
- Variables: `TELEGRAM_BOT_TOKEN`, `BOT_INTERNAL_TOKEN` (same value as the
  backend's), `TELEGRAM_CHANNEL_URL` (optional), `TELEGRAM_PRIVATE_GROUP_ID` (same value as
  the backend's), `MASS_CHALLENGE_TIME`, `MASS_CHALLENGE_HEADSUP_MINUTES`, `MASS_CHALLENGE_NUDGE_MINUTES`,
  `MASS_CHALLENGE_NATURAL_TOPIC_ID`, `MASS_CHALLENGE_SOCIAL_TOPIC_ID`, optionally `CHANNEL_POSTS`,
  `CHANNEL_POST_TIME`, `CHANNEL_FEATURE_DAYS`, `CHANNEL_CHAT_ID` (channel posts; the bot must be a
  channel admin with "Post messages"), optionally `NUDGE_TIME` and `SUPPORT_CONTACT`,
  `BOT_DATA_DIR=/data`, and
  `BACKEND_BASE_URL` = the backend service's public URL from step 3a (Railway's
  private-networking domain, `<service>.railway.internal`, is a worthwhile
  latency/egress optimization once the public-URL version is confirmed working
  - not needed for a first deploy).

## 4. Vercel (frontend)

New Project → import the repo → set the root directory to `frontend`. Add one env
var: `VITE_API_BASE_URL` = the backend service's URL from step 3a. Deploy.

## 5. Close the loop

Back in the Railway backend service, set `ALLOWED_ORIGINS` to the Vercel URL from
step 4 (comma-separated if there's more than one, e.g. a preview + production
domain) and redeploy - CORS needs the real frontend origin to let it through.

## Verifying it worked

- `GET <railway-backend-url>/health` → `{"status": "ok"}`
- Sign up through the Vercel URL, ask `/v1/explain` a question - confirms Postgres,
  pgvector, and the LLM keys are all wired correctly.
- Open an ESSLCE question that has a diagram - confirms Supabase Storage.
- `/start` the bot on Telegram, `/login` - confirms the bot service is up and can
  reach the backend.

## 6. Monitoring and backups

**Errors (Sentry).** Create a free project at sentry.io (platform: Python) and set the same
`SENTRY_DSN` on both Railway services, plus `ENVIRONMENT=production` on the bot service too. The
backend reports unhandled errors; the bot reports every error it logs (a failed send, a failed
backend call, a job that crashed). Events are tagged `service: backend` or `service: telegram_bot`.

**Uptime.** Create a free monitor at uptimerobot.com: type HTTP(s), URL
`<railway-backend-url>/health`, every 5 minutes, alerting your email or Telegram. `/health` checks
both database connections and returns 503 if either is down, so it catches a database outage as
well as the server itself.

**Database backups.** `.github/workflows/backup.yml` runs every night at 02:30 Addis Ababa time and
on demand (Actions → Nightly database backup → Run workflow). It dumps the app's tables (the
`public` schema), encrypts the dump with your passphrase, and keeps it for 14 days as a workflow
artifact. Add two repository secrets (Settings → Secrets and variables → Actions):

- `BACKUP_DATABASE_URL`: the Supabase connection string in plain `postgresql://...` form.
- `BACKUP_PASSPHRASE`: a long random string. Keep a copy somewhere other than GitHub; without it
  the backups can't be opened.

Run it once by hand after adding the secrets and check that the run succeeds. To restore, download
the artifact and run:

```
gpg -d esh-YYYYMMDD.dump.gpg > esh.dump
pg_restore --clean --if-exists --no-owner -d "<postgresql://... connection string>" esh.dump
```

`--clean` replaces the existing tables. To inspect a backup without touching production, restore
it into a separate database instead.

## Alternative: Render (backend only, no bot worker)

Kept for reference - Render's free tier can't run the bot as an always-on worker,
only a web service with a public port, so this path leaves the bot undeployed.

New Web Service → connect the repo → it picks up `render.yaml` at the repo root
automatically. Fill in the env vars `render.yaml` leaves blank (`sync: false`):
`DATABASE_URL`, `VECTOR_DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
`GROQ_API_KEY`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `BOT_INTERNAL_TOKEN`,
`TELEGRAM_PRIVATE_GROUP_ID`, and `ALLOWED_ORIGINS` once you have the Vercel URL.
`JWT_SECRET_KEY` is generated for you.
