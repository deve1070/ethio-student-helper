# ESSLCE exam pipeline: AI-derived answers, per-unit vector metadata, exam stats

## Context

`backend/exams/` is the Grade-12 ESSLCE past-national-exam pipeline (`extract -> load -> key -> approve -> link -> unit -> minutes -> index`), already built and tested (`backend/test/test_esslce_pipeline.py`). EAES declined to provide official papers or answer keys, so every past-exam question needs an AI-proposed answer that a human then reviews — the pipeline currently has no path for this at all (`answer_source` only supports `"official_key"` or `"manual"`). Separately, the user wants the exam vector index to carry per-unit metadata (so retrieval can eventually be filtered "practice this unit's exam questions"), and deterministic statistics on which units are most heavily tested across loaded papers/years.

A separate, earlier script (`backend/ingestion/exam_paper_ingest.py`) attempted AI-answer-resolution for past exams, but wrote into the unrelated `QuizQuestion` table (confirmed a different, separate system — `QuizQuestion` is for self-generated grade 9-12 practice, not grade-12 national exam prep) and is stale (it references `QuizQuestion` columns that don't exist in the current schema). Its grounding + quote-verification logic is being ported into `backend/exams/store.py`, after which the script is deleted.

Scope for this round (confirmed with the user): extend the `backend/exams/` pipeline and its CLI only. No new student-facing serving/practice API (that needs its own attempt-tracking design, deferred). `QuizQuestion`/`routes_practice.py` and `ExamQuestion`/`ExamCache`/`routes_exam.py` (the crowdsourced solve-and-cache flow) are untouched — confirmed separate systems.

## 0. Paper identity: region, delivery mode, booklet code (confirmed with user)

Real content in `backend/exams/content/` surfaced three identity questions beyond the original plan:

- **Only genuine official EAES exams enter this pipeline.** Third-party "model exam"/mock content (Telegram-channel practice papers mimicking the format) is excluded — the user manually curates which source files are official before they ever reach `extract`. No `source_kind`/provenance-tagging field is needed in the schema, and the pipeline does not cite/store where a file came from beyond the existing internal `source_file`/`source_sha256` (bookkeeping only, never shown to students).
- **Region is a real, occasional identity dimension.** EAES sometimes administers a region-specific sitting (e.g. a 2016 Tigray paper) distinct from the national paper for the same subject/year — not every year. Add `region = Column(String(32), nullable=False, default="")` to `EsslcePaper` (`""` = national, e.g. `"tigray"` otherwise), and include it in the identity/unique constraint.
- **Delivery mode is a real, occasional identity dimension.** 2018 introduced an "Online Exam" variant alongside the paper-based one for the same subject/year/round. Add `delivery_mode = Column(String(16), nullable=False, default="")` to `EsslcePaper` (`""` = paper, `"online"` otherwise), included in the identity/unique constraint.
- **Booklet code is NOT part of identity.** Confirmed: different booklet codes for the same official sitting are the same questions with shuffled option/question order (anti-cheating), not different content. `booklet_code` stays exactly as it is today — plain metadata on whichever single paper row gets loaded, not part of `uq_exam_paper`. Just clarify this in its column comment so it's not mistaken for a disambiguator later.

**`EsslcePaper.__table_args__` unique constraint becomes:**
`UniqueConstraint("subject", "stream", "year_ec", "round", "region", "delivery_mode", name="uq_exam_paper")`

**Everywhere a paper is identified by `(subject, stream, year_ec, round)` needs the two new fields threaded through, defaulting to `""` so existing data/behavior is unaffected:**
- `store.find_paper(db, subject, year_ec, stream="", round_="", region="", delivery_mode="")` — filter + the "N papers match" disambiguation message.
- `store.load_paper`'s existing-paper lookup filter (the `existing = db.query(EsslcePaper).filter(...)` block).
- `cli.py`'s `_paper_args(p)` — add `--region` and `--delivery-mode` (both default `""`), applied to every subcommand that already takes `--stream`/`--round` (`key`, `approve`, `unit`, `minutes`, `link`, `index`, and the new `solve`/`stats`).
- `extract.py`'s `run_extract` meta dict and `paper_dirname()` — `paper_dirname` currently joins `(subject, year_ec, stream, round_)`; extend to also join `region`/`delivery_mode` so distinct papers don't collide in the output folder name, e.g. `mathematics_2018_online` or `physics_2016_tigray`.
- `cli.py`'s `extract` subcommand gets matching `--region`/`--delivery-mode` flags, threaded into the `extract` meta dict alongside the existing `--stream`/`--round`.

**Folder structure / naming schema for `backend/exams/content/` (organizational convention, agreed with the user, not enforced by code):**

```
backend/exams/content/
  natural/<subject>/     # natural-stream-only or natural-stream-specific papers (biology, chemistry, physics, mathematics pre-2017 NS, ...)
  social/<subject>/      # social-stream-only or social-stream-specific papers (economics, geography, mathematics pre-2017 SS, ...)
  common/<subject>/      # no stream split: aptitude, english, mathematics 2017 onward
```

Mathematics pre-2017 was streamed (appears under both `natural/mathematics/` and `social/mathematics/` for those years); from 2017 onward it has one common paper (`common/mathematics/`).

Every paper is **one PDF file** (phone-photographed pages get combined into a single PDF before being placed here, not left as a loose folder of images), named, all lowercase:

`<subject>_<year_ec>_<year_gc>_<round?>_<online?>_<region?>_esslce.pdf`

Qualifier tokens (`round1`/`round2`, `online`, a region name like `tigray`) are each included only when they actually apply - omitted entirely otherwise, not written as a placeholder. "ESSLCE" is used uniformly regardless of what an old paper's cover actually printed (EAES's current name for the exam, not an era label - no "UEE" variant in the naming).

