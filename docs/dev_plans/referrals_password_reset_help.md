# Referrals, Telegram-based password reset, and Help/Contact

## Context

Three production-facing features, requested together:

1. **Password reset via Telegram** - this app has no email/SMS provider, so a
   forgotten password currently has no recovery path at all. The bot already
   has a `/login <identifier> <password>` command
   (`telegram_bot/handlers/auth_handler.py`) that, as a side effect, creates a
   `TelegramLink` row (`db/models.py`) tying a Telegram chat to the account -
   confirmed with the user: reset is scoped to students who have done this at
   least once; a student who hasn't is directed to link first (or to the
   regular login page), not given some other recovery channel.
2. **Help/Contact via a Telegram group** - the user is creating a real
   Telegram group for student support/info; the app needs a visible link to
   it once it exists.
3. **Referral tracking** - every student gets a referral code at signup;
   entering someone else's code at signup (optional field) links the two
   accounts; when the referred student's FIRST payment completes, the
   referrer's paid-referral count goes up by one. Confirmed with the user:
   this is a plain counter, not a credit/cash reward - "count how many
   students he refer / increase the number by one." Confirmed: an invalid
   code at signup blocks signup with a clear error, not a silent drop.

All three are new, but every one of them sits directly on top of existing,
working infrastructure: `TelegramLink`, `payments/admin_notify.py`'s proven
direct-push-to-Telegram pattern, `CreditLedgerEntry`'s payment-completion
hook points, and `auth/security.py`'s password hashing helpers.

## Alternatives considered

- **Password reset delivery**: push the code by calling Telegram's Bot API
  directly from the backend (chosen) vs. routing it through the running bot
  process via some shared queue. `payments/admin_notify.py` already proves
  the direct-push pattern works and needs no bot-process dependency - the
  bot staying up or down never affects whether a reset code can be sent.
- **Reset code storage**: a small DB table, `PasswordResetCode` (chosen,
  mirrors `EsslceAttempt`/`Payment`'s append-only-record style already used
  everywhere in this app) vs. an in-memory/Redis store. This stack has no
  Redis; a DB table also survives a worker restart and costs nothing extra
  to add.
- **Referral count**: a stored counter on `User`, incremented at the moment
  a referred student's first payment completes (chosen, matches the user's
  own "increase by one" framing exactly) vs. computing it on every read via
  a join/count query. The stored counter is simpler to serve and the
  eventual-consistency risk (a completed payment later being reversed) is
  rare enough not to justify a live query for this.
- **Referral relationship storage**: two plain columns on `User`
  (`referred_by_user_id`, `referral_paid_count` - chosen) vs. a dedicated
  `Referral` table with its own row per relationship. The dedicated table
  would allow richer history (when, which payment) later, but the user only
  asked for a count; two columns satisfy that with no join at read time.
- **Help/Contact link source**: a backend setting surfaced through the
  existing `/v1/auth/me` response (chosen) vs. baking the group URL into the
  frontend build as a Vite env var. The real invite link doesn't exist yet
  (the group isn't created); a backend setting can be filled in and take
  effect immediately (restart only, no frontend rebuild) the moment it is.

## Design

### 1. Referral codes and signup

- `db/models.py`'s `User` gains three columns: `referral_code` (unique,
  not null), `referred_by_user_id` (nullable FK to `users.id`,
  `ondelete="SET NULL"`), `referral_paid_count` (not null, default 0).
- New `auth/referral.py`: `generate_referral_code(db) -> str` - 8 characters
  from a deliberately unambiguous alphabet (no `0`/`O`, `1`/`I`), retried on
  the rare collision (checked against the DB), so codes are safe to read
  aloud or type from memory.
- `api/routes_auth.py`'s `SignupRequest` gets `referral_code: str | None`.
  In `signup()`: the new user always gets its own `referral_code` via
  `generate_referral_code`. If `body.referral_code` is given, look it up
  (case-insensitive) against `User.referral_code`; no match raises
  `HTTPException(400, "That referral code doesn't exist.")` per the user's
  confirmed choice; a match sets `referred_by_user_id` on the new user.
- `ProfileResponse` (same file) gains `referral_code` and
  `referral_paid_count`, so the frontend can show both without a new
  endpoint.

### 2. Referral count increments on the referred student's first payment

- New `payments/referral.py`: `credit_referral_if_first_payment(db,
  payment: Payment) -> None`. No-ops if `payment.user.referred_by_user_id`
  is `None`. Otherwise checks whether this is that user's first `completed`
  payment (`Payment.user_id == payment.user_id, status == "completed", id
  != payment.id` count is 0); if so, increments the referrer's
  `referral_paid_count` by 1 and - best-effort, same reasoning as
  `admin_notify.py` - pushes a short "one of your referrals just became a
  paying student!" message to the referrer's linked Telegram chat if they
  have one.
