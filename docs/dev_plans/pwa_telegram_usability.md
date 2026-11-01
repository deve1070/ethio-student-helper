# PWA + Telegram usability: real progress feedback and button-first flows

## Context

Two usability gaps, both about students not knowing what the app is doing:

1. **PWA**: every slow backend call (notes generation, /explain, exam solving) is a
   single blocking HTTP request. Confirmed by reading every route handler in
   `backend/api/*.py` and `backend/main.py` - no `StreamingResponse`, SSE, or
   websocket exists anywhere. The frontend shows a generic spinner with static text
   the whole time (`ExplainPage.tsx`, `NotesDetail.tsx`'s bare `FullPageSpinner`,
   `ElaboratePanel.tsx`/`AskChatPanel.tsx`'s single "Thinking..." message) - students
   have no way to tell if anything is actually happening.
2. **Telegram bot**: confirmed the practice and ESSLCE flows are already fully
   button-driven (`practice_handler.py`/`practice_flow.py`,
   `esslce_handler.py` - `InlineKeyboardMarkup` end to end, no typed answers). The
   remaining friction is `/start`'s wall of text (12 typed-command examples, no
   buttons at all), `/buy <bundle>` and `/exam <grade> <subject> <question>`
   requiring exact typed syntax, and no `send_chat_action`/interim message on the
   ESSLCE elaborate/ask calls (the slowest LLM calls the bot makes) even though
   `/explain` and `/exam` already do this.

## Decisions settled in discussion

- **PWA**: real backend-reported progress (Server-Sent Events) only for the two
  endpoints with genuine multi-step pipelines - `/v1/explain` (LangGraph workflow:
  relevance check -> research -> cite -> verify, with a possible re-research loop,
  `agents/workflow.py`) and `/v1/notes/note` (`notes/store.py:generate_note` - unit
  retrieval -> LLM generation -> section/LaTeX formatting -> example-quality check).
  The two single-LLM-call features (`esslce.elaborate`, `esslce.ask`) get an honest
  delayed "Still working on it..." message instead - there's nothing more specific
  happening server-side to report for a single call, so simulating fake stages for
  them would be misleading rather than informative.
- **Telegram**: button-ify `/buy` (pick a bundle) and `/exam`'s grade/subject
  selection (typing the question itself stays typed either way - it's open-ended
  text). `/login` stays typed - Telegram bots cannot collect secret text through a
  button, only trigger fixed `callback_data`, so there is no button alternative for
  a password. Every typed form that already works keeps working unchanged alongside
  the new buttons (not a replacement, an addition).

## Alternatives considered

