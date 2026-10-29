"""Renders a calculation-subject explanation (plain narration mixed with LaTeX math blocks, as written by
exams.store.DERIVE_PROMPT) into a single PNG, so a Telegram text message doesn't show raw "\\[ ... \\]"
markup to a student. Uses matplotlib's mathtext dialect - no system LaTeX install required - which covers
common math notation but not every LaTeX construct (e.g. \\begin{cases}); render_latex_png returns None on
anything it can't render, and the caller falls back to plain text rather than showing a broken image."""

import re

import matplotlib

matplotlib.use("Agg")  # headless: no display server, no GUI backend needed on a server process
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

# \[...\] / \(...\) (the delimiters exams.store's own prompts ask for) are listed first so they're tried
# before the $$.../$...$ alternatives at the same position; $$...$$ is listed before bare $...$ so a
# doubled delimiter (an LLM writing Markdown-flavored LaTeX instead of what was asked for) is consumed as
# one block, not matched as two separate empty-then-malformed single-$ spans (which mathtext can't parse
# at all - it raises "Expected end of text, found '$'" on the literal leftover $$).
_BLOCK = re.compile(r"\\\[(.*?)\\\]|\\\((.*?)\\\)|\$\$(.*?)\$\$|\$(.*?)\$", re.S)
# \1 backreferences the opened name so begin/end must match - covers "aligned", "align", and "align*"
# (all equally common step-by-step-derivation environments an LLM reaches for) as one pattern.
_ALIGNED = re.compile(r"\\begin\{(aligned|align\*?)\}(.*?)\\end\{\1\}", re.S)
# matrix/pmatrix/bmatrix/vmatrix/Vmatrix - the standard amsmath matrix environments. mathtext has NO
# matrix/grid-layout support at all (confirmed directly, not assumed - it's the "genuinely unsupported
# environment" matrix/cases case this module's own tests exercise), but a determinant or matrix is
# common in real ESSLCE linear-algebra worked solutions (e.g. a 3x3 determinant expanded by cofactors),
# and it appears INLINE, mixed with surrounding scalar math ("det(A) = <matrix> = 3*<2x2 matrix> - ..."),
# not as its own isolated block - so a true 2D grid isn't the fix even where one exists. Flattening it
# instead, entries space-separated within a row and rows semicolon-separated, matches how MATLAB/Octave
# themselves write a matrix literal on one line - a correct, unambiguous, widely recognized notation that
# stays within what a single mathtext "$...$" span can actually typeset.
_MATRIX = re.compile(r"\\begin\{(matrix|pmatrix|bmatrix|vmatrix|Vmatrix)\}(.*?)\\end\{\1\}", re.S)
_MATRIX_BRACKETS = {
    "matrix": ("", ""), "pmatrix": ("(", ")"), "bmatrix": ("[", "]"),
    "vmatrix": ("|", "|"), "Vmatrix": ("\u2016", "\u2016"),
}
# An LLM's raw JSON output sometimes double-escapes a backslash before a literal newline it meant to
# write (JSON text "\\n" decodes to the two characters backslash+n, not an actual newline) - but a REAL
# LaTeX command starting "\n" (\neq, \nabla, \notin, ...) is always followed by more letters. Only
# collapse the former: a bare "\n" not followed by another letter.
_DOUBLE_ESCAPED_NEWLINE = re.compile(r"\\n(?![a-zA-Z])")
# Common commands mathtext genuinely doesn't support, each with a safe substitution that preserves the
# math (not a guess - \Leftrightarrow and plain parens are confirmed mathtext-renderable): dropping
# \displaystyle/\bigl/\bigr changes only size/style, never meaning; \boxed{x} keeps its content, loses
# the box.
_SIMPLE_SUBSTITUTIONS = [
    (re.compile(r"\\displaystyle\s*"), ""),
    (re.compile(r"\\boxed\{(.*?)\}"), r"\1"),
    (re.compile(r"\\iff\b"), r"\\Leftrightarrow"),
    (re.compile(r"\\bigl|\\bigr"), ""),
]

# A step label ("**Problem:**", "\textbf{Answer:}") should look visually distinct from the step's own
# content - without this, exams.store's worked-example prompts produce an image where every line is the
# same weight, so a reader can't tell a step header from the math/explanation under it at a glance.
_BOLD_STAR = re.compile(r"\*\*(.+?)\*\*", re.S)
_BOLD_TEXTBF = re.compile(r"\\textbf\{(.*?)\}", re.S)


