# Gemini embedding migration + hierarchical textbook chunks + exam provenance fields

## Context

The backend can't fit Render's free tier: loading the local embedding model
(`HuggingFaceEmbeddings("BAAI/bge-small-en-v1.5")` in `retriever/builder.py`)
alone pushes RSS to ~800MB, measured directly. The fix already half-exists in
the code — `GoogleGenerativeAIEmbeddings` is written and commented out right
above the line that's actually running. Switching to it drops local RAM to
near nothing (Gemini embeds via API call) and, per MTEB numbers, is likely a
retrieval-quality upgrade too, not just a RAM fix — `bge-small-en-v1.5` is a
33M-parameter model that trails larger models on retrieval benchmarks.

Since every textbook/exam vector must be re-embedded anyway (switching models
changes the vector space), the user wants to use the migration as a chance to
make textbook embeddings hierarchy-aware — bake each chunk's unit/section
context into the embedded text, not just side-channel metadata, "to get most
out of the embedding." Exploration turned up a second, concrete reason to do
this precisely now: the app's "practice questions from this unit across every
year" feature (`routes_esslce.py`'s `/next` with `unit=`, backed by
`exams/store.py`'s `best_unit()`/`EsslceTopicLink`) is driven by embedding an
exam question's own text and searching the **textbook** collection for the
closest chunks, then reading *their* unit/section metadata to classify the
question. Making textbook chunks hierarchy-aware should directly sharpen that
classification step — the user confirmed this is the feature to protect.

The user also flagged that shown questions are missing provenance info
(year, booklet code) beyond the question number — a separate, small, clearly
scoped addition bundled into this same effort since it touches the same
`EsslceQuestionOut` response path.

## Decisions already settled in discussion

- **Hierarchy prefix applies to the "textbooks" collection only.**
  `exams/store.py:embed_text` (the `esslce_exams` collection, used for
  question-bank duplicate matching) and `exams/cache.py:ExamCache` (the
  `exam_questions` collection, used for ad-hoc answer caching) are both
  deliberately written to embed *only* the question's own wording — their
  existing code comments explain that mixing in paper/unit context would
  pull every question from the same paper/unit toward each other and away
  from a student's own rephrasing, breaking the "is this the same question
  we already answered" match. Both collections still get re-embedded with
  the new model — their embedded *text* just doesn't change shape. Unit
  context for exam questions keeps flowing through `EsslceTopicLink`/
  `best_unit()` as metadata, not through the embedding text itself.
