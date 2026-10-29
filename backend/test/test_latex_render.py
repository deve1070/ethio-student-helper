"""Test of exams/latex_render.py: real failure modes found testing against actual AI-derived explanations
(not synthetic edge cases) - a double-escaped newline from an LLM's JSON output, \\begin{aligned} (mathtext
has no environment support at all), and matplotlib's own auto-wrap silently corrupting a long math block.
Run from backend/:   python test/test_latex_render.py"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exams.latex_render import render_latex_png

# ---- 1. a double-escaped newline (literal backslash+n, not a real newline char) is recovered -------------------
broken = r"\[a=1\]\n\[b=2\]"  # exactly what an LLM produced once: JSON "\\n" decodes to this, not "\n"
assert render_latex_png(broken) is not None

# a REAL latex command starting with \n (not a stray newline) must NOT be mangled
real_command = r"\[x \neq y\]"
assert render_latex_png(real_command) is not None

# ---- 2. \begin{aligned} is expanded into separate renderable lines, not left to mathtext (which has no
#         environment support and silently prints it as broken literal text instead of raising) ----------------
aligned = r"\[\begin{aligned} n=1 &: a_1 = -1,\\ n=2 &: a_2 = 1. \end{aligned}\]"
assert render_latex_png(aligned) is not None

# ---- 3. a genuinely unsupported environment (cases/array/...) cleanly falls back to None, never a
#         garbled image. matrix/pmatrix/bmatrix/vmatrix/Vmatrix are a DIFFERENT case - see test 11 below:
#         they're flattened to a single-line literal and DO render, not left unsupported ------------------
cases = r"\[f(x)=\begin{cases}1 & x>0\\ 0 & x\le 0\end{cases}\]"
assert render_latex_png(cases) is None

# ---- 4. common commands mathtext doesn't support get a safe substitution instead of failing --------------------
for text in (r"\[\displaystyle \frac{1}{2}\]", r"\[\boxed{42}\]", r"\[p \iff q\]", r"\[\bigl(x\bigr)\]"):
    assert render_latex_png(text) is not None, text

# ---- 5. a long single-line math block isn't corrupted by matplotlib's own auto-wrap (confirmed bug: with
#         wrap=True, a long $...$ block gets cut in half at the figure edge and mathtext silently prints
#         the broken half as literal text rather than raising) ---------------------------------------------------
long_line = r"\[" + " + ".join(f"x_{{{i}}}" for i in range(40)) + r" = 0\]"
assert render_latex_png(long_line) is not None

# ---- 6. empty / no-math input ------------------------------------------------------------------------------------
assert render_latex_png("") is None
assert render_latex_png("just plain narration, no math at all") is not None

# ---- 7. $$...$$ (Markdown-flavored LaTeX some prompts don't explicitly rule out, e.g. notes/store.py's
#         CALC_SUPPLEMENT_PROMPT) renders instead of mathtext choking on the literal leftover $$ - found
#         for real from a live /v1/notes/note response, not a hypothetical ---------------------------------------
dollar_block = r"$$n(A\cup B)=n(A)+n(B)-n(A\cap B)$$"
assert render_latex_png(dollar_block) is not None
# a mix of \[...\] and $$...$$ in the same text (plausible if an LLM is inconsistent within one reply)
mixed = r"\[x+y=1\] and also $$x-y=2$$"
assert render_latex_png(mixed) is not None
# bare single $...$ (inline-math Markdown convention) also renders
assert render_latex_png(r"The result is $x=2$.") is not None

# ---- 8. \begin{align*} (not just \begin{aligned}) is recognized, and a BARE align block with no
#         \[...\]/$$...$$ wrapper at all still renders as math instead of leaking through as literal
#         "\begin{align*}" text - found for real from a live /v1/notes/note worked example ----------------------
assert render_latex_png(r"\[\begin{align*} a &= 1\\ &= 2 \end{align*}\]") is not None  # delimited, "align*"
bare_align = "Step 4:\n\\begin{align*}\nn(A\\cap B) &= 80 - 70 \\\\\n&= 10.\n\\end{align*}\nDone."
assert render_latex_png(bare_align) is not None
from exams.latex_render import _to_mathtext
mt = _to_mathtext(bare_align)
assert r"\begin{align*}" not in mt and r"\end{align*}" not in mt, mt  # actually expanded, not left literal
assert "$n(A\\cap B) = 80 - 70$" in mt, mt  # expanded into its own real math line

# ---- 9. wrap_as_math: a standalone formula fragment with NO delimiter at all (common for an isolated
#         "key formula", unlike a worked example where narration forces one) still renders as math,
#         instead of literal backslash-command text with nothing to mark it as math at all - confirmed
#         for real from a live /v1/notes/note response (`n\left(A \cup B\right)=...` shown as literal text)
from exams.latex_render import wrap_as_math

bare_formula = r"n\left(A \cup B\right)=n\left(A\right)+n\left(B\right)-n\left(A \cap B\right)"
assert wrap_as_math(bare_formula) == f"\\[{bare_formula}\\]"
assert render_latex_png(wrap_as_math(bare_formula)) is not None

# an already-delimited formula is unwrapped and rewrapped once, never doubled
for already in (r"\[x=1\]", r"\(x=1\)", r"$$x=1$$", r"$x=1$"):
    assert wrap_as_math(already) == r"\[x=1\]", already

# ---- 10. a step label ("**Problem:**" / "\textbf{Answer:}") renders genuinely bold - confirmed directly
#          that \mathbf{\text{...}} silently renders at REGULAR weight despite the \mathbf wrapper (\text{}
#          resets the font inside it), so the conversion must use bare \mathbf{...}, not the more "obvious"
#          nested form -----------------------------------------------------------------------------------------
from exams.latex_render import _to_mathtext

assert _to_mathtext("**Problem:** Let A and B be sets.") == r"$\mathbf{Problem:}$ Let A and B be sets."
assert _to_mathtext(r"\textbf{Answer:} 10.") == r"$\mathbf{Answer:}$ 10."
# a multi-word bold phrase keeps its spaces (escaped, or mathtext collapses them) and still renders
multiword = _to_mathtext("**Solution (step-by-step):** details follow")
assert multiword == r"$\mathbf{Solution\ (step-by-step):}$ details follow", multiword
assert render_latex_png("**Problem:** Let A and B be two finite sets.") is not None

# ---- 11. matrix/pmatrix/bmatrix/vmatrix/Vmatrix: mathtext has no 2D grid layout at all, but a
# determinant/matrix is common in real ESSLCE linear-algebra solutions and appears INLINE, mixed with
# surrounding scalar math - confirmed for real from a live explanation that leaked raw "\begin{vmatrix}"
# text to a student. Flattened to a single-line, comma/semicolon literal (MATLAB/Octave's own convention
# for a one-line matrix) instead of a 2D grid, which stays inline and actually renders -------------------
det_3x3 = (
    r"\[ \det(A)=\begin{vmatrix}3 & 1 & 1\\ 2 & -1 & 1\\ 0 & 1 & 3\end{vmatrix} \]"
    r"\[ =3\begin{vmatrix}-1 & 1\\ 1 & 3\end{vmatrix}-1\begin{vmatrix}2 & 1\\ 0 & 3\end{vmatrix}"
    r"+1\begin{vmatrix}2 & -1\\ 0 & 1\end{vmatrix} \]"
)
mt = _to_mathtext(det_3x3)
assert r"\begin{vmatrix}" not in mt and r"\end{vmatrix}" not in mt, mt  # actually expanded, not left literal
assert "|3,1,1;2,-1,1;0,1,3|" in mt, mt  # entries comma-separated (a bare space collapses in mathtext)
assert render_latex_png(det_3x3) is not None
# each bracket type renders its own real delimiter character, not a generic placeholder
assert "(2,1;3,4)" in _to_mathtext(r"\[\begin{pmatrix}2 & 1\\ 3 & 4\end{pmatrix}\]")
assert "[2,1;3,4]" in _to_mathtext(r"\[\begin{bmatrix}2 & 1\\ 3 & 4\end{bmatrix}\]")

print("LATEX RENDER TESTS PASSED")
