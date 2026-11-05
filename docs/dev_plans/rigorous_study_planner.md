# Rigorous multi-day study planner

## Context

The existing `/v1/study-plan/today` feature (`studyplan/plan.py`,
`db/models_studyplan.py`, `api/routes_studyplan.py`) is a thin daily
task-picker: it finds the single weakest QuizQuestion-practice unit and the
single weakest ESSLCE unit/skill, splits the student's daily time budget
evenly between them plus a flexible "ask anything" slot, caches that list
for the rest of the calendar day, and regenerates fresh (with no memory of
what came before) the next day. Confirmed directly in the code
(`routes_studyplan.py`, `plan.py`):

- **`User.exam_date` is never read anywhere in `studyplan/` or
  `api/routes_studyplan.py`**, even though it already exists on the `User`
  model and is already collected at onboarding for Grade 12 students
  (`frontend/.../OnboardingPage.tsx`'s `examDate` step) and editable from
  `Profile.tsx` via `PATCH /v1/auth/me`. A planner that never asks "how many
  days are actually left" cannot be realistic.
- There is no multi-day horizon at all - "today's plan" has no relationship
  to tomorrow's, so there's no way to pace coverage of a subject's full
  curriculum against the exam date.
- There is no curriculum-coverage signal - the planner only ever reacts to
  practice/ESSLCE *attempt* history, so a unit the student has never
  touched at all looks identical to one they've mastered (both have zero
  "weak" signal), and nothing ever surfaces "you haven't started Grade 10
  Chemistry yet."
- Real ESSLCE-paper test-weight (`exams/store.py`'s `unit_stats` - which
  units past papers actually test most) is computed today for admin
  surfacing only and never feeds the student's plan.

