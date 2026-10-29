# ESSLCE student-facing serving endpoint + Telegram bot wiring

## Context

`backend/exams/` (the Grade-12 ESSLCE past-exam bank) has never had a student-facing serving layer — its own README says so explicitly. The user wants this built as a real, shippable feature now (not a throwaway test harness), testable end-to-end via the Telegram bot, with the student choosing between two modes: one question at a time with immediate feedback, or a full paper with results shown only at the end. The existing `QuizQuestion` practice engine (`routes_practice.py` + `practice/selection.py` + `telegram_bot/practice_flow.py`) already solves this exact shape of problem for a different content type — it's the template to follow, not reinvent.

## 1. `backend/exams/models.py` — new `EsslceAttempt` table

Mirrors `QuizAttempt` (append-only, no unique constraint, so `practice.selection.pick_questions`'s "latest attempt by timestamp" logic works unmodified):

```python
class EsslceAttempt(Base):
    __tablename__ = "esslce_attempts"
    id = Column(Integer, primary_key=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("esslce_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    paper_id = Column(Integer, ForeignKey("esslce_papers.id", ondelete="CASCADE"), nullable=False, index=True)
    chosen_index = Column(Integer, nullable=False)
    is_correct = Column(Boolean, nullable=False)
    mode = Column(String(16), nullable=False, default="practice")  # "practice" | "exam" - informational, not behavior-gating server-side
    created_at = Column(DateTime, server_default=func.now())
```
Needs `from sqlalchemy.dialects.postgresql import UUID` added to the file's imports. `paper_id` is denormalized (skips a join when reconstructing "has this student finished paper X" for the exam-summary endpoint).

Create with `python -m exams.cli create-tables` (picks up any new table on the shared `Base` automatically — confirm before running against the real DB).

## 2. New LaTeX rendering helper: `backend/exams/latex_render.py`

`render_latex_png(text: str) -> bytes | None` — converts `\[ ... \]`/`\( ... \)` delimiters to matplotlib mathtext's `$...$` dialect, renders the full multi-line explanation (plain narration + inline math segments) as one PNG via a `matplotlib.figure.Figure` + `FigureCanvasAgg`, `bbox_inches="tight"`. Mathtext doesn't cover every LaTeX construct (e.g. `\begin{cases}`) — wrap the render call in `try/except` and return `None` on failure so the caller falls back to plain text instead of crashing. This is only ever called for `CALCULATION_SUBJECTS` explanations (reuse that set from `exams/store.py`); grounded/quote-verified explanations stay plain text always.

**New dependency:** `matplotlib` is not currently installed. Per this project's own operational lesson (`requirements.txt` is a frozen `pip freeze` snapshot, fragile on new additions), install it into the venv and do a real resolve check before pinning it into `requirements.txt` — not a guessed version pin.

## 3. New router: `backend/api/routes_esslce.py` at `/v1/esslce`

Reuses `eligible`/`best_unit`/`CALCULATION_SUBJECTS` from `exams/store.py`, `pick_questions`/`unit_progress` from `practice/selection.py` directly (pure, data-shape-agnostic — no fork needed).

- `GET /subjects` — subjects with ≥1 eligible question.
- `GET /papers?subject=...` — papers for a subject with `ready_for_students` count (reuses the `status_rows`-style eligible count), so the bot can offer "take this paper as a mock exam."
- `POST /next` — body `{subject, paper_id?, stream?, count=5}`:
  - `paper_id` set (exam mode): ALL eligible questions of that paper, ascending `item_no`, regardless of prior attempts (a fresh exam attempt always presents every item).
  - `paper_id` absent (practice mode): eligible-question pool filtered by subject(+stream), latest `EsslceAttempt` per question for this user, `pick_questions(...)` orders unseen→wrong→right, same as the practice engine.
  - Reading-comprehension items: batch-fetch `EsslcePassage.text` for the distinct `passage_id`s in the result (one extra query, not N+1), attach as `passage_text`.
- `POST /answer` — body `{question_id, chosen_index, mode}`. Always grades immediately and writes an `EsslceAttempt` row (stateless; `mode` is stored for analytics only, doesn't change server behavior). Response includes `is_correct`, `correct_index`, `explanation`, `supporting_quote`, and — when the paper's subject is in `CALCULATION_SUBJECTS` and rendering succeeds — `explanation_image_base64` (PNG from `latex_render.render_latex_png`, base64-encoded so the whole result is one round trip). Re-verifies `eligible(question)` before answering (404/409 if it was un-approved since being served).
- `POST /exam-summary` — body `{paper_id}`. Joins latest `EsslceAttempt` per question (filtered to that paper, this user) against the paper's eligible questions; returns per-item results + aggregate score. Reconstructible from the DB alone, so a lost/restarted bot session doesn't lose the final summary.

Register in `backend/main.py`: `from api.routes_esslce import router as esslce_router` + `app.include_router(esslce_router)` (uncommented and active, unlike the dormant `exam_router`/`payments_router`).

## 4. Telegram bot: one command, mode sub-menu

New `telegram_bot/esslce_flow.py` (mirrors `practice_flow.py`'s `Screen`/`FlowError`/stateful-session shape, held in `context.user_data`):

- `/esslce` is the single entry point. First screen: "How do you want to practice?" → `[One question at a time]` / `[Full exam — results at the end]`, setting `self.mode`.
- Practice mode: subject → (optionally unit, reusing the same pattern as `PracticeSession`) → questions one at a time, `on_answer` shows the grading screen immediately (sending the rendered PNG via `send_photo` when `explanation_image_base64` is present, plain text otherwise).
- Exam mode: subject → paper (a specific `EsslcePaper`) → all its eligible questions in order; `on_answer` records the already-returned grading result into `self.exam_results` and silently advances — no feedback shown — until the queue empties, then renders a full summary screen (score, and a per-item breakdown the student can step through, including the images for calculation items).
- Callback prefix `^e[a-z]` (unused by `^p[a-z]`/practice and the callback-free `/exam` solver): `em|practice|exam` (mode), `es|<idx>` (subject), `ep|<idx>` (paper, exam mode only), `ea|<qid>|<idx>` (answer), `en` (next), `ex` (stop/finish early).

New `telegram_bot/handlers/esslce_handler.py` mirrors `practice_handler.py` (`keyboard()`, friendly error mapping, command entrypoint, one `CallbackQueryHandler`). `telegram_bot/api_client.py` gets thin wrappers: `esslce_subjects`, `esslce_papers`, `esslce_next`, `esslce_answer`, `esslce_exam_summary`. `bot.py` gets the command registration + help text line.

## 5. Tests: `backend/test/test_esslce_route.py`

Matches the project's existing direct-route-test convention (confirmed from `test/test_exam_route.py`: no pytest, in-memory SQLite built from the real `Base.metadata`, `FastAPI()` + `TestClient` with `dependency_overrides` for `get_db`/`get_current_user`, plain asserts). Seed one `EsslcePaper` + questions covering both eligible and ineligible cases (missing key, `has_diagram`, not approved) + one passage-linked question. Cover: `/next` with and without `paper_id`, `/answer` writing an `EsslceAttempt` and returning a rendered image only for a calculation-subject question, `/exam-summary` after a full paper's worth of answers.

## Verification

- `python test/test_esslce_route.py` from `backend/`.
- Manually exercise `/esslce` through the real Telegram bot once the one real loaded/approved paper (Math 2018, pending the background extraction) is keyed/approved/indexed — confirm both modes end-to-end, including a calculation-subject question rendering as an image.
