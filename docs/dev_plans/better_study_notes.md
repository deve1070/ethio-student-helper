# Better Study Notes: real LaTeX rendering + per-topic worked examples

## Context

The user shared a note from another app (Grade 12 Sequences and Series) as the
quality bar they want ours to match: every subtopic states its own formula/
theorem, is followed by one or more fully worked "Example: / Solution:"
blocks right where that formula is taught, and the math renders cleanly.

Reading our own pipeline end to end (`backend/notes/store.py`,
`backend/exams/latex_render.py`, `backend/api/routes_notes.py`,
`frontend/src/pages/notes/NotesDetail.tsx`) turned up two concrete gaps, not
just "the prompt needs to be better":

1. **Math rendering is weak on the web app specifically.** Every piece of
   LaTeX (notes' key formulas/worked example, ESSLCE answer explanations,
   elaborate, ask-about-this-question) is pre-rendered server-side to a PNG
   via `exams/latex_render.py`'s `render_latex_png`, which uses matplotlib's
   "mathtext" dialect - confirmed directly in that file's own docstring and
   regex comments: no `\begin{cases}` support, no real matrix/grid layout
   (flattened to one inline row), a fixed raster image that doesn't scale or
   stay crisp. The web app is a React PWA that could render real LaTeX in
   the browser instead - it just never has, because this PNG pipeline was
   built once and reused everywhere including routes that didn't need a
   raster image at all.
   - Confirmed directly: every response that carries an `*_image_base64`
     field (`NoteResponse.formulas_image_base64`/`worked_example_image_base64`,
     `AnswerResponse.explanation_image_base64`, `ElaborateResponse.
     content_image_base64`, `AskResponse.reply_image_base64`) ALSO already
     carries the same content as plain text/LaTeX
     (`key_formulas`/`worked_example`, `explanation`, `content`, `reply`).
     The backend already sends both; only the frontend ever chose the image.
   - Telegram still needs the PNG (it can't run JS) - this is purely a web-
     frontend change, the backend's existing image generation and fields are
     untouched.

2. **Calculation-subject notes get exactly ONE worked example for the
   WHOLE unit**, detached from whichever subtopic it happens to illustrate
   (`notes/store.py`'s `CALC_SUPPLEMENT_PROMPT` + `key_formulas`/
   `worked_example`, called once after all sections are built). The
   reference note instead ties a formula and its worked example to the
   specific subtopic that introduces it. This project already solved an
   analogous problem for English notes - `ENGLISH_UNIT_PROMPT`'s own comment
   explains that putting the real requirement (a real example, stated in
   the field's own description) directly into the per-section JSON field,
   rather than as a generic add-on rule, is what actually changed the
   output. The same fix applies here: a per-section prompt field, not a
   unit-wide bolt-on.

Confirmed via AskUserQuestion: build the LaTeX renderer as shared frontend
infrastructure (notes, elaborate, ask-about-this-question, and exam answer
explanations all switch to it, not just notes), and give every
calculation-subject subtopic its own worked example(s), the same way English
subtopics already each get their own.

## Alternatives considered

1. **Keep matplotlib PNG rendering, just improve the mathtext-conversion
   regexes** (handle more LaTeX constructs) - rejected. mathtext fundamentally
   has no matrix/grid support and a fixed, non-scaling raster output; no
   amount of regex preprocessing changes that ceiling. The web app is fully
   capable of real LaTeX rendering and the backend already sends the raw
   text needed for it.
2. **Replace the backend's PNG pipeline entirely** (drop `render_latex_png`)
   - rejected. Telegram has no way to render LaTeX itself and depends on
   this exact pipeline for `/answer`, `/elaborate`, and the ask-chat replies
   it already sends as photos. Scope this to the web frontend's own
   rendering choice; change nothing about what the backend sends.
3. **One combined "explanation" field holding formula + example together,
   free-form** (simplest) vs. **separate structured fields** (`summary` for
   the stated rule, `examples: list[str]` for 0+ worked illustrations) -
   chose separate fields, matching how the reference note visually separates
   the rule/theorem from its "Example:" block, and makes the frontend's
   rendering (regular prose vs. a visually distinct worked-example block)
   straightforward without re-parsing free text to find the boundary.
4. **Force every section to have exactly N examples** - rejected, consistent
   with this project's own established and explicitly user-confirmed
   philosophy (English notes' comment: "over-constraining this produced
   correct but needlessly rigid... notes - confirmed directly by the user").
   Left to the model's judgment per subtopic and grade level, same as English.

## Implementation

### 1. Shared frontend LaTeX rendering (KaTeX)

- Add `katex` to `frontend/package.json` (lightweight, the standard choice -
  Khan Academy, Jupyter, etc. - full LaTeX math support including matrices/
  cases/aligned systems that mathtext cannot do).
- New `frontend/src/components/ui/MathText.tsx`: parses the SAME delimiters
  `exams/latex_render.py`'s `_BLOCK` regex already recognizes (`\[...\]`,
  `\(...\)`, `$$...$$`, `$...$`) out of a plain string, renders each span via
  `katex.renderToString` (`throwOnError: false`, so a construct KaTeX can't
  parse degrades to plain text instead of crashing the page - same
  graceful-degradation spirit as the backend's own PNG fallback), and runs
  the existing `**bold**` handling from `RichText.tsx` on the non-math spans
  so both keep working together in one component.
- Update every call site that currently branches on an `*_image_base64`
  field to render the raw text/LaTeX field through `MathText` instead, and
  drop the `<img>` branch for the web app (the image fields stay in the API
  responses themselves, since Telegram still consumes them):
  `NotesDetail.tsx` (key formulas/worked example - see section 2, these
  fields move to being per-section), `ElaboratePanel.tsx` (`content`),
  `AskChatPanel.tsx` (`reply`), `EsslceSession.tsx` and `PracticeSession.tsx`
  (`explanation`).

### 2. Per-topic worked examples for calculation-subject notes

`backend/notes/store.py`:
- New `CALC_UNIT_PROMPT` (parallel structure to the existing
  `ENGLISH_UNIT_PROMPT`, not a generic add-on to `UNIT_PROMPT` - same lesson
  this file already learned and documented). Per section:
  - `"summary"`: state the actual formula/theorem/rule for this subtopic
    (as LaTeX) and explain what it means and when to use it - not just a
    vague conceptual description.
  - `"examples"`: a list of 0+ fully worked examples specific to THIS
    subtopic's own formula, each a self-contained string with step-by-step
    LaTeX (matching the reference note's style - intermediate algebra shown,
    not just the final answer). The model decides how many, including zero
    for a subtopic that's a pure definition with nothing to work through -
    never padded.
  - Same `heading`/`level`/`source_index`/`supporting_quote` fields as today,
    so numbering, citation, and quote-verification (`_numbered_sections`)
    need only one small change: carry the new `examples` list through
    unvalidated (it's elaboration grounded in the section's own already-
    verified quote, the same trust level English's rich `summary` text
    already gets - not independently re-verified).
- `generate_note`: select `CALC_UNIT_PROMPT` for `subject in
  CALCULATION_SUBJECTS`, the same `is_english`-style branch already used for
  `ENGLISH_UNIT_PROMPT`. Remove `CALC_SUPPLEMENT_PROMPT` and the unit-wide
  supplement call block entirely - fully superseded, not kept alongside.
- `backend/notes/models.py`: drop the now-unused `key_formulas`/
  `worked_example` columns (a new Alembic migration, `alembic revision
  --autogenerate`, reviewed before applying - same safe workflow already
  used for the cross-check columns migration). `sections` (JSON) needs no
  migration - it already stores whatever keys `_numbered_sections` puts in
  it, so `examples` just becomes a new key in existing dicts.
- `backend/api/routes_notes.py`: `NoteResponse`'s per-section schema gains
  `examples: list[str]`; drop `key_formulas`/`formulas_image_base64`/
  `worked_example`/`worked_example_image_base64` (superseded by per-section
  examples - no caller needs the old unit-wide fields once the frontend
  moves to rendering per-section examples).
- Existing cached `StudyNote` rows predate this schema and won't have
  `examples` - since this is purely a regenerable cache (same as every other
  *_elaboration/cache table in this project), clear the `study_notes` table
  rather than trying to migrate old rows' content; the next request for any
  unit just regenerates it under the new prompt.

### 3. Generalize "examples help" to every subject, not just calculation ones

`UNIT_PROMPT` (the generic, non-English, non-calculation path - biology,
chemistry's conceptual topics, history, etc.) gets the same modest
permission `ENGLISH_UNIT_PROMPT` already has: the `summary` field's own
description explicitly invites a brief concrete illustration where one
clarifies the concept, left to the model's judgment, never a forced
addition - consistent with the "don't over-constrain" lesson applied
throughout. This subject group doesn't get a separate `examples` list field
(no formula to work through step-by-step), just richer prose where it helps.

## Verification

- Run the backend test suite (`backend/test/test_notes.py`), updating its
  assertions for the removed `key_formulas`/`worked_example` fields and the
  new per-section `examples` field, same pattern as this session's other
  prompt-contract test updates.
- Generate a real note for a calculation-subject unit (e.g. mathematics,
  Grade 11/12 "Sequences and Series" if it's in the corpus, or whatever unit
  is available) against the real database and a real LLM call, the same
  direct-against-production verification technique used throughout this
  session, and read the actual output for whether each subtopic's own
  formula and example line up.
- `npm run build` + `npx tsc -b --noEmit` on the frontend to confirm the new
  `MathText` component and its call-site updates compile clean.
- Manually open a calculation-subject note, an elaborate panel, and an
  ESSLCE answer explanation in the dev server to visually confirm KaTeX
  renders correctly (including at least one case/matrix construct mathtext
  couldn't handle, to confirm the actual improvement).