- `api/routes_payments.py` calls this once, right after each of the two
  existing `db.add(CreditLedgerEntry(...))` lines (`submit_receipt`'s
  auto-approve path and `approve_payment`'s manual path) - the two places a
  payment is ever marked `completed` today. Not a new third code path; both
  existing completion points call the same shared helper, so the logic
  never has to be kept in sync by hand across them.

### 3. Password reset via Telegram

- New `db/models.py` table `PasswordResetCode`: `id`, `user_id` (FK,
  cascade), `code_hash` (hashed with the same `auth/security.hash_password`
  used for real passwords - a reset code is a short-lived credential too,
  never stored in plaintext), `expires_at`, `used_at` (nullable),
  `created_at`.
- New `auth/telegram_notify.py`: `send_reset_code(db, user, code) ->
  bool` - looks up the user's most-recently-linked `TelegramLink`
  (`user_id` can in principle have more than one historical link if they
  ever logged into the bot from a different Telegram account; the latest
  one wins) and pushes the code via a direct `sendMessage` call to
  Telegram's Bot API, exactly the `httpx.post(...)` pattern
  `payments/admin_notify.py` already uses for `sendPhoto` - same
  best-effort error handling, same `settings.TELEGRAM_BOT_TOKEN` setting.
  Returns `False` (nothing sent) if the token isn't configured, the user
  has no link, or the push fails.
- `api/routes_auth.py` gets two new endpoints, both rate-limited like
  `/login` (`@limiter.limit("5/minute")`):
  - `POST /auth/password-reset/request` `{identifier}` - finds the user by
    phone/email (reusing `_find_user_by_identifier`). If no user, or the
    user has no `TelegramLink`, responds `{"status": "no_telegram_link"}`
    (deliberately the same response either way - this doesn't confirm or
    deny that an account exists, only whether Telegram-based reset is
    available for it). If the user has a link: invalidate any still-active
    code for them, generate a random 6-digit code, store it hashed with a
    10-minute expiry, call `send_reset_code`, and respond
    `{"status": "code_sent"}` (or still `"no_telegram_link"` if the push
    itself failed, so the frontend never promises a code that didn't
    arrive).
  - `POST /auth/password-reset/confirm` `{identifier, code, new_password}`
    - finds the user's latest unused, unexpired `PasswordResetCode` and
    checks `code` against `code_hash` with `verify_password`. On match:
    sets `password_hash`, marks the code used, and returns a fresh
    `TokenResponse` (logs them straight in, same as signup/login). On any
    mismatch/expiry/already-used: `401 "Invalid or expired code."`
- `config/settings.py` gets `PASSWORD_RESET_CODE_EXPIRE_MINUTES: int = 10`.

### 4. Help/Contact via the Telegram group

- `config/settings.py` gets `TELEGRAM_GROUP_URL: str = ""` (empty until the
  user creates the group and sets it).
- `ProfileResponse` gains `telegram_group_url: str | None` (omitted/`None`
  when unset, so the frontend can hide the row entirely rather than show a
  dead link).
- `telegram_bot/bot.py` gets a small `/help` command (and a line added to
  `/start`'s welcome text) that replies with the same group link, read from
  its own already-shared `.env` - so the link is reachable both from the
  app and from inside the bot itself.

### 5. Migration

One new Alembic migration:
- Adds `users.referral_code` (unique), `users.referred_by_user_id` (FK,
  nullable), `users.referral_paid_count` (default 0) - backfills a
  generated code for every existing user as part of `upgrade()` (same
  "fix up existing rows inside the migration" precedent as
  `b5fc7992aa61`'s `DELETE FROM study_notes`), since the column can't be
  both unique and not-null with blank values on existing rows.
- Creates `password_reset_codes`.

### 6. Telegram bot

No change to the reset flow itself (it's a one-way push from the backend,
same as admin payment alerts - the bot process being up or down doesn't
matter). Only the `/help` command/welcome-text addition from part 4.

### 7. Frontend

- `lib/api.ts`: `SignupRequest`-equivalent payload gets optional
  `referral_code`; profile type gets `referral_code`, `referral_paid_count`,
  `telegram_group_url`; new `auth.requestPasswordReset(identifier)` /
  `auth.confirmPasswordReset(identifier, code, new_password)`.
- `pages/auth/Signup.tsx`: one new optional "Referral code" text field,
  sent as-is (uppercased/trimmed client-side for forgiveness, matching how
  the backend compares it case-insensitively).
- `pages/auth/Login.tsx`: a "Forgot password?" link under the form.
- New `pages/auth/ForgotPassword.tsx`: step 1 (enter identifier → request);
  branches on the response - `code_sent` moves to step 2 (code + new
  password + confirm, then logs the student in and navigates home);
  `no_telegram_link` shows a message directing them to open the bot and run
  `/login <phone or email> <password>` once to enable reset for next time,
  with a link back to `/login` and a link to the Telegram group (ties
  directly into the Help feature) for anyone who needs a human.
- `App.tsx`: new public route `/forgot-password`, wrapped the same way
  `/login`/`/signup` are (`RedirectIfAuthed`).
- `pages/Profile.tsx`: two new cards - "Invite friends" (the student's own
  code, a one-tap copy/share action, and "`N` students you referred are now
  Premium") and "Help & Support" (the Telegram group link, hidden entirely
  if `telegram_group_url` is empty).

## Verification

- `backend/test/test_auth_route.py` (extended): signing up with a valid
  referral code links `referred_by_user_id`; an invalid code returns 400
  and creates no account; `/password-reset/request` for a linked user
  returns `code_sent` and a `PasswordResetCode` row exists; for an unlinked
  or unknown identifier returns `no_telegram_link` either way; `/confirm`
  with the right code changes the password and logs in; a wrong/expired/
  reused code is rejected; the Telegram push itself is stubbed (same
  `httpx`-call-boundary stubbing style `payments/admin_notify.py`'s own
  behavior would need, not a real network call).
- `backend/test/test_payments_route.py` (extended): a referred user's first
  completed payment increments the referrer's `referral_paid_count` by
  exactly 1 (covering both the auto-approve and manual-approve paths); a
  second payment from the same user does not increment it again.
- `cd backend && venv/bin/python -m alembic upgrade head` against a local
  Postgres (not production) to confirm the migration (including the
  existing-user backfill) applies cleanly, same approach used for the
  study-plan migration earlier.
- `npx tsc -b --noEmit` + `npm run build` on the frontend; manually run
  through signup-with-a-code, invalid-code, forgot-password (both
  branches), and the Profile page's new cards against the already-running
  local backend/frontend dev servers.
