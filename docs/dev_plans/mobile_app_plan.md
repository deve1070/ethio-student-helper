# Mobile App: Decided Direction

Status: planning decisions locked in 2026-10-21. No mobile frontend code written yet - this
records direction, not an implementation log. Backend work it depends on (diagnostic test) has
already shipped as part of `backend/exams/`, independent of which frontend consumes it.

## Name

**Ethiopian Student Helper** - the existing name used across the repo and the live Telegram bot.
Considered switching to something ESSLCE-specific (the GPT mockup's placeholder was "ESSLCE
Prep") but decided to keep the existing broader name rather than introduce a second brand.

## Tech stack: PWA, not native

A Progressive Web App (installable via "Add to Home Screen", offline-capable via a service
worker), not a native or cross-platform-native app. Reasoning:
- Matches the actual target user (Ethiopian Grade-12 students on low-end Android phones,
  unreliable connectivity) without app-store friction or fees.
- No new backend - the PWA calls the exact same `/v1/esslce/*` and `/v1/auth/*` REST APIs the
  Telegram bot already uses. This is a new frontend, not a new backend.
- Consistent with this project's standing principle of not adding infrastructure before it's
  needed; if it validates with real users and Play Store presence becomes worth the cost later,
  most of the API-calling logic carries over to a React Native wrapper.

Proposed stack: React (or Next.js) + Tailwind (the GPT mockup's color palette translates
directly) + a service worker (Workbox or hand-rolled) for the offline scope decided below.

## Feature decisions (2026-10-21)

- **Payments**: Chapa will NOT be integrated (no TIN/business registration - see
  [[esh-payments-manual-receipt]]). Manual receipt + admin approval is the only payment path -
  **reconciled and built 2026-10-22**: `POST /v1/payments/submit-receipt` (vision-verified) +
  admin approval pushed to Telegram, `User.is_admin` role added. See
  [[esh-payments-manual-receipt]] for the full design.
- **AI Tutor**: single-shot explanation (matches `/v1/esslce/elaborate` as it already exists -
  grounded, cached per question, no conversation state). Explicitly NOT the free-form multi-turn
  chat the GPT mockup showed; that would need conversation history and materially more LLM cost
  per student and is out of scope for now.
- **Structured citations + citation-grounded deep elaborations: built 2026-10-21.** See below.
- **Ask-about-this-question chat: built 2026-10-21**, added after the original planning round -
  the user asked for free-form conversational follow-up per question, not just the single-shot
  elaboration. See below.
- **No Google sign-in.** Auth stays email/password (`routes_auth.py`) plus Telegram-link, both
  already built. No OAuth work.
- **Offline scope, deliberately narrow for v1**: cache already-fetched questions for offline
  viewing only. No offline answer submission, no sync/conflict-resolution protocol. The GPT
  mockup implied full offline practice with later sync - scoped down intentionally; that's a
  real feature (idempotent sync, conflict handling) not worth building before the core app is
  validated.
- **Diagnostic test: implemented.** See below.

## Diagnostic test (shipped 2026-10-21)

Backend:
- `exams/store.py`: `diagnostic_questions(db, subject, count=15, stream=None)` - stratified
  round-robin sampling across topic groups (`best_unit`, falling back to `skill_strand`, falling
  back to "uncategorized"), so a short diagnostic deliberately spans the subject's topic space
  instead of clustering in whatever the mastery-ordered mixed pool would pick. Does not exclude
  previously-attempted questions - this is a rough baseline, not a bias-controlled instrument.
- `api/routes_esslce.py`: `POST /v1/esslce/diagnostic` (subject, stream?, count=15) returns the
  fixed set in one shot, same `EsslceQuestionOut` shape as `/next`. `EsslceQuestionOut` gained a
  `skill` field alongside the existing `unit` field (populated via `skill_strand`), so the
  diagnostic result screen can show a topic label for English/SAT questions too.
  `AnswerRequest.mode` gained a third literal value, `"diagnostic"` (no DB migration needed -
  `EsslceAttempt.mode` is a plain `String(16)`, not a DB-level enum).

Telegram bot (`telegram_bot/esslce_flow.py`):
- Third top-level mode button, "📋 Take a Diagnostic Test", alongside practice/exam.
- Behaves like exam mode structurally (grading deferred to the end, `exam_results` accumulated
  per answer) but is NOT paper-scoped - it spans every year's papers via the stratified sample,
  so `on_next`'s empty-queue handling needed a dedicated diagnostic branch rather than falling
  into the mixed-pool refill.
- `_diagnostic_summary_screen()` deliberately does NOT claim a "weakest unit/skill"
  recommendation the way `_progress_screen` does for ongoing practice - a diagnostic spreads
  thin across many topics (often exactly 1 item per unit/skill), and `recommend_focus`'s own
  `MIN_ATTEMPTS_FOR_SIGNAL` threshold exists precisely because one question is never enough to
  call a topic weak. Shows the honest per-item breakdown and lets the student pick what to
  practice next themselves, rather than overclaiming from a thin sample.

Tests: `test_esslce_pipeline.py` (stratification across topic groups, pooling across multiple
papers of the same subject, no duplicates), `test_esslce_route.py` (`/diagnostic` endpoint
shape and 404 on a subject with no eligible questions). Full regression suite and bot build
pass as of this writing.

## Structured citations + richer elaboration (shipped 2026-10-21)

Backend:
- `db.models.Chunk.vector_id` (already existed, written once per chunk during textbook ingestion)
  is the exact join key between a Chroma retrieval hit's metadata and the Postgres `Chunk` row -
  `exams/store.py:_citation_for(db, vector_id)` resolves `{textbook, grade, subject,
  unit_or_chapter, section, page_start, page_end}` from it. A page number is never something the
  LLM states itself - it's always looked up deterministically from this join, same "verify before
  trust" principle as everywhere else in this pipeline.
- `EsslceElaboration.citation` (new JSON column) persists this alongside the cached explanation.
  NULL for a calculation-subject elaboration (no textbook excerpt) or a reading-comprehension
  question (grounded in the exam's own passage, not a textbook chunk).
- `ELABORATE_GROUNDED_PROMPT` rewritten to require: the underlying concept with an example, why
  the correct option is correct, and why each of the other three is specifically wrong (not just
  "it's wrong") - still gated by the same one-verified-quote requirement as before for the core
  concept; the right/wrong walkthrough reasons from that same grounded concept without needing
  its own separate quotes (demanding a verified quote for every distractor would fail almost
  everything, since textbooks explain concepts, not "why option C is wrong on this exam item").
- The 4 pre-existing cached elaborations (from earlier live testing) were cleared so the next
  request regenerates in the new format - cache data, not real user data, so no loss.
- `ElaborateResponse.citation` surfaces this to any client; the Telegram bot renders it as a
  deterministic "📖 Textbook, Grade N, Unit, Section, p.N" line appended after the LLM's prose,
  never woven into the LLM's own text.

## Ask-about-this-question chat (shipped 2026-10-21)

A genuinely different trust level from everything else in this pipeline, worth remembering:
- `POST /v1/esslce/ask` (`exams/store.py:ask_about_question`) is conversational and **never
  cached** - every message is a fresh LLM call, unlike `/elaborate`'s cache-once-per-question.
- Grounding is **prompt-level only**, not independently verified. The system prompt gives the
  model the question, options, correct answer, and the question's own (always-exists-first,
  auto-created via `get_or_create_elaboration`) explanation + citation, and instructs it to
  decline rather than invent when asked something outside that context - but unlike
  `quote_in_passage`'s hard verification gate used everywhere else (`solve_question`,
  `elaborate_grounded`), nothing here independently checks that the model actually followed that
  instruction. This is a real, deliberate trust-level step down from the rest of the pipeline,
  accepted because per-message quote verification isn't practical for open-ended dialogue.
- Client holds conversation history (capped at the last 12 messages in the bot session), resent
  each turn - the server itself keeps no conversation state between messages.
- Telegram integration required the bot's first-ever free-text `MessageHandler` (previously
  100% button-driven) - scoped by `EsslceSession.asking_question_id`; any text when that's unset
  is silently ignored, never treated as an error, since the handler can't know whether some other
  feature might claim it instead.

## Still open

- Actual PWA frontend has not been started - this plan is the agreed direction, not code.
- Payments: `CREDIT_BUNDLES` pricing is still a placeholder, and the Telebirr recipient number in
  the bot's `/buy` instructions is a literal `09XXXXXXXX` placeholder - needs the real number
  before this goes live. No admin has linked their Telegram account yet (is_admin was set directly
  in the DB, not via the bot's own login), so the push-to-admin notification has nowhere to send
  until that happens once.
- Cost exposure: `/ask` is uncached and can be used repeatedly per question - no per-user rate
  limit or cost cap built yet beyond the project-wide slowapi default. Worth a decision once
  pricing is revisited (explicitly deferred earlier in the project).
