# Deploying

Frontend on Vercel, backend on Render, all persistent state (Postgres, vector search,
exam diagram photos, payment receipts) on Supabase's free tier. See
`docs/dev_plans/deploy_vercel_render_supabase.md` for why this split.

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

## 3. Render (backend)

New Web Service → connect the repo → it picks up `render.yaml` at the repo root
automatically. Fill in the env vars `render.yaml` leaves blank (`sync: false`):
`DATABASE_URL`, `VECTOR_DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
`GROQ_API_KEY`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN` (optional - only needed for
the admin payment-review push), and `ALLOWED_ORIGINS` once you have the Vercel URL
from step 4. `JWT_SECRET_KEY` is generated for you.

## 4. Vercel (frontend)

New Project → import the repo → set the root directory to `frontend`. Add one env
var: `VITE_API_BASE_URL` = the Render service's URL from step 3. Deploy.

## 5. Close the loop

Back in Render, set `ALLOWED_ORIGINS` to the Vercel URL from step 4 (comma-separated
if there's more than one, e.g. a preview + production domain) and redeploy - CORS
needs the real frontend origin to let it through.

## Verifying it worked

- `GET <render-url>/health` → `{"status": "ok"}`
- Sign up through the Vercel URL, ask `/v1/explain` a question - confirms Postgres,
  pgvector, and the LLM keys are all wired correctly.
- Open an ESSLCE question that has a diagram - confirms Supabase Storage.
