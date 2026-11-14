# Daily mass ESSLCE practice (Phase 1): subscriber-only group challenge, leaderboard, consistency

## Context

The product owner's stated core problem: students lack consistency and discipline in exam prep.
The requested fix is a daily, fixed-time, scheduled ESSLCE practice event - "mass" in the sense of
everyone doing it together, at the same time, inside a private Telegram group restricted to
subscribers (a separate, already-planned public channel stays open to everyone for general
community). After each event: answers + explanations, a scorers list, and (web app) a leaderboard
ranking students by questions answered and by consistency of participation specifically in this
mass practice - not general app usage. A later phase (explicitly deferred, not built now) adds an
AI-generated "how this unit tends to be tested in the real exam" insight per unit, synthesized from
historical exam questions plus the textbook's own content for that unit.

Scale today is tiny (2 total users, 1 Telegram-linked) - this is designed to work correctly now and
scale later without an architecture change, using only infrastructure already running (the existing
single FastAPI process + single bot process, no new services).

## Design

### Core mechanic: native Telegram quiz polls, not hand-rolled buttons

Telegram's own `send_poll(type="quiz", is_anonymous=False, correct_option_id=N, explanation=...,
open_period=<seconds>)` is purpose-built for exactly this: one question posted to the group, each
member answers privately (nobody else sees who answered what or what they chose - inline poll votes
are inherently per-voter-private in Telegram), the correct answer + explanation is shown to each
voter the instant they answer, and the poll auto-closes after `open_period` seconds (Telegram's
documented range is 5-600s, confirmed via the installed library's own `PollLimit` constants - our
75-90s range is comfortably inside it). `PollAnswerHandler` delivers a `PollAnswer` update per vote
with the voter and their chosen option(s). This replaces what would otherwise be a much larger
hand-rolled inline-keyboard-plus-callback-tracking build, confirmed directly against the installed
`python-telegram-bot` 21.9 library (not assumed).

### Configuration: environment variables, not hardcoded

Matching the existing `BOT_TIMEZONE`-env-var convention (`reminders.py`'s `local_tz()`):
- `MASS_CHALLENGE_TIME` (default `"20:00"`) - parsed with `reminders.py`'s existing public
  `parse_time()` helper, reused as-is, not reimplemented.
- `MASS_CHALLENGE_QUESTION_COUNT` (default `6`)
- `MASS_CHALLENGE_QUESTION_SECONDS` (default `90`) - the per-question `open_period`; a short fixed
  breather (e.g. 15s) between questions is a code constant, not worth its own env var.
- `TELEGRAM_PRIVATE_GROUP_ID` (default `0` = feature disabled) - the private group's numeric chat
  id, added to both `backend/config/settings.py` and `telegram_bot/config.py`, following the exact
  duplication pattern `TELEGRAM_GROUP_URL` already uses (both files read the same `.env`).

This means the owner can retune timing/length/count purely by editing `.env` and restarting,
matching the explicit request to be able to "manage based on the condition" without a code change.

### Data model

One new Alembic migration (same `op.create_table`/`CheckConstraint`/`UniqueConstraint` shape as
`f1a2c3d4e5f6_free_action_usage.py`):

```python
mass_challenges:
    id              Integer PK
    date            Date, not null
    stream          String(32), not null, default ""   # "" for Phase 1 (one combined daily event);
                                                          # forward-compatible for a Phase 2/3 switch
                                                          # to separate natural/social tracks with zero
                                                          # further schema change
    subject         String(64), not null
    grade           Integer, nullable                    # disambiguates a recurring unit name, same
                                                          # role as EsslceTopicLink.grade
    unit            String(255), not null
    question_ids    JSON, not null                        # ordered EsslceQuestion ids, fixed at creation
    opens_at        DateTime(timezone=True), not null
    question_seconds Integer, not null
    created_at      DateTime(timezone=True), server_default now()
    UniqueConstraint(date, stream)