1. **PWA progress depth**: real SSE everywhere vs. none (purely simulated status
   text everywhere) vs. the chosen hybrid. Full SSE on `elaborate`/`ask` was
   rejected - they're one Groq call each, nothing to report a "stage" of. Pure
   simulation everywhere was rejected - it would show fabricated progress on
   `/explain` and notes generation when the real backend pipeline already has
   genuine, reportable steps available for free (LangGraph's own `.stream()`, and
   `generate_note`'s existing procedural steps).
2. **How explain's stages get reported**: a hand-rolled callback threaded through
   `ResearchAgent`/`CitationAgent`/`VerificationAgent` vs. using LangGraph's own
   per-node streaming (`compiled_workflow.stream(...)` instead of `.invoke(...)`).
   **Chosen: LangGraph's own streaming** - the graph already models the pipeline as
   discrete nodes; a parallel callback mechanism would duplicate that structure.
3. **SSE transport**: the browser's native `EventSource` vs. `fetch` + a
   `ReadableStream` reader. **Chosen: fetch+ReadableStream** - `EventSource` only
   supports GET with no custom headers, and this app's auth is a bearer token in a
   request header, not a cookie.
4. **Telegram main menu**: leave `/start` as a typed-command list (status quo) vs.
   a button hub (chosen) vs. removing typed commands entirely. Removing typed forms
   was rejected - `/login` must stay typed, and power users typing a remembered
   command is strictly faster than tapping through a menu, so both should coexist.

## Implementation

### A. PWA - real progress for explain & notes, honest status elsewhere

**A1. Shared SSE transport (new, shared infrastructure)**
- `backend/utils/sse.py`: `format_sse_event(data: dict) -> str` -> `f"data: {json.dumps(data)}\n\n"`.
- `frontend/src/lib/sse.ts`: `streamPost<T>(url, body, onEvent: (data) => void): Promise<T>` -
  `fetch` with the existing auth header, reads `response.body.getReader()`, splits on
  blank lines, parses each `data:` line as JSON, calls `onEvent` for every event
  until one carries `done: true`, whose payload is the resolved value.

**A2. `/v1/explain` streaming**
- `agents/workflow.py`: add `AgentWorkflow.stream_full_pipeline(question, retriever)`,
  a generator using `self.compiled_workflow.stream(initial_state)` instead of
  `.invoke(...)` (confirm the exact `stream_mode` needed against the installed
  `langgraph==0.2.68` while implementing - `full_pipeline`'s existing `.invoke()`
  call and return shape stay unchanged as the non-streaming entry point). Maps each
  completed node name to a short label (`check_relevance` -> "Checking if your
  textbook covers this...", `research` -> "Writing an answer...", `cite` -> "Finding
  the right pages...", `verify` -> "Double-checking the answer...") and yields each
  as it completes, then yields the same final result `full_pipeline` already builds.
- `backend/api/routes_explain.py`: route becomes `StreamingResponse(media_type=
  "text/event-stream")`, writing one SSE event per stage label plus a final
  `{"done": true, ...answer}` event.
- `frontend/src/lib/api.ts` (`explain.ask`) switches to `streamPost`, taking an
  `onStage` callback; `ExplainPage.tsx` shows the live label instead of static text.

**A3. `/v1/notes/note` streaming**
- `notes/store.py`: `generate_note`/`get_or_create_note` gain an optional
  `on_stage: Callable[[str], None] | None = None`, called before unit retrieval
  ("Reading your textbook..."), before the generation LLM call ("Writing your
  notes..."), before `_numbered_sections` ("Formatting formulas..."), and before
  `_judge_sections` ("Double-checking examples..."). A plain callback, not a
  generator - this code is procedural, not a graph, so it keeps its own shape
  rather than being forced into the same mechanism as A2.
- `backend/api/routes_notes.py`: wraps the call so the route is still one
  `StreamingResponse` sharing A1's event format (the callback feeds a small
  generator/queue the route reads from).
- `frontend/src/pages/notes/NotesDetail.tsx`: live stage label replaces the bare
  `FullPageSpinner`.

**A4. Honest delayed status for single-call features**
- New `frontend/src/lib/useDelayedStatus.ts`: after ~4s, swaps a panel's static
  "Working it out.../Thinking..." text for "Still working on it...". Used by
  `ElaboratePanel.tsx` and `AskChatPanel.tsx` - one honest escalation, not a
  fabricated multi-step sequence, since nothing more granular is actually happening.

### B. Telegram - button-first flows + "something's happening" signals

**B1. Main menu replaces `/start`'s text wall**
- `telegram_bot/bot.py`: `start_command` sends an `InlineKeyboardMarkup` hub
  (Practice, ESSLCE, Explain, My Credits, Buy Credits, Reminders, Login/Logout) in
  place of the typed-command list. New `CallbackQueryHandler` (pattern `^m[a-z]`)
  calls the same entry-point function each slash command already calls.
- `set_my_commands` added in `post_init` so Telegram's native "/" menu also lists
  every command (currently never populated anywhere in the repo).

**B2. `/buy` buttons**
- `telegram_bot/handlers/payment_handler.py`: argument-less `/buy` shows inline
  buttons for `bundle_5`/`bundle_20` (`callback_data="by|bundle_5"` etc.); new
  `buy_callback` reuses the existing instructions text, parameterized by the tapped
  bundle instead of `context.args[0]`. Typing `/buy bundle_5` keeps working
  unchanged - same code path, just also reachable by button now.

**B3. `/exam` becomes grade -> subject buttons, then typed question**
- `telegram_bot/handlers/exam_handler.py`: argument-less `/exam` starts a guided
  flow using the same `context.user_data` state pattern `practice_flow.py` already
  established (a small `grade`/`subject` holder), with button rows for grade then
  subject (`callback_data="xg|<grade>"`, `"xs|<subject>"`), ending with "now type
  your question, or send a photo." The single-line `/exam <grade> <subject>
  <question>` form keeps working unchanged - both paths end at the existing
  `_solve_and_reply`.

**B4. `/remind` quick-pick buttons**
- `telegram_bot/handlers/reminder_handler.py`: bare `/remind` (today's status-check
  path) also shows buttons for a few common times plus "Off"
  (`callback_data="rm|18:00"`, `"rm|off"`); typing `/remind 6:45` keeps working
  exactly as today for anything not in the quick list.

**B5. "Something's happening" signals**
- Wherever `esslce_elaborate`/`esslce_ask` are actually called (confirm the exact
  handler while implementing) gains the same pattern `explain_handler.py`/
  `exam_handler.py` already use: `context.bot.send_chat_action(...,
  action=ChatAction.TYPING)` plus an interim text message, right before the slow
  `api_client` call - currently the one slow-call pair missing this.

## Verification

- Add/extend backend route tests for `/v1/explain` and `/v1/notes/note` confirming
  the SSE stream parses into the expected stage events followed by one `done` event
  (this project's existing TestClient + `dependency_overrides` convention).
- Run the frontend dev server and manually exercise /explain and a notes page to
  watch the live stage label change, and elaborate/ask to see the delayed "Still
  working..." message after ~4s.
- Telegram changes can't run live in this sandbox (needs a real bot token and
  network to api.telegram.org) - verified by direct code reading; flag for the user
  to manually walk through `/start`, `/buy`, `/exam`, `/remind` against the real bot
  once deployed.
- Run the full existing backend test suite to confirm no regressions.
