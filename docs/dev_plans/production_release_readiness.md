# Production release readiness

## Context

The app has real deployment configs committed (`render.yaml`, `frontend/vercel.json`)
and the Render-RAM/embedding-migration work is already underway, but nothing has
ever audited whether the backend is safe to run as a real production service once
the current migration finishes. The user asked to plan and implement everything
needed for production. An audit (fork agent + direct reads of `main.py`,
`config/settings.py`, `api/routes_payments.py`, and this project's test-file
convention) found a working deployment skeleton with several real gaps:

- No database migration tool — schema changes rely on manual `create_all()` calls,
  which is dangerous for a database that already holds real user data (`create_all`
  cannot alter existing tables; there is no record of what schema state production
  is actually in).
- No global unhandled-exception handler and no error-tracking service — a crash
  outside the one `RateLimitExceeded` handler produces FastAPI's default response
  with no alert to anyone, visible only if someone happens to grep `app.log`.
- `/health` returns a static `{"status": "ok"}` with no check that the database is
  actually reachable, so Render's health check cannot catch a DB outage.
- CORS unconditionally allows `localhost:5173`/`127.0.0.1:5173` in every
  environment, including production (`main.py:43`).
- `JWT_SECRET_KEY` defaults to `"dev-only-change-me"` (`config/settings.py:45`) with
  nothing that stops the app from booting with that default in production if the
  env var is ever missed in Render's dashboard.
- Telegram admin notification for pending payments silently no-ops with just a log
  line if `TELEGRAM_BOT_TOKEN` is unset (`payments/admin_notify.py:35-36`) — a
  missing token in production would mean payment approvals never reach an admin,
  with nothing loud enough to surface it.
- No CI: nothing runs the backend test suite or the frontend typecheck/build
  automatically on push/PR.
- `api/routes_exam.py`'s router (`/v1/exam/solve` — the crowdsourced
  "submit any exam question, AI solves it for credits" flow, see
  `[[esh_system_boundaries]]` system 3) has been commented out of `main.py` since
  the project's very first commit (confirmed via `git log -p`) and is currently
  unreachable.

Two other things the audit flagged are explicitly **out of scope** for this plan,
per direct discussion with the user:
- **Subscription tiers UI** (phase 6 of `pwa_feature_buildout.md`) — the
  `Subscription` table exists and is read by `payments/entitlement.py`, but nothing
  ever writes to it and there's no frontend tier-picker. User chose to leave this as
  a separate future plan rather than bundle it here.
- **Real credit bundle pricing** — `CREDIT_BUNDLES` in `routes_payments.py:29-32` is
  an explicit placeholder (5 credits/25 ETB, 20 credits/90 ETB). User chose to keep
  the placeholder values and treat settling real pricing as a go-live blocker to
  resolve separately, not a code change this plan should guess at.

The user did choose to **enable the exam-solve router** as part of this release.

## Decisions settled in discussion

- **Alembic** for schema migrations, baselined against the live schema (not
  applied from zero) — see alternatives below.
- **Sentry free tier** for error monitoring, additive to the existing loguru logger.
- **Keep the existing ad-hoc `python test/test_*.py` test convention** for CI rather
  than converting ~12 files to pytest — confirmed by reading
  `test/test_esslce_route.py` that these are flat procedural scripts with top-level
  `assert` statements (no `test_`-prefixed functions pytest would collect), so a
  pytest conversion would mean rewriting every file for no behavior change CI needs.
- **Enable `exam_router`** in `main.py`, after confirming it's already protected by
  the same auth/credit-gating convention as the rest of the app (confirmed: it
  already uses `get_current_user` and `require_credits`, so no gap to fix).

## Alternatives considered

1. **Database migrations**: Alembic vs. continuing with `create_all()` + hand-written
   `ALTER` scripts vs. a lighter tool (e.g. `yoyo-migrations`). **Chosen: Alembic** —
   SQLAlchemy-native, autogenerates diffs straight from the existing declarative
   models, and has a direct, well-documented procedure for baselining a database
   that already has the tables (`stamp` instead of `upgrade`). A hand-rolled
   `ALTER` script convention would just rebuild a worse version of what Alembic
   already does, and `create_all()`-only is the status quo this plan exists to fix.
2. **Error monitoring**: Sentry free tier vs. extending loguru to push errors to
   Telegram (reusing the pattern `admin_notify.py` already has) vs. nothing.
   **Chosen: Sentry** — purpose-built (stack traces, grouping, release tracking),
   free tier covers this app's scale, and it's additive — loguru keeps doing
   structured local logging, Sentry just adds alerting on unhandled exceptions.
3. **CI test execution**: convert to pytest vs. keep the ad-hoc script loop.
   **Chosen: keep the loop** — matches the existing, deliberate convention, zero
   churn across files that work today, and pytest would buy nothing here since
   these scripts don't use fixtures or parametrization.