def _bold_math(phrase: str) -> str:
    """Wraps `phrase` as a bold-weight mathtext span. Confirmed directly (not assumed) that bare
    \\mathbf{...} renders genuinely bold, while the seemingly-equivalent \\mathbf{\\text{...}} silently
    renders at REGULAR weight - \\text{} resets the font inside \\mathbf{}'s own styling. Spaces must be
    escaped (\\ ) or mathtext collapses them; underscore/caret are escaped too since they trigger
    subscript/superscript parsing left bare, which a plain label was never meant to invoke."""
    escaped = phrase.replace(" ", r"\ ").replace("_", r"\_").replace("^", r"\^")
    return f"$\\mathbf{{{escaped}}}$"


_TOKEN = re.compile(r"\$[^$]*\$|\S+")


def _wrap(mathtext: str, max_chars: int) -> list[str]:
    """Greedy word-wrap to `max_chars` per line, treating each $...$ span as one unbreakable token (its
    inner spaces are part of the equation, not word boundaries). Without this, a long narration sentence
    with no author-inserted newline stays one unbroken line; `render_latex_png`'s bbox_inches="tight" then
    expands the saved PNG to that line's full width at a fixed font size, so once a chat bubble or phone
    screen scales the image down to its own width, the font shrinks down with it - sometimes to the point
    of being unreadable. Wrapping bounds every line to a predictable character count, which bounds the
    image's aspect ratio and keeps the font legible after that same downscale."""
    out = []
    for raw_line in mathtext.splitlines():
        tokens = _TOKEN.findall(raw_line)
        if not tokens:
            out.append("")
            continue
        line = tokens[0]
        for tok in tokens[1:]:
            if len(line) + 1 + len(tok) <= max_chars:
                line += " " + tok
            else:
                out.append(line)
                line = tok
        out.append(line)
    return out


def _expand_aligned(m: re.Match) -> str:
    """mathtext has no \\begin{aligned}/align/align* support at all, but it's common step-by-step-
    derivation content worth rendering rather than discarding: turn each \\\\-separated row into its own
    already-$-wrapped math line, dropping the &-alignment markers mathtext also doesn't understand.

    Wrapping happens HERE (not left to `repl` below) because this substitution runs over the FULL text,
    before block-delimiter detection - an LLM sometimes writes a bare align block with no surrounding
    \\[...\\]/$$...$$ wrapper at all (seen for real from a live /v1/notes/note response), and that block
    would otherwise never reach `repl` to get wrapped, leaking through as literal "\\begin{align*}" text
    instead of rendering. `repl` detects a line that already starts/ends with "$" and leaves it alone, so
    a block that genuinely IS inside \\[...\\] isn't double-wrapped into "$$...$$" by this change."""
    rows = m.group(2).split("\\\\")
    rows = [row.replace("&", "").strip() for row in rows]
    return "\n".join(f"${r}$" for r in rows if r)


def _expand_matrix(m: re.Match) -> str:
    """Flattens one matrix/determinant environment to a single-line MATLAB-style literal - see _MATRIX's
    own comment for why a 2D grid isn't the fix here. Entries are comma-separated, not space-separated:
    mathtext collapses a bare space in math mode (confirmed directly - the same reason _bold_math escapes
    its own spaces), so "3 1 1" silently became the unreadable, ambiguous "311" when first tried; a comma
    stays visible regardless of surrounding whitespace, so "3,1,1" can never be misread as a single
    three-digit entry. Runs INLINE within whatever math it's embedded in (unlike _expand_aligned, which
    replaces a whole line) - the result is substituted back in place, still inside its enclosing
    \\[...\\]/$...$ block, not wrapped on its own."""
    env = m.group(1)
    rows = [r.strip() for r in m.group(2).split("\\\\") if r.strip()]
    row_texts = [",".join(c.strip() for c in row.split("&")) for row in rows]
    left, right = _MATRIX_BRACKETS.get(env, ("", ""))
    return f"{left}{';'.join(row_texts)}{right}"