The user asked for this feature to be rebuilt "rigorously, realistically,
helpfully" and explicitly invited a multi-agent design (a user-profile
agent, exam-profile agent, book-profile agent, planner agent, "so on"),
while giving full latitude on the actual architecture ("don't limit by what
I said... give the app high value"). Confirmed directly with the user: the
LLM's role stays limited to explaining and motivating an already-computed
schedule, never to choosing the schedule itself.

## Alternatives considered

1. **Pure deterministic scheduler, no LLM at all.** Simplest, fastest,
   free, and fully testable/predictable. But a purely rule-based allocator
   can't explain *why* a given day looks the way it does, or communicate
   trade-offs ("13 units left, 9 days - here's what we're prioritizing and
   why") in language a student finds motivating - the "helpful" half of the
   request suffers.
2. **Literal multi-agent pipeline** (mirroring `agents/workflow.py`'s
   LangGraph `StateGraph`): a real LLM-calling "UserProfileAgent",
   "ExamProfileAgent", "BookProfileAgent" each doing their own reasoning
   step, composed into a graph, as the user's own phrasing suggests. Rejected:
   profile/exam/curriculum data all already lives in Postgres and needs zero
   reasoning to retrieve - it's a SQL query. `agents/workflow.py`'s own real
   agents (`RelevanceChecker`, `ResearchAgent`, `CitationAgent`,
   `VerificationAgent`) are never used for raw data retrieval, only for
   steps that are inherently language-judgment (is this relevant? does this
   answer match? is this citation real?). Wrapping a DB query in an LLM
   call here would add latency, cost, and a new failure mode (hallucinated
   counts) for zero benefit, and risks exactly the kind of production
   memory pressure already fought hard this session, for no real gain.
3. **Hybrid: deterministic profile/allocation + one grounded LLM step for
   trade-off judgment and communication, checked afterward - CHOSEN.**
   All data-gathering and the actual day-by-day minute allocation stay
   plain Python (reliable, free, instant, testable). A single LLM call -
   reusing the existing `LLMClient`/`parse_json_object` contract - is fed
   ONLY the already-computed, structured weekly schedule and profile
   summary (never raw DB rows) and asked for two things no rule can do
   well: (a) a one-line rationale per day ("why this, why now"), and (b) a
   short weekly motivational framing. Its job is explanation and
   encouragement, never arithmetic or fact invention - the same grounding
   discipline every other LLM prompt in this app already follows (elaborate,
   notes, exam answers: only ever explain facts handed to it, never invent
   new ones). A deterministic check afterward discards any day-rationale
   that names a subject/unit NOT actually in that day's task list, mirroring
   the existing cross-check/verification pattern in `exams/store.py`
   (`solve_question_crosschecked`) rather than trusting LLM output blindly.

   This keeps the "agent" framing the user suggested, but splits work along
   the line this codebase already uses elsewhere: an "agent" is a reasoning
   step, not a rebranded data fetch.

## Design

### 1. Deterministic profile layer - `studyplan/profile.py` (new)

Pure functions, reusing existing queries rather than re-deriving them
(`db` passed in, no new query logic duplicated):

- **Exam profile**: `days_remaining = (user.exam_date - today).days` if set,
  else `None` (a student who hasn't set one yet gets a rolling 7-day plan
  with no countdown framing, not a crash or a guessed date).
- **Required subjects**: cross `user.subjects_selected` against
  `config.constants.NATURAL_ONLY_SUBJECTS` / `SOCIAL_ONLY_SUBJECTS` /
  `COMMON_SUBJECTS`, filtered by `user.stream` (both already on `User`,
  already collected at onboarding for grades 11-12 - see
  `esh_stream_subject_mapping` memory, now literally encoded in
  `config/constants.py`). Flags any stream-required subject **missing**
  from `subjects_selected` as a real, surfaced gap (e.g. a natural-science
  student who never added Chemistry) - new, since nothing today cross-checks
  this.
- **Curriculum coverage ("book profile")**: for each required subject, the
  full set of units across every grade up to the student's own
  (`notes.store.available_units(db, g, subject)` for `g` in
  `config.constants.SUPPORTED_GRADES` where `g <= user.grade_level` - ESSLCE
  is cumulative across grades 9-12). A unit counts as "touched" if the
  student has >=1 attempt on it in either system (`practice.progress.
  attempt_rows`, `exams.store.student_progress`) **or** has viewed its
  Study Note (new signal, see below) - "untouched" otherwise. Produces a
  `coverage_ratio` per subject.
- **Weak areas**: per subject, every unit/skill crossing
  `exams.store.MIN_ATTEMPTS_FOR_SIGNAL`, not just the single global weakest
  - `practice/progress.py` gets a new `weak_units_across_subjects(db,
  user_id, grade, subjects) -> list[(subject, unit, accuracy)]` (the full
  list), and the existing `weakest_unit_across_subjects` becomes a one-line
  wrapper (`min(...)` over the new function) so there's exactly one real
  query, not two - satisfies "migrate callers, don't fork logic." ESSLCE
  side reuses `exams.store.student_progress` directly (it already returns
  every unit/skill row; `recommend_focus` stays as-is for its current
  single-best use, the profile layer just also reads the full list itself).

### 2. New per-user "note viewed" signal

`notes/models.py` gets a new `StudyNoteView` table (`user_id`, `grade`,
`subject`, `unit`, `first_viewed_at`, unique on the first three) - the
existing `StudyNote` row is a GLOBAL cache (first requester pays the LLM
call, shared for everyone, per `notes/models.py`'s own docstring), so there
is currently **no** record of which individual student has actually opened
a given note. `api/routes_notes.py`'s `/note` endpoint records one
(idempotent upsert) whenever it successfully serves a note to an
authenticated user (it already requires `get_current_user` - trivial,
cheap addition, one insert). This is a genuine shared-infrastructure gap
the planning feature exposes (coverage can't be told apart from "never
opened the material") - fixing it here benefits any future feature that
wants "has this student studied X," not just the planner.

### 3. Fix `exams/store.py`'s `unit_stats` before a new caller touches it

`unit_stats` currently loads full `EsslcePaper.questions` ORM objects per
paper to count them - the exact N+1 full-materialization pattern already
diagnosed and fixed this session in `eligible_units`/`eligible_skill_strands`/
`diagnostic_questions` (same file), because materializing every question of
a large subject (confirmed: biology/chemistry have hundreds) was enough to
OOM-kill the single Render worker. The new planner is about to become a
second caller of this exact function to get ESSLCE test-weight per unit
(see below) - per CLAUDE.md, this is "fix shared infrastructure for the
expanded scope," not route around it. Rewrite `unit_stats` to use the same
`eligible_filter()` + lightweight-column-query pattern as its siblings
(join `EsslceTopicLink` for `best_unit`'s inputs, aggregate counts/years via
SQL, never load `stem`/`options`/`explanation`/`verification_code`).

### 4. Multi-day allocator - `studyplan/planner.py` (new, replaces `plan.py`)

Deterministic. Horizon = `min(days_remaining, 14)` if an exam date is set
(re-planned weekly so it's never far stale), else a fixed rolling 7 days.
For each required subject, a **need score** combines: uncovered-unit count
(from the book profile), weak-area severity (low accuracy, enough
attempts), and ESSLCE test-weight (`unit_stats`, now cheap). Each day gets
2-3 required task slots (same `MIN_MINUTES_PER_TASK=15` floor as today)
drawn from whichever subject most needs attention that day, rotating so no
single subject monopolizes the whole week, plus the existing always-present
flexible "ask anything" slot. If the total estimated minutes needed to
touch every uncovered unit at least once exceeds what the remaining days at
the student's own daily pace can fit, the allocator sets an explicit
`"realistic": false` flag with the shortfall, rather than silently
producing a plan that looks complete but isn't - prioritizing by test-weight
when trade-offs are forced. `TaskCandidate`'s shape carries forward as the
per-task dict shape (kind/label/subject/unit/skill/minutes/done), so the
frontend's existing task-rendering (`Dashboard.tsx`'s `taskHref`) needs no
rework, just a new source.

### 5. Grounded LLM step - `studyplan/coach.py` (new)

One `LLMClient` call per plan generation (not per day), given only the
already-built week's task list + profile summary as compact JSON, asked for
a `rationale` string per day and one `weekly_note` string. Parsed via the
existing `parse_json_object`. A deterministic post-filter drops any
day-rationale mentioning a subject/unit not actually scheduled that day
(cheap substring check) - never trust-without-check, consistent with
`exams/store.py`'s existing cross-check philosophy. On any LLM failure
(rate limit, parse failure), the plan is still served with the deterministic
schedule and no rationale text, never a 500 - same degrade-gracefully
pattern as `notes/store.py`'s `generate_note`.

### 6. Storage - `StudyPlanWeek` replaces `StudyPlanDay`

New model (`db/models_studyplan.py`, rewritten): unique on
`(user_id, week_start_date)`, JSON `days` (list of 7 day-dicts, each with
its own `tasks` list in today's existing per-task shape), JSON
`profile_snapshot` (the inputs the plan was built from), `rationale`/
`weekly_note` text columns, `created_at`. Regenerated once per
`(user, week_start_date)` like today's daily cache, but ALSO regenerated
early if `exam_date`/`stream`/`subjects_selected` differ from
`profile_snapshot` (a real profile change, not just staleness) - the
current daily model never needed this check since it re-read live data
every single day; a week-long cache does. Alembic migration drops
`study_plan_days`, creates `study_plan_weeks` and `study_note_views`.

No dual-mode fallback: `studyplan/plan.py`, `db/models_studyplan.py`'s old
`StudyPlanDay`, and the old route bodies are replaced outright, not kept
behind a flag.

### 7. API - `api/routes_studyplan.py` (rewritten)

- `GET /v1/study-plan/week` - full week: per-day tasks + rationale, exam
  countdown, per-subject coverage ratios, the `realistic` flag + shortfall
  explanation if set.
- `POST /v1/study-plan/week/days/{day_index}/tasks/{task_index}/done` -
  replaces the old single-index endpoint (a week has 7 days of tasks, not
  one flat list).
- No `/today` endpoint kept as a compatibility shim - the frontend caller is
  migrated instead (see below), per "migrate callers, never add fallbacks."

### 8. Frontend

- `frontend/src/lib/api.ts`: replace `studyPlan.today`/`markDone` with
  `studyPlan.week()` and `studyPlan.markDone(dayIndex, taskIndex, done)`;
  update `StudyPlanResponse`/`StudyPlanTask` types for the new shape
  (add `coverage`, `daysRemaining`, `realistic`, `rationale`, `weeklyNote`).
- `Dashboard.tsx`: keep a compact "today" widget, now sourced from the
  week response's day matching today's date (same `taskHref`/toggle logic,
  reindexed to `(dayIndex, taskIndex)`), plus a one-line exam countdown and
  a "View full week" link.
- New `frontend/src/pages/studyplan/StudyPlanPage.tsx`: the actual planning
  surface - 7-day view, per-subject coverage bars, the weekly note, and (if
  `realistic: false`) a visible, honest callout about the shortfall and
  what's being prioritized. Routed at `/study-plan`.

## Verification

- `backend/test/test_studyplan_*.py` (new/rewritten, following this
  project's existing pure-function-first testing style, e.g.
  `test_esslce_pipeline.py`): `weak_units_across_subjects` returns every
  weak unit not just the min; `unit_stats` produces identical results
  before/after the SQL-aggregate rewrite (compare against a small fixture);
  `planner.build_week_plan` respects `daily_goal_minutes`, surfaces
  `realistic: false` when uncovered-unit minutes exceed the horizon, and
  never drops the "ask anything" slot.
- Real end-to-end check against production-shaped data (same standard
  used earlier this session for `generate_note`): generate a week plan for
  a real grade-12 natural-science test account with an `exam_date` set and
  confirm the countdown, coverage ratios, and task rotation look sane; also
  generate one for an account with no `exam_date` set to confirm the
  no-countdown rolling-week path doesn't crash.
- `cd backend && venv/bin/python -m alembic upgrade head` against a local
  DB before touching production; `npx tsc -b --noEmit` + `npm run build`
  on the frontend; manually open `/study-plan` and the Dashboard widget in
  the dev server.
