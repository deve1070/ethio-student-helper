# Notes: color-coded content types + PDF download

## Context

Two follow-up requests on the notes feature just shipped (real LaTeX via
KaTeX, per-topic worked examples - `docs/dev_plans/better_study_notes.md`):

1. Different parts of a note should look visually different so a student
   can skim and grasp a topic fast, without reading every word.
2. Students should be able to download a note as a PDF.

Confirmed via AskUserQuestion:
- Color should mean **content type**, consistently everywhere (an
  explanation always looks one way, a worked example always looks another),
  not a rotating per-section color with no fixed meaning.
- PDF export should be a **direct one-click file download**, not the
  browser's print dialog - accepting the stated tradeoff that a client-side
  "screenshot the page" library embeds the math as a (high-resolution)
  raster image rather than infinitely-sharp vector text, since generating it
  server-side would add real memory/CPU load on the Render free tier this
  project just spent significant effort keeping under its 512MB ceiling.

## Design

### 1. Content-type coloring

The actual content "kinds" already in the data, right now, are: unit
overview, a subtopic's explanation (`section.summary`), a worked example
(`section.examples[]`), and a citation line. Rather than inventing new
per-subject-specific styling logic, the cleanest version of "formulas and
examples look different from explanatory prose" falls out of two small,
generalizable changes:

- **`MathText.tsx`** (already shared by notes, elaborate, ask-about-this-
  question, exam answers, practice/mistakes feedback - see
  `docs/dev_plans/better_study_notes.md`): when it renders a BLOCK-mode
  LaTeX span (`\[...\]` or `$$...$$` - a formula standing on its own line,
  as opposed to `\(...\)`/`$...$` inline math woven into a sentence), wrap
  it in a distinct "formula card" (soft indigo background, centered,
  comfortable padding) instead of rendering it bare. This makes every
  stated formula/theorem in the app visually pop out from its surrounding
  prose, automatically, everywhere MathText is already used - not a notes-
  specific hack.
- **`NotesDetail.tsx`**'s existing per-example block (already visually
  separated with a plain `bg-zinc-50` box) gets a distinct second color
  (soft emerald) plus a small "Example" label, so a formula-card (indigo)
  and a worked-example block (emerald) are never confused with each other
  even when a worked example also contains its own formula.
- Section headings keep their current level-1/level-2 distinction
  (already-existing bold/indent styling) - not touched.

This gives exactly three consistent, meaningful colors app-wide: plain prose
(unstyled), a stated formula (indigo), a worked example (emerald) - matching
the "by content type, not by topic" decision, and reusable by every other
screen that already renders LaTeX-bearing text through `MathText`.

### 2. PDF download

New `frontend/src/lib/pdf.ts`: a small `downloadElementAsPdf(element,
filename)` helper using `jspdf`'s own `doc.html(element, {...})` method
(built on top of `html2canvas` internally, with jsPDF's own built-in multi-
page pagination - avoids hand-rolling canvas-slicing-per-page logic). Scale
set high enough (`html2canvas: { scale: 2 }`) that the embedded math stays
crisp at normal reading/printing zoom, even though it's a raster capture of
the rendered page rather than vector text.

`NotesDetail.tsx` gets a "Download PDF" button (next to the existing
"Practice this unit" button) that:
- Renders the note's overview + sections (including the new formula/example
  styling) into a ref'd container sized for a clean printed page (a fixed
  width, no app chrome/nav/buttons in the captured region - a separate,
  print-oriented layout of the SAME data already in state, not the on-
  screen interactive view itself).
- Calls `downloadElementAsPdf(ref.current, "<subject>-<unit>.pdf")`.

No backend changes at all - this is why the print-based approach was
offered as the lower-risk default; going with a direct download instead
only costs a new frontend dependency and a flatter (not infinitely crisp)
math rendering in the exported file, never backend memory/CPU.

## Alternatives considered

1. **Browser print-to-PDF** (`window.print()` scoped via CSS, user picks
   "Save as PDF") - the tradeoff-free option (keeps vector math, zero new
   dependencies) - not chosen per the user's explicit preference for a
   direct one-click download without the print dialog's extra UI.
2. **Server-side PDF generation** (e.g. a headless-browser or weasyprint
   render) - rejected: real memory/CPU cost on a free-tier instance this
   project just spent a long session getting under 512MB; the whole point
   of today's "stay client-side" choice.
3. **Per-section rotating colors** (a different accent per topic, no fixed
   meaning) - rejected per the user's own choice above; content-type-based
   coloring chosen instead.

## Implementation

- `frontend/package.json`: add `jspdf` and `html2canvas` (jsPDF's `doc.html`
  pulls in `html2canvas` as its own dependency, but installing it directly
  too keeps the version pinned/visible rather than implicit).
- `frontend/src/components/ui/MathText.tsx`: wrap block-mode KaTeX output in
  a styled container (indigo-tinted card) instead of a bare `<span>`;
  inline-mode output stays exactly as it is now.
- `frontend/src/lib/pdf.ts` (new): `downloadElementAsPdf(element, filename)`.
- `frontend/src/pages/notes/NotesDetail.tsx`: give the worked-example block
  its own emerald styling + "Example" label; add a hidden/off-screen print-
  layout container (ref'd) mirroring the visible note content in a PDF-
  friendly fixed width; add the "Download PDF" button wiring it to
  `downloadElementAsPdf`.

## Verification

- `npx tsc -b --noEmit` + `npm run build` after the changes.
- Manually open a calculation-subject note in the dev server (e.g.
  mathematics, Grade 12, "Unit 1: Sequences and Series" - already confirmed
  rich content exists for this unit from the previous session's real
  generation test) and visually confirm: block formulas show in the new
  indigo card, worked examples show in emerald with their label, and
  "Download PDF" produces a readable, correctly-paginated PDF with the math
  rendered crisply at a normal zoom level.
