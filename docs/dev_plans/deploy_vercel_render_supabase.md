# Deploy prep: Vercel (frontend) + Render (backend) + Supabase (data)

## Context

The app needs to go live: frontend on Vercel, backend on Render. Two things stood
in the way of just writing deployment config files:

1. The backend has no CORS middleware at all — fine when frontend and backend
   shared an origin via Vite's dev proxy, broken the moment they're on separate
   domains (Vercel vs Render).
2. Three local-disk directories are read at request time, not just during
   ingestion: `chroma_db/` (powers `/v1/explain`, ESSLCE citations, Study Notes
   retrieval), `exams_out/*.jpg` (the real source-page photo for a has_diagram
   ESSLCE question), and `receipts/` (payment-proof photos students upload).
   Render's web-service disk is wiped on every redeploy. Render's persistent
   disk add-on would fix this but costs money, which the user said they can't
   spend right now.

Checked and confirmed live (not assumed):
- `backend/content/` (1.9GB, raw textbook PDFs) is **ingestion-only** — no
  request-serving route reads it, so it never needs to leave the local machine.
- Chroma holds 26,239 `textbooks` vectors + 1,654 `esslce_exams` vectors, both
  384-dim (BAAI/bge-small-en-v1.5). At ~1.5KB/vector plus content+metadata+index
  overhead that's roughly 100-150MB — comfortably under Supabase's free-tier
  500MB Postgres cap, which is the real constraint for the pgvector option.
- `exams_out/*.jpg` + `receipts/` together are ~218MB, under Supabase's 1GB free
  Storage cap.
- The codebase's only Chroma filter pattern is Mongo-style
  (`{"$and": [{"grade": g}, {"subject": s}]}`, used via
  `.as_retriever(search_kwargs={"filter": ...})`). Confirmed via LangChain's own
  docs that `langchain_postgres.PGVector` supports the same `$and`/`$eq`/bare-key
  operators, so this is a compatible swap, not a rewrite of every call site's
  filter logic.
- `langchain-postgres` requires the `psycopg` (v3) driver; the existing
  SQLAlchemy ORM engine keeps using `psycopg2-binary` unchanged — the two
  drivers coexist fine, each on its own connection string scheme.

Decision: use Supabase's free tier for **all** persistent state (Postgres +
pgvector + Storage), making the Render web service fully stateless. This is a
real migration (swap Chroma for pgvector, swap local-disk image/receipt reads
for Supabase Storage), not just config — but it's the only path that costs
nothing at the current data scale, and it converges all three storage needs
(DB, vectors, files) onto one free-tier account instead of juggling Render disk
pricing for some of it.

Separately: `backend/`, `telegram_bot/`, and `docs/` have a large backlog of
real, working, never-committed code (the whole ESSLCE exam bank, Study Notes,
payments, auth hardening, rate limiting, the entire `frontend/` app — currently
0% committed). This gets organized into logical commits alongside the deploy
work, with generated/scratch content kept out of git via `.gitignore` rather
than committed or deleted.

## What does NOT change

- `exams/cache.py` / `api/routes_exam.py` (the separate, already-disabled
  `ExamCache` system — `# app.include_router(exam_router)` is commented out in
  `main.py`, and its own Chroma collection has 0 documents). Confirmed dead on
  the live path; left alone, not migrated, not deleted.
- `document_cache/` (`CACHE_DIR`) — genuinely a cache (has `CACHE_EXPIRE_DAYS`),
  fine to lose on redeploy, no migration needed.
- The relational schema itself — Supabase Postgres is wire-compatible, this is
  a connection-string swap (`DATABASE_URL` env var), no model changes.

## Work items

### 1. `retriever/vectorstore.py` (new) — the one choke point

A single `get_vector_store(collection_name: str, embedding_function)` function
wrapping `langchain_postgres.PGVector`, built once so every caller gets the
same connection handling. Returns an object with the same
`similarity_search_with_score(query, k, filter)` / `.as_retriever(...)`
surface the codebase already depends on (confirmed compatible above), so call
sites change their *construction* line only, not their query logic.

Migrate every existing `Chroma(...)` construction to call this instead
(9 sites, same mechanical edit each time — construct via the new function
instead of importing `Chroma` directly):
`retriever/builder.py`, `api/routes_esslce.py`, `api/routes_notes.py`,
`ingestion/textbook_ingest.py`, `exams/cli.py`, `scripts/book_report.py`,
`scripts/question_stats.py`, `scripts/generate_questions.py`,
`scripts/seed_sample_content.py`. No dual-mode flag — once this lands, nothing
in the live path still knows how to talk to local Chroma (per "migrate
callers, never add fallbacks").

### 2. `storage.py` (new) — Supabase Storage client

Thin wrapper (`upload(bucket, path, bytes) -> url`, `download(bucket, path) ->
bytes | None`) over Supabase's S3-compatible Storage REST API. Replaces:
- `exams/store.py`'s `question_page_image()` (currently
  `Path(paper.source_dir) / f"p{page:02d}.jpg"` + `read_bytes()`) — reads from
  a `exam-pages` bucket instead, keyed by the same relative path already
  stored in `paper.source_dir`/`printed_page`, so no DB schema change.
