# AI-only rigorous answer cross-checking

## Context

Three systems in this app have an LLM produce or pick an answer with no human
answer key to check against, because EAES never provided official past-exam
keys ([[esh-eaes-declined-exam-sourcing]]) and there are no teachers
available to review output:

1. `exams/store.py` `solve_question`/`solve_question_calculation` - proposes
   an answer for an ESSLCE past-paper question, gated at `review_status =
   "needs_review"` until a human runs `exams.cli approve`. With no one to do
   that, solved questions never actually reach students.
2. `agents/workflow.py`'s `AgentWorkflow` (shared by `/v1/explain` and the
   crowdsourced `/v1/exam/solve`) - already re-checks its own draft with
   `VerificationAgent`, but the checker (`LLMClient`, Groq) is the same
   vendor/model family as the one that wrote the draft it's checking.
3. `practice/generator.py`'s `generate_for_passage` (QuizQuestion generation)
   - already does a same-model "blind solve" second opinion before accepting
   a question.

The user wants real rigor added here specifically because there is no
fallback human check: every one of these should get a genuinely **independent
second opinion from a different model**, not the same model grading its own
work, and - where today's `needs_review` human gate would otherwise block
everything indefinitely - full agreement between the two independent checks
should be allowed to approve a question automatically.

Confirmed via `grep`: `langchain_google_genai`'s chat class
(`ChatGoogleGenerativeAI`) is already importable in this venv (it's a
transitive import inside the embeddings module already in use for the vector
migration), so no new package install is needed - only a new settings entry
and ~30 lines of adapter code. Gemini's chat free tier is a separate quota
bucket from the embedding quota currently exhausted
(`generativelanguage.googleapis.com/embed_content_free_tier_requests` is
embedding-specific), confirmed by reading the actual 429 error text from
tonight's re-embedding run - so this feature is not blocked by that.

## Decisions settled in discussion (AskUserQuestion)

- **Scope**: all three systems above.
- **Method**: independent cross-model re-derivation (Gemini, as the second,
  genuinely different model) - not same-model self-consistency resampling,
  because a model's own systematic misconceptions repeat across samples of
  itself but not across model families.
- **Approval policy**: when the cross-check agrees (ESSLCE past-paper path),
  auto-approve - skip the manual `needs_review` gate entirely. On
  disagreement, or if the second model errors/can't be reached, fall back to
  exactly today's behavior (`needs_review`, or for /explain and
  /exam/solve, the existing `FAIL`/`ERROR` handling) - never auto-approve on
  uncertainty, and never treat "the checker failed" the same as "the checker
  disagreed."

## Alternatives considered

1. **Same-model self-consistency voting** (ask Groq the same question N
   times, majority vote) - rejected per the user's explicit choice above:
   cheaper, no new provider wiring, but weaker evidence, since the model's
   own blind spots repeat across its own samples.
2. **A brand-new "answer twice and compare" subsystem per site** - rejected.
   `solve_question(llm, ...)` and `solve_question_calculation(llm, ...)`
   already take the LLM client as a parameter; calling the *same* function
   twice with two different clients reuses 100% of the existing grounding/
   code-execution gates with zero new prompts. Building a parallel mechanism
   would duplicate that trust gate and risk the two paths drifting apart.
3. **A dedicated "devil's advocate" prompt on the same model** (ask the model
   to argue against its own answer) - rejected: still one model's reasoning
   space, which the literature and this project's own experience with
   same-vendor resampling suggests converges back to the same blind spots;
   weaker than genuine cross-model disagreement.
4. **Swap VerificationAgent to Gemini entirely vs. add a whole separate
   parallel-answer pipeline for /explain and /exam/solve** - chosen: swap the
   model underneath `VerificationAgent` (used by both routes already) to
   Gemini. It already fact-checks the Groq draft claim-by-claim against the
   retrieved context; changing only *which model* runs that check turns an
   already-existing step into genuine cross-model verification, with no new
   architecture, versus hand-building a second "answer the same question
   independently and semantically compare the two free-text answers" system
   (needed only because /explain's output is open-ended prose, not a 4-way
   pick - much harder to do well, and not something this project already has
   infrastructure for).

## Implementation

### 1. Shared infra: a Gemini chat client with the same contract as `LLMClient`

New `backend/llm/gemini_client.py`:
- `GeminiLLMClient(model_id=None, temperature=0, max_tokens=1500)` wrapping
  `ChatGoogleGenerativeAI` (`langchain_google_genai`), using
  `settings.GEMINI_API_KEY` and a new `settings.GEMINI_CHAT_MODEL` (default
  `"gemini-3.8-flash"`).
- `.chat(messages: list[dict]) -> dict` - **exactly** `LLMClient`'s contract
  (`{"choices": [{"message": {"content": ...}}]}`), converting the
  OpenAI-style role dicts to what `ChatGoogleGenerativeAI.invoke` expects.
  Reuses `llm.client.parse_json_object` unchanged (it's already
  provider-agnostic string parsing) - every existing caller that does
  `parse_json_object(llm.chat(...)["choices"][0]["message"]["content"])`
  works identically regardless of which client it's given.
- `config/settings.py`: add `GEMINI_CHAT_MODEL: str = "gemini-3.8-flash"`.