mass_challenge_polls:
    id                 Integer PK
    challenge_id       Integer FK -> mass_challenges.id, ondelete CASCADE, index
    question_id        Integer FK -> esslce_questions.id, ondelete CASCADE
    telegram_poll_id   String(64), not null, unique, index   # matches PollAnswer.poll_id
    sent_at            DateTime(timezone=True), server_default now()

private_group_memberships:
    user_id     UUID FK -> users.id, ondelete CASCADE, PRIMARY KEY
    joined_at   DateTime(timezone=True), server_default now()
```

Plus one nullable column added to the existing `esslce_attempts` table in the same migration:
`mass_challenge_id` (FK -> `mass_challenges.id`, `ondelete="SET NULL"`, indexed).

**Reuse `EsslceAttempt` for mass-challenge answers, don't create a parallel table** - confirmed via
direct inspection of `backend/exams/models.py`: `mode` has no DB `CheckConstraint` (unlike
`FreeActionUsage.feature`, which does), so `mode="mass"` needs no migration at the DB layer; the
Pydantic `Literal["practice","exam","diagnostic"]` restriction lives only on the existing
`/v1/esslce/answer` route's request model and is irrelevant since mass answers go through their own
new endpoint. `paper_id` is `NOT NULL` but trivially satisfied (`question.paper_id`, exactly like
`/answer` already does). `routes_esslce.py`'s own docstring already states `mode` is informational
only and never gates server behavior - exam-mode and practice-mode attempts already commingle in
`student_progress`/`mistakes`/repeat-avoidance, so mass-mode joining that same pool is consistent,
not a new precedent. This also means the consistency/question-count leaderboard can reuse
`practice/selection.py`'s existing `local_date()` (already Africa/Addis_Ababa-aware) for free.
The recording endpoint is made idempotent (no-op if a row for `(user_id, mass_challenge_id,
question_id)` already exists) as a defensive measure, since `PollAnswer.option_ids` can in principle
be empty (vote retraction) even though quiz-mode polls are expected not to allow it in practice.

### Backend: question picking

New functions in `backend/exams/store.py`, reusing the exact `eligible_filter()`/`EsslceTopicLink`
join `eligible_units()`/`best_unit()` already use (not reinvented):
- `pick_todays_unit(db, today) -> (subject, grade, unit)`: deterministic rotation - subject chosen
  by `day_of_year % len(ALL_SUBJECTS)` (skipping a subject with zero eligible units and advancing),
  then a unit from that subject's eligible-unit list the same way. One combined daily event for
  Phase 1 (not separate natural/social tracks) - with only 2 users, doubling every moving part of
  this design (two announcements, two question sequences, two reveals, stream-based routing of who
  sees which) is complexity with no audience yet; an off-stream student occasionally getting a
  day outside their own stream is an explicitly accepted, minor cost at this scale. The `stream`
  column on `mass_challenges` keeps this cheap to revisit later without a schema change.
- `pick_mass_challenge_questions(db, subject, grade, unit, count)`: the same unit-filtered eligible
  pool `/esslce/next`'s existing `unit` request param already builds, sampled down to `count`.

### Backend: new route file `backend/api/routes_mass_challenge.py`

Registered in `backend/main.py` alongside the other routers.

- `POST /v1/mass-challenge/today` - get-or-create today's challenge (idempotent: looked up by
  `(date, stream="")` first; a bot restart re-firing the opening job never double-creates).
- `POST /v1/mass-challenge/answer` - body `{challenge_id, question_id, chosen_index}`; the voting
  student's own JWT, resolved bot-side exactly like every other bot feature already does.
- `GET /v1/mass-challenge/{id}/leaderboard` - score + time ranking for one challenge (used by the
  reveal message and the web app).
- `GET /v1/mass-challenge/consistency-leaderboard` - distinct mass-participation days (reusing
  `local_date()`) + total mass questions answered, ranked, for the web app's leaderboard page.

**Auth for the three bot-initiated, no-specific-student calls** (creating today's challenge,
checking private-group join eligibility, fetching the leaderboard to post the reveal): none of
these act on behalf of one particular student, so the existing per-student-JWT pattern genuinely
doesn't fit (confirmed: this codebase has no service/API-key auth path today, only
`get_current_user`'s bearer-JWT check). Borrowing a specific admin's own login session was
considered and rejected: it would make the whole feature silently stall if that admin's token ever
expires with nobody noticing, since nothing in this flow would surface that failure to anyone. The
deep fix instead: a small, narrow `BOT_INTERNAL_TOKEN` env var (generated once, known only to the
backend and the bot process) checked by a new FastAPI dependency used **only** by these three calls
- not a general service-account impersonation mechanism, not reused anywhere else. This avoids a
fragile hidden dependency on a human's session staying fresh for an otherwise fully unattended,
scheduled feature.

### Bot: new module `telegram_bot/mass_challenge.py`

Mirrors `reminders.py`'s shape (module-level helpers, functions taking `job_queue`/`context`,
`reminders.local_tz()` for timezone).

- `schedule_daily_event(job_queue, tz)` - one **global** `run_daily` job (not per-user, confirmed
  this is new ground - no shared/global job exists anywhere in this codebase today), registered
  unconditionally every boot from `bot.py`'s `post_init` (nothing to "restore" the way per-user
  reminders are, since there's only ever one job, not N).
- `open_challenge(context)` - calls `/mass-challenge/today`, posts one announcement message to
  `TELEGRAM_PRIVATE_GROUP_ID`, then schedules `MASS_CHALLENGE_QUESTION_COUNT` chained
  `job_queue.run_once(post_question, when=i*(question_seconds+15), data={...})` calls (confirmed
  this chaining approach is directly supported by the installed library's `run_once` signature -
  simpler than a stateful repeating loop), then one final `run_once(reveal, ...)` timed for right
  after the last poll's `open_period` ends.
- `post_question(context)` - sends one `send_poll(type="quiz", is_anonymous=False, ...)` to the
  private group, records the resulting `message.poll.id` into `mass_challenge_polls` via the
  backend **before** any vote could arrive.
- `on_poll_answer(update, context)` - the global `PollAnswerHandler`. Looks up `poll_id -> question`
  via a short-lived in-memory dict populated by `post_question` (durability across a bot restart is
  the backend's `mass_challenge_polls` table's job, not this dict's); resolves the voter's stored
  JWT via `telegram_bot/store.py`; calls the new `/answer` endpoint; on a `401` (that student's
  token expired since their last `/login`), DMs them to `/login` again so future votes count -
  flagged explicitly as an accepted Phase-1 limitation at this scale, not silently swallowed.
- `reveal(context)` - fetches the leaderboard (service-token auth) and posts one ranked results
  message to the group. This is where Phase 2's AI insight would attach later, not now.
- `on_join_request(update, context)` (`ChatJoinRequestHandler`) - resolves the requester's
  `telegram_user_id` -> `TelegramLink` -> `User` -> `has_active_subscription` (reused exactly as-is
  from `payments/entitlement.py`) via the service-token-authed lookup (a fresh join requester may
  not have a stored session in this bot process at all, so this cannot go through the per-student-
  JWT pattern either); approves or declines, DMing a decline with a pointer to `/subscribe`.
- `sweep_expired_memberships(context)` - daily `run_daily`. Iterates `private_group_memberships`
  rows only (not every `TelegramLink` - avoids one `get_chat_member` call per linked user),
  `ban_chat_member` + immediate `unban_chat_member` (kick without a permanent ban, so they can
  request to rejoin after resubscribing) for anyone whose subscription has lapsed, removes their row.

`telegram_bot/api_client.py` gains `mass_challenge_today`, `mass_challenge_answer`,
`mass_challenge_leaderboard` following the existing function shape in that file exactly.

`telegram_bot/bot.py`: call `mass_challenge.schedule_daily_event(...)` and
`mass_challenge.schedule_sweep(...)` from `post_init`; register
`ChatJoinRequestHandler(mass_challenge.on_join_request)` and
`PollAnswerHandler(mass_challenge.on_poll_answer)`.

### Frontend: `/leaderboard` page

New route + page (two views: today's challenge ranking, consistency+question-count ranking),
`lib/api.ts` additions for the two `GET` endpoints above. Kept deliberately light in this plan since
the real complexity is backend/bot-side, not here - straightforward once the data exists, following
this app's existing list/ranking-page conventions (e.g. `MistakesPage.tsx`'s list-rendering style).

### Explicitly deferred (not built in this pass)

- **Phase 2**: the AI-generated "how this unit is tested" insight (cached per `(subject, unit,
  grade)`, same shape as `notes/store.py`'s `StudyNote` caching - generated once, shared across
  every student, attached to the reveal message).
- **Phase 3 ideas** (offered, not committed, since the request explicitly invited going beyond what
  was asked): speed-weighted scoring (faster correct answers score higher, Kahoot-style, using
  `PollAnswer`'s own timing); a "streak at risk" DM sent only to subscribers who haven't
  participated yet, shortly before that day's reveal (targeted, not a blast to everyone); badges
  (7-day streak, perfect score, top-10-this-week) shown on the Profile page; splitting into
  separate natural/social tracks once there's a real audience to justify it (the `stream` column
  is already there for this); a lighter-weight async "make-up" path for a subscriber who misses the
  live window, so one missed evening doesn't zero out their whole streak.

## Verification

- `cd backend && venv/bin/alembic upgrade head` against local Postgres.
- New test file mirroring `test_entitlement.py`'s direct-unit-test shape: question-picking rotation
  determinism, answer-recording idempotency, leaderboard ranking correctness, all against a bare
  SQLite session, no HTTP layer.
- Manual end-to-end: with `TELEGRAM_PRIVATE_GROUP_ID` set to a real test group (owner creates it,
  adds the bot as admin, enables "approve new members"), confirm a subscribed test account's join
  request is auto-approved and a non-subscribed one is declined; confirm the daily job fires at the
  configured `MASS_CHALLENGE_TIME`, posts the right number of timed quiz polls, and the reveal
  message's leaderboard matches what was actually answered; confirm the web app's `/leaderboard`
  page reflects the same data.

## Addendum: after the reveal (answer key, catch-up, streak reminder, weekly ranking)

Built after Phase 1, on top of the group-poll design (the "Core mechanic" section above describes
quiz polls; the shipped version uses regular polls, so nobody sees correctness before the reveal).

- **Answer key.** The reveal job posts a second message: each question's correct option, plus its
  explanation when that is plain text. An explanation containing LaTeX is left out, since a group
  message cannot render it; the poll's "Ask AI" button covers those.
- **Catch-up.** A student who missed the polls answers the same questions in their private chat
  (`/catchup`, or the button under the answer key). The backend decides whether an answer is late:
  it is late when that question's group poll closed more than 10 seconds ago, or when the question
  has no poll of its own while the challenge has already posted others. A late answer is stored as
  `EsslceAttempt.mode = "mass_late"`. It counts toward participation days and question totals (the
  consistency ranking), and is excluded from the day's and the week's score rankings, because the
  correct answers are public by then.
- **Streak reminder.** `MASS_CHALLENGE_NUDGE_MINUTES` after the opening time, the bot privately
  messages each student who took part yesterday and has not answered today (`GET /at-risk`), with a
  button into the catch-up flow for their own stream's challenge.
- **Weekly ranking.** `GET /weekly-leaderboard`: on-time correct answers over the last 7 local days.
- **Invite link.** `TELEGRAM_PRIVATE_GROUP_URL`, returned in the profile only to a subscribed student.

Alternatives considered for catch-up scoring: counting late answers in the day's ranking (rejected:
the answers are already posted), or not recording them at all (rejected: one missed evening would
end a streak, the discipline problem this feature exists to solve).