4. **CORS**: tighten now vs. leave as-is. **Chosen: gate the localhost origins
   behind an environment check** — cheap, doesn't change Render/Vercel behavior
   (they'll have `ENVIRONMENT=production` set), removes a real (if low-severity)
   permissiveness in the production CORS policy.
5. **Exam-solve router**: user chose to enable it. Confirmed `routes_exam.py`
   already requires auth and spends credits consistently with the rest of the app,
   so enabling it is just the uncomment.

## Implementation

### 1. Database migrations — Alembic
- Add `alembic` to `backend/requirements.txt`.
- `alembic init migrations` under `backend/`; point `env.py` at the project's
  declarative `Base` for `target_metadata`, and at `settings.DATABASE_URL` for the
  connection.
- Generate the baseline revision: `alembic revision --autogenerate -m "baseline
  existing schema"`. Inspect the generated file — since every table already
  exists in production, this file's `upgrade()` will contain `CREATE TABLE`
  statements that must **never be run** against the live database.
- Mark the live database as already at this revision without executing it:
  `alembic stamp head`. From this point on, every schema change goes through
  `alembic revision --autogenerate` + review + `alembic upgrade head`.
- Migrate the existing callers: `scripts/init_db.py` and
  `scripts/create_practice_tables.py` currently call `Base.metadata.create_all()`
  directly — whatever is pure `create_all()` responsibility is removed in favor of
  Alembic, per the no-dual-path rule, rather than left as a second, inconsistent
  way to create tables.

### 2. Global exception handling + real health check — `main.py`
- Add `@app.exception_handler(Exception)` that logs the full traceback via
  `logger.exception(...)` and returns a consistent `{"detail": "..."}` 500 body,
  so no unhandled error is silently swallowed or shown as a bare default response.
- Extend `/health` to run a trivial query (e.g. `SELECT 1`) against both
  `settings.DATABASE_URL` and `settings.VECTOR_DATABASE_URL`, returning HTTP 503
  if either fails, so Render's `healthCheckPath` can actually detect a DB outage.

### 3. Error monitoring — Sentry
- Add `sentry-sdk[fastapi]` to `requirements.txt`.
- Add an optional `SENTRY_DSN: str = ""` setting; initialize `sentry_sdk` in
  `main.py` only if it's set, so local dev needs nothing extra.
- Add `SENTRY_DSN` to `render.yaml` (`sync: false`) and `.env.example`.

### 4. Startup validation — `config/settings.py` + `main.py`
- Add `ENVIRONMENT: str = "development"` to `Settings`.
- At import time in `main.py`, right after `settings` loads: if
  `settings.ENVIRONMENT == "production"` and
  `settings.JWT_SECRET_KEY == "dev-only-change-me"`, raise immediately instead of
  booting with a known-insecure secret.
- Same spot: if `settings.ENVIRONMENT == "production"` and
  `not settings.TELEGRAM_BOT_TOKEN`, log a loud startup warning — surfaces at
  deploy time instead of only when the first payment approval silently vanishes.

### 5. CORS tightening — `main.py`
- Only append the `localhost:5173`/`127.0.0.1:5173` origins when
  `settings.ENVIRONMENT != "production"`.

### 6. Security headers — `main.py`
- Add a small middleware setting `Strict-Transport-Security`,
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and
  `Referrer-Policy: strict-origin-when-cross-origin` on every response.

### 7. Enable the exam-solve router — `main.py`
- Uncomment `app.include_router(exam_router)`.

### 8. CI — new `.github/workflows/ci.yml`
- Trigger on push/PR to `main` and `dev`.
- **backend job**: set up Python 3.11.9 (matches `render.yaml`'s pin), install
  `requirements.txt`, run each `test/test_*.py` directly (`python test/test_x.py`)
  except `test_exam_route.py` (pre-existing, unrelated fixture bug — a `FakeBuilder`
  stub missing `.embeddings` — flagged separately, not silently hidden) and
  `test1.py` (an exploratory script, not a real test). No service container needed:
  every test file provisions its own in-memory SQLite.
- **frontend job**: `npm ci && npm run build` (already runs `tsc -b && vite build`).

### 9. Config file updates
- Add `ENVIRONMENT` and `SENTRY_DSN` to both `backend/.env.example` and
  `render.yaml`.

## Verification

- Run `alembic upgrade head` against a fresh, empty database (not production) to
  confirm the baseline revision is well-formed end to end, separate from stamping
  the real database.
- Trigger a deliberate unhandled exception locally to confirm the global handler
  returns the consistent error shape and logs via loguru.
- Hit `/health` with the database intentionally unreachable to confirm it reports
  503 instead of the current unconditional 200.
- Run the full existing backend test suite directly (`venv/bin/python
  test/test_*.py`) to confirm zero regressions from the exception handler, CORS,
  and router changes.
- Push a branch to confirm the new GitHub Actions workflow actually runs both jobs
  and passes.

## Explicitly deferred (not in this plan)

- Subscription tiers UI (`pwa_feature_buildout.md` phase 6) — separate future plan.
- Real credit bundle pricing — business decision; current placeholders kept and
  flagged as a go-live blocker to resolve before accepting real payments.
- Converting backend tests to pytest — kept exactly as the project already runs them.