`backend/llm/retry.py`'s `invoke_with_retry` currently only recognizes Groq's
`RateLimitError`/`APIConnectionError` and Groq's "try again in Xs" phrasing.
Generalize it (not a parallel copy) to also catch Google's analogous
exceptions (`google.api_core.exceptions.ResourceExhausted`,
`ServiceUnavailable`, imported the same defensive
try/except-ImportError way Groq's are) and parse Gemini's "retry in Xs"
phrasing alongside Groq's "try again in Xs" - one shared retry loop for both
providers, since both are now real, live dependencies of this module, not a
hypothetical.

### 2. ESSLCE past-paper solve - the system with an actual gate to skip

`backend/exams/store.py`:
- New `solve_question_crosschecked(llm_primary, llm_secondary, tb_store,
  paper, q, grades, k)`: calls `solve_question(llm_primary, ...)`; if
  unresolved, returns it unchanged (nothing to cross-check). Otherwise calls
  `solve_question(llm_secondary, ...)` **blind** (same inputs, no mention of
  the primary's answer) and adds `"cross_checked": True, "agreement": bool`
  (`secondary["resolved"] and secondary["answer_index"] ==
  primary["answer_index"]`) and, on disagreement,
  `"secondary_answer_index": secondary.get("answer_index")` to the primary's
  result dict so a reviewer can see both candidates without re-running
  anything. If the secondary call raises (`LLMUnavailableError` or any
  exception), treat as **not cross-checked** (`cross_checked=False`), never
  as a disagreement.
- `solve_paper(db, paper, llm, llm_secondary, tb_store, grades, log)`: calls
  `solve_question_crosschecked` instead of `solve_question`. On
  `agreement is True`: `review_status = "approved"`, `reviewed_by =
  "ai_crosscheck"`, `reviewed_at = now`. Otherwise: unchanged existing
  behavior (`review_status = "needs_review"`).
- `EsslceQuestion` (`exams/models.py`) gains two nullable columns:
  `cross_check_status` (`String(16)`: `"agreed" | "disagreed" | None` =
  never cross-checked) and `cross_check_secondary_answer` (`Integer`,
  populated only when `cross_check_status == "disagreed"`) - so a future
  "show me what the models disagreed on" view needs no new script, just a
  filter. New Alembic revision (chained off `7634b6a9f3ff`, the existing
  baseline) adding these two columns.
- `exams/cli.py`'s `solve` branch: build a second client
  (`GeminiLLMClient(temperature=0, max_tokens=600)`) alongside the existing
  `LLMClient(...)` and pass both into `store.solve_paper`.

### 3. `/v1/explain` + `/v1/exam/solve` - make the existing verify step cross-model

`backend/agents/verification_agent.py`: change `self.model = LLMClient(...)`
to `GeminiLLMClient(...)`. No other change in this file - same JSON
contract, same parsing, same PASS/FAIL/ERROR semantics. This alone makes
*both* routes' existing verification genuinely cross-model, since
`AgentWorkflow` (used by both) already runs this step and already has the
re-research-on-FAIL loop (`agents/workflow.py`, unchanged).

Bundled bug fix found while reading this path (`backend/api/routes_exam.py`):
`result.get("verification_status") == "ERROR"` is special-cased to skip
caching/charging, but a final `"FAIL"` (verification ran, found the draft
unsupported, re-research already exhausted its retries) is **not** - it
silently falls through to the normal cache+charge path despite being
self-flagged as unsupported. Fix: treat `"FAIL"` the same as `"ERROR"` here
(`source="unverified"`, not cached as the canonical answer, not charged) -
directly in scope for "reduce errors," found while grounding this plan in
the real code, not a drive-by unrelated cleanup.

### 4. QuizQuestion generation - swap the existing same-model check to cross-model

`backend/scripts/generate_questions.py`: `solve_llm = LLMClient(...)` becomes
`solve_llm = GeminiLLMClient(temperature=0, max_tokens=800)`. `gen_llm`
(the one that drafts candidate questions) stays Groq. Zero changes needed in
`practice/generator.py`/`practice/validate.py` - `blind_solve` already just
calls `llm.chat(...)` generically against whatever client it's given, and
the existing grounding gate (`check_question`/`quote_in_passage`) is
untouched. This system already auto-accepts on second-opinion agreement
(that's its existing design); this change only makes the second opinion
genuinely independent.

## Verification

- New tests in `backend/test/` for `solve_question_crosschecked`: fake LLM
  clients (agree / disagree / secondary raises) confirm `agreement`,
  `cross_check_status` ends up `"agreed"`/`"disagreed"`/not-set correctly,
  and that `solve_paper` only auto-approves on real agreement.
- Extend `test/test_exam_route.py` (or add alongside it) for the
  `routes_exam.py` FAIL-handling fix: a FAIL-status workflow result must not
  be cached or charged, mirroring the existing ERROR-path test if one
  exists.
- Run the full existing backend test suite (`test/test_*.py`) to confirm the
  `VerificationAgent`/`generate_questions.py` client swaps are transparent -
  existing tests already inject fake LLMs via the `.chat()` contract, so
  they shouldn't need changes, just a pass to confirm.
- One live smoke test once implemented: a tiny real call through
  `GeminiLLMClient.chat(...)` (one message, confirms the model id and
  message-format conversion actually work against the real API) before
  running anything at scale - same spirit as tonight's one-off
  `embed_query` smoke test before trusting the embedding key.
- Run `exams.cli solve` on one already-loaded, already-approved paper's
  subject to see the new `review_status`/`cross_check_status` values land
  correctly, without disturbing papers that aren't touched.