- **Migration reuses already-stored text, no PDF re-parsing.** The DB/vector
  metadata only ever persisted `unit` (top heading) and `section` (the
  *last* heading in a chunk's trail) — any middle heading levels were
  discarded at ingestion time and aren't recoverable without re-running
  Docling. User chose the re-embed-only path: read each chunk's existing
  document text + its `unit`/`section` metadata straight from the pgvector
  tables, build a 2-level prefix from what's already there, re-embed. Existing
  `Chunk` DB rows are untouched (same ids, same `vector_id`).

## Alternatives considered

1. **Full re-ingestion** (re-run Docling parsing + `HierarchicalChunker` from
   the original PDFs) to capture the complete multi-level heading trail —
   rejected: slower, and re-exposes the ingestion pipeline's known
   PDF-extraction quirks (garbled fonts, running headers/footers, OCR gaps)
   that needed manual per-book fixes the first time around, for a depth of
   hierarchy (3+ levels) most chunks likely don't even have.
2. **Hierarchy-prefixing the exam collections too** — rejected: would blur
   the near-duplicate match those collections are tuned for, and the app
   already has a working, deliberate path (`EsslceTopicLink`) for attaching
   unit context to exam questions without touching their embedded text.
3. **True multi-level/RAPTOR-style index** (LLM-generated unit/section
   summaries embedded as their own documents, two-stage retrieval: find the
   unit, then search within it) — considered, not pursued now. It needs
   extra LLM calls (cost against the already-constrained free-tier Groq
   budget per `[[esh_exams_answer_resolution_gap]]`) and more moving parts,
   for a corpus size (tens of thousands of chunks, not millions) that
   doesn't obviously need two-stage retrieval yet. A deterministic
   metadata-based prefix captures most of the benefit far more cheaply.
   Worth revisiting if retrieval quality still falls short after this round.

## Implementation

### 1. Shared embeddings provider — `retriever/builder.py`

- Replace the commented-out block with a small wrapper around
  `GoogleGenerativeAIEmbeddings` that overrides `embed_documents`/
  `embed_query` to pass `task_type="RETRIEVAL_DOCUMENT"` /
  `"RETRIEVAL_QUERY"` respectively. Confirmed by reading `langchain_postgres`
  source: `PGVector.add_texts` calls `self.embedding_function.embed_documents(...)`
  and `similarity_search_with_score` calls `self.embeddings.embed_query(...)`
  — so this one wrapper, used as `self.embeddings` in `RetrieverBuilder`,
  transparently benefits every existing caller (ingestion, `/explain`,
  `/notes`, exam cache, exam topic-linking) with no caller-side change.
- Delete the `HuggingFaceEmbeddings` line entirely — no dual-mode flag.
- Drop `torch`, `torchvision`, `transformers`, `sentence-transformers` from
  `backend/requirements.txt` (confirmed nothing else in the serving path
  imports them; only stale Chroma-era debug scripts like `debug_retrieval.py`
  and `audit_ingestion.py` still reference the retired local Chroma store
  directly — already broken by the earlier pgvector migration, unrelated to
  this change, flagged here but left alone unless you want them fixed too).

### 2. Textbook hierarchy prefix — `ingestion/textbook_ingest.py`

- Add a helper, e.g. `_embed_text(grade, subject, unit, section, text) -> str`,
  building a short header before the chunk text:
  `"{subject label}, Grade {grade}\n{unit}" + (" > {section}" if section else "") + "\n\n{text}"`.
- Use its output — not the raw chunk text — as the string passed to
  `vector_texts` in `ingest_all()`. This string becomes both the embedding
  input *and* the stored/retrieved document content (that's how `add_texts`
  already works: one string serves both roles).
- `Chunk.text_excerpt` (the DB column used for citations) stays built from
  the original unprefixed `text[:280]`, unchanged — students never see the
  structural header, only retrieval sees it.

### 3. Re-embedding migration script — new `backend/scripts/reembed_vectors.py`

Modeled on the existing `scripts/migrate_vectors_to_pgvector.py` (same
read-the-old-store, batch-write-the-new-store shape) and reusing the
retry/backoff batching already written as `_add_in_batches` in
`ingestion/textbook_ingest.py` (move it to `retriever/vectorstore.py` so both
the ingestion script and this new one share it, instead of duplicating it).

For each of the three collections (`textbooks`, `exam_questions`,
`esslce_exams`):
- Read every row's `(id, document, cmetadata)` directly from
  `langchain_pg_embedding` joined to `langchain_pg_collection` (same join
  `vectorstore.collection_count()` already uses), batched into memory.
- `textbooks`: rebuild the embedded text via the new `_embed_text()` helper,
  using each row's own stored `unit`/`section` metadata.
- `exam_questions` / `esslce_exams`: reuse the stored `document` text
  verbatim — only the model changes, not the text.
- Delete all rows for that collection, then re-add through
  `RetrieverBuilder().embeddings` (now Gemini) in small batches via the
  shared retry helper.
- `--dry-run` flag (counts only, no writes), matching the existing script's
  convention.
- Note: Gemini's free tier doesn't support the Batch API, so this runs
  through the regular per-call embedding endpoint at whatever RPM the
  account allows — expect it to take a while for the full textbook
  collection; the retry/backoff loop already handles rate-limit errors.
- First verification step inside the script, before any writes: confirm the
  pgvector `embedding` column was created without a fixed dimension
  (`Vector(None)` in the installed `langchain_postgres`, confirmed from
  source) so switching to Gemini's larger output dimensionality doesn't need
  a schema change.

### 4. Exam question provenance — `api/routes_esslce.py`

- Add `year_ec: int | None` and `booklet_code: str | None` to
  `EsslceQuestionOut` and `MistakeItem` (both fields already exist on
  `EsslcePaper`, just never surfaced in these response schemas).
- Populate both from `q.paper.year_ec` / `q.paper.booklet_code` in
  `_build_outputs()` — the single shared builder every `EsslceQuestionOut`
  already funnels through — and in the `mistakes()` endpoint's own
  `MistakeItem` construction.

## Verification

- Re-run the RSS import probe (same technique used to measure the current
  ~800MB) after the `requirements.txt` change, to directly confirm the app
  now fits comfortably under Render's 512MB free tier instead of assuming it.
- Dry-run the migration script on the smallest collection first
  (`exam_questions`), then `esslce_exams`, then the larger `textbooks`
  collection.
- Spot-check retrieval before/after on a handful of known `/explain` queries
  and `/notes` unit queries — compare which chunks come back. No labeled
  retrieval eval set exists for this project, so this is a judgment-call
  comparison, not a pass/fail test.
- Run the existing backend test suite (`backend/test/test_esslce_route.py`
  and friends) to catch regressions from the schema/response changes.
- Add a direct-route test for the new `year_ec`/`booklet_code` fields,
  matching this project's existing test convention (in-memory SQLite,
  `TestClient`, `dependency_overrides`).