Examples: `content/common/mathematics/mathematics_2018_2026_esslce.pdf` (no qualifiers); `content/natural/physics/physics_2016_2024_tigray_esslce.pdf` (regional variant).

This is curation guidance for sorting the existing messy `content/` tree (which currently mixes official papers with excluded mock-exam files, loose photo pages at the root, and an oddly-named `2014-2018_enterance_exams/` subtree) - not something this plan automates. Path-based auto-inference of `--subject`/`--year-ec`/etc. from the folder/filename is a nice-to-have, explicitly not built in this round unless requested separately.

## 1. `backend/exams/models.py`

- Add `supporting_quote = Column(Text)` to `EsslceQuestion` — stores the AI's verbatim cited quote so a human reviewer can check it against the source photo/textbook (mirrors `QuizQuestion.supporting_quote` in the practice engine).
- Update the `answer_source` comment to document the new value: `"official_key" | "manual" | "ai_derived"` (no column type change, it's already a free-text `String(32)`).
- This needs a manual `ALTER TABLE esslce_questions ADD COLUMN supporting_quote TEXT;` against any already-created Postgres DB — `create-tables` only creates missing tables, it does not alter existing ones. **Confirm before running this against the real DB.**
- Similarly, `region`/`delivery_mode` on `EsslcePaper` and the updated `uq_exam_paper` constraint need `ALTER TABLE esslce_papers ADD COLUMN region VARCHAR(32) NOT NULL DEFAULT ''`, `ADD COLUMN delivery_mode VARCHAR(16) NOT NULL DEFAULT ''`, then drop and recreate `uq_exam_paper` with the two new columns — only relevant if `esslce_papers` already exists in the real DB (per the project's dev-database state, likely safe to drop/recreate since nothing real is at stake yet, but will confirm before running).

## 2. `backend/exams/store.py` — AI-answer-resolution

- `solve_query(q)`: reuses `link_query(q)`'s stem/section/options-based query text.
- `solve_question(llm, tb_store, paper, q, grades=(9,10,11,12), k=6) -> dict`: ports the retired script's `SOLVE_PROMPT` + grounding pattern. Calls the already-existing `retrieve_cross_grade(tb_store, solve_query(q), paper.subject, grades, final_k=k)`, asks the LLM for `{answer_index, source_index, explanation, supporting_quote}` (or `-1` if unconfident — never guess), and trusts the result only if `practice.validate.quote_in_passage(quote, cited_excerpt.page_content)` passes (reusing the same fuzzy-substring check the practice engine already uses — not reimplemented).
- `solve_paper(db, paper, llm, tb_store, grades=(9,10,11,12), log=print) -> dict`: iterates `paper.questions`, **never overwrites** a question whose `answer_source` is already `"official_key"` or `"manual"`. For the rest, calls `solve_question`; on a confident result writes `answer_index/explanation/supporting_quote/answer_source="ai_derived"`. If the question was previously `approved` and the new answer differs, withdraws approval exactly like `attach_key` already does (`review_status -> "needs_review"`, `reviewed_by/reviewed_at -> None`, reported in the return value). Never auto-approves — the existing `approve` step still gates every question before a student can see it.
- `unit_stats(db, subject=None) -> list[dict]`: deterministic aggregation (no LLM call), reusing `best_unit(q)` per question across all loaded papers (optionally filtered by subject). One dict per `(subject, grade, unit)`: `all_count`, `approved_count`, `years` (sorted distinct `year_ec`), `verified` (human-set vs. suggested unit), sorted by `all_count` descending. Plain Python/ORM aggregation — consistent with the project's "deterministic computation, LLM narration only" rule; no LLM involved in computing these numbers.

## 3. `backend/exams/cli.py`

- New `solve` subcommand: same `_paper_args` shape as `link`/`approve`, `--grades` (default `9,10,11,12`), reuses the existing Chroma-textbook wiring from the `link` branch. Prints a one-line summary matching the terse style of `key`/`approve`.
- New `stats` subcommand: optional `--subject`, prints `unit_stats` rows like the existing `status` command.
- Update the module docstring's command list to include `solve` (between `key` and `approve`) and `stats` (near `status`).

## 4. `index_questions` metadata enrichment (`store.py`)

- Compute `best_unit(q)` once per row; add `grade`/`unit` to the metadata dict **only when `best_unit(q)` is not `None`** (Chroma rejects `None` metadata values — omit the keys entirely rather than passing `None`).
- `embed_text` itself is **not** touched — it stays question-wording-only. This is intentional (confirmed by an existing test assertion: `"ESSLCE" not in text and "2016" not in text`) so a student's own typed/photographed question still matches by wording, not by paper metadata.

## 5. `backend/config/constants.py`

- Add `EXAM_COLLECTION_NAME: str = "esslce_exams"` next to `TEXTBOOK_COLLECTION_NAME`/`EXAM_CACHE_COLLECTION_NAME` (it was referenced via a `getattr(..., fallback)` in `cli.py` but never actually defined).
- In `cli.py`, remove the now-redundant `DEFAULT_COLLECTION` constant and the `getattr` fallback — use `constants.EXAM_COLLECTION_NAME` directly.

## 6. `backend/test/test_esslce_pipeline.py`

Extend the existing flat, assert-based test (no pytest, fake vision/Chroma stand-ins already defined) with:
- A fake-LLM stand-in for `solve_question`, covering: a confident resolution that passes quote verification, an unconfident (`-1`) response, and a fabricated-quote case `quote_in_passage` correctly rejects.
- Approval-withdrawal symmetry: solving a question whose new `ai_derived` answer differs from a previously-approved one withdraws approval (same shape as the existing `attach_key` withdrawal assertion).
- Never-overwrite guarantee: a question with `answer_source in ("official_key", "manual")` is untouched by `solve_paper`.
- Extended `index_questions` assertions: metadata includes `grade`/`unit` for a linked+unit-set question, and omits those keys (not `None`) when no unit is resolved yet.
- New `unit_stats`/`stats` CLI assertions using the existing `BOOKS`/`FakeTextbooks` fixtures.
- Add `EXAM_COLLECTION_NAME` to the test's `config.constants` stub.

## 6b. Calculation subjects: code-executed derivation (added after the real smoke test)

`solve_question`'s textbook-grounding + quote-verification has nothing to verify against for a *derived*
answer like "(2f-g)(-2) = ?" - there's no textbook sentence to quote. For `CALCULATION_SUBJECTS =
{"mathematics", "physics", "chemistry"}` (chemistry is mixed - confirmed in conversation, "to some extent" -
so it falls back to grounding when a question isn't actually computational), `solve_question` tries
`solve_question_calculation` FIRST:

- The LLM writes a full step-by-step LaTeX solution (`explanation`, shown to students) plus independent
  verification code (`sympy`/`math`/`fractions` only).
- That code is actually EXECUTED in a separate process (`run_verification_code`) - never trusted on the
  LLM's say-so, never `exec()`'d in-process. A static AST allowlist check (`_code_is_safe`) runs first,
  rejecting anything importing outside `sympy`/`math`/`fractions` or referencing file/process/network/
  introspection primitives (`open`, `os`, `subprocess`, `getattr`, etc.) before any execution is attempted.
  The subprocess itself also gets a wall-clock timeout, CPU/memory `resource` limits, and a cleared
  environment (defense in depth, not a full container sandbox - proportionate to a verification helper
  whose only job is checking arithmetic, not a full code-execution product).
- The answer is only accepted if the executed result matches the *printed option text* at the claimed
  index (`_results_match` - exact normalized-string match, falling back to a `sympy` symbolic-equality
  check). This is deliberately stronger than code-execution alone: a flawed derivation landing exactly on
  one of four specific printed numbers by coincidence is unlikely.
- New `EsslceQuestion` columns `verification_code`/`verification_output` let a human reviewer see exactly
  what was run and what it printed, same transparency principle as `supporting_quote`.
- Explicitly not built: a multi-sample self-consistency check (re-deriving 2-3x and requiring agreement) -
  the exact-match-to-option constraint already substantially guards against the same failure mode, and
  this project's principle is to not build for a gap that hasn't actually been demonstrated.

## 7. Delete `backend/ingestion/exam_paper_ingest.py`

No importers anywhere in the repo (confirmed). Delete once its grounding/quote-verification logic is ported per step 2.

## Alternatives considered

- **Keep `backend/ingestion/exam_paper_ingest.py` and extend it instead of `backend/exams/`.** Rejected: it writes into `QuizQuestion`, which is confirmed to be a different system (self-test practice, not grade-12 exam prep); it also silently drops any question that can't be matched to a textbook chunk, and lacks passages, human transcription review, and mock-exam timing that `backend/exams/` already has.
- **Have `solve` consume the textual passages already fetched by `link_topics`/`EsslceTopicLink` instead of doing its own retrieval.** Rejected: `EsslceTopicLink` stores only metadata (textbook_id/vector_id/unit/section) and a distance score, not the actual passage text — reusing it would require a second fetch by `vector_id` anyway, with no real savings over calling `retrieve_cross_grade` directly, and it would force `link` to run before `solve` instead of each CLI step being independently runnable.
- **Build the student-facing "practice by unit" serving endpoint now, in the same pass.** Deferred — it needs its own attempt-tracking design (akin to `QuizAttempt`) and is a materially larger task; the user confirmed this round is pipeline + stats only.

## Verification

- `python test/test_esslce_pipeline.py` from `backend/` (SQLite in-memory, no real API calls) — must pass including the new assertions.
- Manual smoke test on real content: pick **one** real paper folder under `backend/exams/content/`, run `extract -> load -> solve -> link -> index -> stats` against it with a real Groq vision model id, and show the `review.txt`/`status`/`stats` output. Confirm before any step writes to the real Postgres DB or Chroma store, and before running the `ALTER TABLE` for `supporting_quote`.