def _to_mathtext(text: str) -> str:
    """\\[ ... \\] / \\( ... \\) -> $...$ (matplotlib's mathtext delimiter). Leaves plain narration untouched.
    Raises ValueError if an unsupported LaTeX environment (cases, array, ...) remains after expanding the
    ones we do handle (aligned/align/align*, matrix/pmatrix/bmatrix/vmatrix/Vmatrix) - mathtext doesn't
    raise on these itself, it silently prints the raw tokens as garbled literal text, so this check is
    what actually catches the failure."""
    text = _DOUBLE_ESCAPED_NEWLINE.sub("\n", text)
    for pattern, replacement in _SIMPLE_SUBSTITUTIONS:
        text = pattern.sub(replacement, text)
    text = _BOLD_STAR.sub(lambda m: _bold_math(m.group(1)), text)
    text = _BOLD_TEXTBF.sub(lambda m: _bold_math(m.group(1)), text)
    text = _MATRIX.sub(_expand_matrix, text)
    text = _ALIGNED.sub(_expand_aligned, text)
    if "\\begin{" in text:
        raise ValueError(f"unsupported LaTeX environment: {text[:60]!r}")

    def repl(m: re.Match) -> str:
        inner = (m.group(1) or m.group(2) or m.group(3) or m.group(4)).strip()
        return "\n".join(
            ln if not ln.strip() or (ln.startswith("$") and ln.endswith("$")) else f"${ln}$"
            for ln in inner.split("\n")
        )

    return _BLOCK.sub(repl, text)


_OUTER_WRAP = re.compile(r"^\s*(?:\\\[(.*)\\\]|\\\((.*)\\\)|\$\$(.*)\$\$|\$(.*)\$)\s*$", re.S)


def wrap_as_math(formula: str) -> str:
    """Wraps a string KNOWN to be a single pure math expression, not narration (e.g. one entry of an
    LLM's "key_formulas" list) in \\[...\\] so it flows through _to_mathtext's usual pipeline - stripping
    any \\[...\\]/\\(...\\)/$$...$$/$...$ wrapper the author may already have added first, so it's never
    double-wrapped. An isolated formula fragment often comes with NO delimiter at all (unlike a worked
    example, which has narration prose forcing the author to mark where the math starts and ends) -
    render_latex_png on its own only recognizes delimited spans, so an undelimited fragment would
    otherwise render as literal backslash-command text instead of real math (confirmed for real: a
    "key_formulas" entry like `n\\left(A \\cup B\\right)=...` with no delimiter rendered as literal text)."""
    formula = formula.strip()
    m = _OUTER_WRAP.match(formula)
    inner = next((g for g in m.groups() if g is not None), formula) if m else formula
    return f"\\[{inner.strip()}\\]"


def render_latex_png(text: str, fontsize: int = 13, max_chars_per_line: int = 46) -> bytes | None:
    """PNG bytes of `text` with its LaTeX math blocks typeset, or None if matplotlib can't parse it
    (an unsupported construct, unbalanced delimiters, etc.) - never raises past this function."""
    if not text or not text.strip():
        return None
    try:
        mathtext = _to_mathtext(text)
        lines = _wrap(mathtext, max_chars_per_line) or [mathtext]
        width = max(5.0, 0.11 * max(len(ln) for ln in lines))
        height = max(1.0, 0.45 * len(lines))
        fig = Figure(figsize=(width, height), dpi=160)
        FigureCanvasAgg(fig)  # attaches the Agg canvas to fig; fig.savefig uses it directly
        # fig.text(), not ax.text(): an Axes' own bbox (even with axis("off")) still counts toward
        # bbox_inches="tight"'s crop, pinning the saved image to our guessed `width` above however
        # compactly the math actually renders (a stacked \frac is far narrower than its raw character
        # count). A bare Figure.text() has no axes bbox to compete with, so "tight" crops to the real
        # rendered extent of the text itself.
        fig.text(
            0.01, 0.98, "\n".join(lines),
            va="top", ha="left", fontsize=fontsize,
            # NOT wrap=True: `_wrap` already split the text into lines itself, token-aware (never inside
            # a $...$ span) - matplotlib's own auto-wrap doesn't know that boundary and will cut a long
            # line (and the math block inside it) in half at the figure edge, which mathtext can't parse
            # (and does NOT raise on - it silently prints the broken half as literal text).
        )
        import io

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
        return buf.getvalue()
    except Exception:  # noqa: BLE001 - mathtext rejects some LaTeX constructs; fall back to plain text
        return None
