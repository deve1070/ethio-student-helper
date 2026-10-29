# PWA feature build-out: Progress, Study Plan, Notes, Mistake Tracker, richer onboarding, tiers

## Context

The user supplied 19 reference design mockups (`frontend/pages/*.png`, excluding Community, Parent Dashboard, and Offline, which are explicitly out of scope) showing a much richer feature set than the PWA built so far, and asked for all of it, step by step, with me choosing the build order. Three decisions are already settled:

- **Design direction**: adapted, not literal. Keep the existing teal/amber brand, system fonts, and Lucide icons; adopt the mockups' richer per-subject/per-status color-coding and data visualization (rings, trend lines, mastery bars, stat tiles) — but drop the cursive-script banners and emoji-headline chrome, which are the "looks AI-generated" tells the user originally asked to avoid.
- **Payments**: Subscription tiers (Free / Premium / Exam Season Package) are built, but payment stays Telebirr/CBE manual receipt + admin approval (see `[[esh_payments_manual_receipt]]`) — no Chapa or card gateways, since the business-registration docs for those were never obtained.
- **Admin panel**: out of scope for this round. Admin review stays on the Telegram bot.

Stream mapping (needed by onboarding, subject pickers, and the Study Plan) was clarified directly by the user and saved to `[[esh_stream_subject_mapping]]`: Biology/Chemistry/Physics are natural-only, Economics/Geography/History are social-only, English/SAT are common to both, and Math is common only for exam years after 2016 EC (stream-split before that, already modeled as `EsslcePaper.stream`).

## What already exists and will be reused, not rebuilt

Exploration found the hard part of the two biggest features already solved:

- `practice/selection.py:unit_progress()` — pure function, per-unit accuracy + weak/strong level, already used by both `GET /v1/practice/progress` and (via `exams/store.py:student_progress`/`recommend_focus`) `GET /v1/esslce/progress`. The Progress Dashboard's "Topic Mastery" and "Weak Areas" sections are a frontend job, not a new backend algorithm.
- `exams/store.py:get_or_create_elaboration` — the exact cache-on-first-request pattern (LLM call only once per question, served from a DB row after) that Study Notes should reuse for topic-level content.
- `exams/latex_render.py:render_latex_png` — already renders calculation-subject explanations as images; reused as-is wherever Study Notes or Mistake Review show a formula.
- `db/models.py:Subscription` — a `plan`/`status`/`current_period_end` table already exists, unused. Subscription tiers hook into this instead of new schema.
- `User` has no `stream`, `exam_date`, `daily_goal_minutes`, or `subjects_selected` today — genuinely new columns, not a gap in reuse.

## Build order (my call, as asked) and why

1. **Progress/Analytics Dashboard** — highest value-to-effort ratio: nothing like it exists today, and 90% of the backend logic (unit accuracy, weak areas, recommendation) is already live. Only new backend work: a trend-over-time and a study-streak aggregation (both pure functions over existing `QuizAttempt`/`EsslceAttempt` timestamps, no new tables).
2. **Mock-exam Question Navigator + Mistake Review/Weakness Tracker** — mostly a frontend rework (exam mode already fetches all paper questions via `paper_id`; the navigator just needs to stop serving them one-at-a-time and track local jump/flag state) plus one new "list my wrong attempts" query endpoint per system. Natural follow-on to #1 since it shares the same accuracy data.
3. **Richer onboarding** (stream, subject selection, exam date, daily goal) — the one schema migration everything after it depends on (`stream`, `exam_date`, `daily_goal_minutes`, `subjects_selected` on `User`).
4. **Study Plan / Exam Countdown** — depends on #3's new fields and #1's weak-area data; the actual "plan" is computed fresh on each request from current weak units + days-remaining, not a long-lived stored calendar (see Design Decisions below).
5. **Study Notes & Formula Sheets** — depends on nothing above, could move earlier, but is placed after the analytics/plan features since it's the one net-new content type and benefits from the `get_or_create_elaboration` pattern being fresh in mind.
6. **Subscription tiers UI** — lowest urgency (no student is blocked by its absence today); last.

## Design decisions flagged for confirmation

- **Mistake Tracker's "why you missed it" classification** (concept not clear / calculation error / careless, shown in the mockup): recommend **skipping this for v1**. Classifying it reliably needs either an LLM call per wrong answer (real cost, and today's Groq daily-token-cap pain argues against adding more per-answer LLM calls) or an unreliable heuristic. The tracker still shows the wrong answer, correct answer, stored explanation, and a "try a similar question" action (reusing `/next` with a unit filter) — just without the classified reason tag. Can be added later as its own scoped feature.
- **Study Plan generation**: recommend **computed-on-demand**, not a persisted 12-week calendar. Each "Today's Plan" request derives 1–2 weak units (from the existing progress endpoints) + a practice block sized to `daily_goal_minutes`, computed fresh every time. Avoids a plan silently going stale as the student's weak areas shift, and avoids a new table of long-lived plan rows. A small new table is still needed for the daily checklist's "done" checkboxes (so completing today's items persists), but the plan *content* itself is never stored.
- **Study Notes sourcing**: recommend **LLM-generated on first request per (subject, unit), cached after** — identical pattern to `get_or_create_elaboration`, reusing the same retriever + LLM client, rather than requiring someone to hand-author 40+ formula sheets.

## Verification

- Backend: a direct-route test per new/changed endpoint, matching the existing convention in `backend/test/test_esslce_route.py` (in-memory SQLite, `TestClient`, `dependency_overrides`).
- Frontend: extend the existing Playwright smoke-test pattern (`frontend/smoke_test.mjs`) to cover each new page, plus a manual screenshot review before calling any phase done (the standing rule this session has followed throughout).
- Each phase ships and is verified before the next starts — the user asked for step-by-step delivery, not a single big-bang merge.