- `api/routes_payments.py`'s receipt save (currently writes to
  `settings.RECEIPTS_DIR` locally) — uploads to a `receipts` bucket instead.

### 3. CORS

Add `CORSMiddleware` to `main.py`. New `ALLOWED_ORIGINS: list[str]` setting
(env-driven, comma-separated), defaulting to `["http://localhost:5173"]` for
local dev; set to the real Vercel URL in Render's env vars.

### 4. Settings additions (`config/settings.py`)

`SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (Storage access), `ALLOWED_ORIGINS`.
`DATABASE_URL` and `CHROMA_DB_PATH` — `CHROMA_DB_PATH` gets dropped entirely
once nothing constructs local Chroma anymore.

### 5. `requirements.txt`

Add `langchain-postgres`, `psycopg[binary]`. Drop `chromadb` /
`langchain_community.vectorstores`'s Chroma usage only once step 1 is fully
migrated (keep `langchain_community` itself — other integrations in it are
still used).

### 6. Local validation before touching any cloud account

Install the `pgvector` extension into the existing local docker Postgres
(already running, port 5544 per project memory) and point the new
`retriever/vectorstore.py` at it for testing. Run the full backend test suite,
then manually smoke-test `/v1/explain`, an ESSLCE practice session (incl. a
has_diagram question once storage.py is stubbed/local), and Study Notes
generation against it. This proves the migration works without needing the
user's Supabase credentials yet.

### 7. One-time migration scripts (prepared now, run later by the user)

- `scripts/migrate_vectors_to_pgvector.py`: reads local Chroma (both
  collections), writes to the target Postgres via the new vector store
  builder. Idempotent (safe to re-run).
- `scripts/migrate_storage_to_supabase.py`: uploads `exams_out/*.jpg` and
  `receipts/*` to the two Supabase Storage buckets.
- Relational data: plain `pg_dump`/`pg_restore` (documented command in
  DEPLOY.md, no script needed — standard tooling, nothing project-specific).

These need the user's real Supabase project URL/keys, which I don't have — I
prepare and locally-test the scripts' logic, the user runs them once their
Supabase project exists.

### 8. Deployment configs

- `render.yaml`: single web service, no disk, build
  `pip install -r backend/requirements.txt`, start
  `uvicorn main:app --host 0.0.0.0 --port $PORT`, Python version pinned.
- `frontend/vercel.json`: SPA rewrite (`/(.*) -> /index.html`) so client-side
  routes survive a hard refresh.
- `.env.example` (backend) updated with the new Supabase/CORS vars.
- `docs/dev_plans/` stays as the plan record; a short root-level `DEPLOY.md`
  gives the actual click-through runbook (create Supabase project → enable
  `pgvector` extension → create two Storage buckets → run the two migration
  scripts → `pg_dump`/`pg_restore` → create Render service with env vars →
  create Vercel project with `VITE_API_BASE_URL` set to the Render URL).

### 9. Git hygiene

- Extend `.gitignore` (root + `backend/.gitignore`) to exclude data/generated
  content (`exams_out/`, `backend/exams/content/`, `backend/exams/temp/`,
  `backend/content/`, `backend/chroma_db/`, `backend/receipts/`,
  `telegram_bot/data/`) and the scratch files from the earlier audit
  (`reclean_backup_*.jsonl`, `debug_*.py`, `check_*.py`, `*.bak`, `nohup.out`,
  `project.zip`, `audit_*.json`, `practice_rejected.jsonl`) — left on disk,
  never committed, per your answer.
- Commit the real backlog in small, logical groups by feature/system
  boundary (matching the project's own module boundaries): auth/rate-limiting,
  ESSLCE exam bank, Study Notes, payments, the entire `frontend/` app (0%
  committed today), telegram bot updates, docs. Then the deploy-prep changes
  (items 1-8 above) as their own trailing commits, separate from the backlog.
- Short, plain commit messages (conventional-style: `feat: ...`, `fix: ...`),
  no AI/Claude mentions, no `Co-Authored-By` trailer — per your explicit
  instruction, which overrides this session's default attribution.

## Verification

- `python test/test_esslce_pipeline.py`, `test_esslce_route.py`,
  `test_notes.py`, `test_practice_core.py`, `test_practice_api.py`,
  `test_latex_render.py` — must all still pass once Chroma stubs in test files
  are updated to target `retriever.vectorstore.get_vector_store` instead of
  `langchain_community.vectorstores.Chroma`.
- Local pgvector smoke test (step 6) before any cloud work.
- `cd frontend && npx tsc --noEmit` clean, `npm run build` succeeds (Vercel
  build parity check).
- `uvicorn main:app` boots locally with `CORSMiddleware` installed; a
  cross-origin fetch from the Vite dev server (different port) succeeds.
- Final: this plan's step 6-8 scripts get a dry run against the user's real
  Supabase project once created, before calling the migration "done."
