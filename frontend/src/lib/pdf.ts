/** html2canvas's own color parser has no support at all for CSS Color 4 functions - oklch(), lab(),
 * lch(), color-mix(). Tailwind v4 (this app's `@tailwindcss/vite`) defines every color token as
 * oklch(). html2canvas rasterizes the page by cloning it into an offscreen iframe first; the clone
 * hits the unsupported color on the first element it parses, and depending where that throw lands
 * in its internal (non-rejecting) pipeline, `doc.html()`'s callback can simply never fire -
 * confirmed live: "Preparing..." forever, no error, no download, the main thread pinned the whole
 * time it spends trying.
 *
 * Three things had to be true at once for this to actually work, each only found by testing
 * against the real built app rather than reasoning about it, since each one looked sufficient on
 * its own and wasn't:
 *   1. The color itself has to become a plain rgb()/rgba() string - see toRgb() below for why
 *      canvas's own fillStyle getter does NOT reliably do that.
 *   2. Nested calls like Tailwind's `color-mix(in oklab, color-mix(...) <pct>%, transparent)` need
 *      their own closing paren found by counting depth, not a regex with a fixed nesting limit -
 *      see stripUnsupportedColorFunctions() below.
 *   3. The fix has to land somewhere html2canvas's clone actually reads FROM - see
 *      fixStylesheetColors() below for why mutating the live CSSOM in place isn't that place for a
 *      production build's `<link rel="stylesheet">` (only a `<style>` tag's clone is rebuilt from
 *      its own current rules; a cloned `<link>` just re-fetches the original file by its href). */
// A 1x1 canvas pixel, not fillStyle's own getter, is what actually forces a plain rgb()/rgba()
// result. Confirmed live that fillStyle's round trip does NOT downgrade oklch()/oklab() colors at
// all - modern Chromium's canvas natively supports those color spaces, so reading fillStyle back
// just re-serializes the same color space with normalized number formatting (oklch(97.1% ...) ->
// oklch(0.971 ...), still oklch) - the exact function name html2canvas can't parse survives
// completely untouched. Painting the color onto a real pixel and reading getImageData()'s bytes
// instead is reliable because THAT output format is fixed by spec: a Uint8ClampedArray of 0-255
// integers per channel, never any CSS color syntax, regardless of what color space the input used.
let _pixelCanvas: HTMLCanvasElement | null = null
let _pixelCtx: CanvasRenderingContext2D | null = null

function toRgb(cssColor: string): string {
  _pixelCanvas ??= Object.assign(document.createElement("canvas"), { width: 1, height: 1 })
  _pixelCtx ??= _pixelCanvas.getContext("2d")
  if (!_pixelCtx) return cssColor
  _pixelCtx.clearRect(0, 0, 1, 1)
  _pixelCtx.fillStyle = cssColor
  _pixelCtx.fillRect(0, 0, 1, 1)
  const [r, g, b, a] = _pixelCtx.getImageData(0, 0, 1, 1).data
  return a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${(a / 255).toFixed(3)})`
}

const COLOR_FN_START = /\b(?:oklch|oklab|lch|lab|color-mix)\(/gi

/** Replaces every oklch()/oklab()/lch()/lab()/color-mix() call in text with a canvas-resolved
 * rgb() equivalent - matching the CALL'S OWN PARENS BY DEPTH, not a regex with a fixed nesting
 * limit. A regex allowing only one level of nested parens (`[^()]*(?:\([^()]*\)[^()]*)*`) is NOT
 * enough here: confirmed live against this app's real production CSS that Tailwind v4's opacity-
 * modifier output nests color-mix() calls inside each other (e.g.
 * `color-mix(in oklab, color-mix(in srgb, ...) <pct>%, transparent)`), and a one-level regex
 * matches only partway into a two-level call, leaving its own tail - and the oklch()/oklab() still
 * inside that tail - completely unmatched and unreplaced. Walking forward from each function
 * name and counting '(' / ')' to find the call's own true closing paren handles any nesting depth,
 * because it's counting actual parens instead of guessing how many levels a pattern should allow. */
function stripUnsupportedColorFunctions(text: string): string {
  let out = ""
  let last = 0
  COLOR_FN_START.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = COLOR_FN_START.exec(text))) {
    const openParen = m.index + m[0].length - 1
    let depth = 1
    let i = openParen + 1
    while (i < text.length && depth > 0) {
      if (text[i] === "(") depth++
      else if (text[i] === ")") depth--
      i++
    }
    out += text.slice(last, m.index) + toRgb(text.slice(m.index, i))
    last = i
    COLOR_FN_START.lastIndex = i
  }
  return out + text.slice(last)
}

/** Replaces every stylesheet-owning element with an equivalent inline <style> tag holding a
 * color-fixed copy of its rules - NOT a CSSOM mutation of the existing sheet in place.
 *
 * Mutating an existing sheet's rules via deleteRule()/insertRule() (the first approach tried
 * here) never actually fixed anything in production, and the reason is specific to how
 * html2canvas clones the page for rasterizing: its DocumentCloner special-cases <style> elements
 * (reading their OWN sheet.cssRules and rebuilding the clone's textContent from that - this path
 * WOULD have picked up a CSSOM-level fix) but falls through to a generic shallow cloneNode() for
 * every other element type, <link rel="stylesheet"> included. A cloned <link> still carries its
 * original href, so once it's inserted into html2canvas's cloning iframe the browser just
 * re-fetches the ORIGINAL, unpatched CSS file from the server - confirmed live: a stylesheet
 * verified completely clean of oklch()/oklab() in the live document, at the exact moment of the
 * capture, still produced "unsupported color function" inside html2canvas, because the fetch that
 * actually fed its clone never went through the live, patched CSSOM at all. Vite's production
 * build emits CSS as a `<link>` (a dev-mode run emits a `<style>` instead, which is why this bug
 * was inconsistent to reproduce depending on which build was under test).
 *
 * The only fix that works for both element types is to make sure a real <style> tag - with
 * already-fixed text - is what's actually in the DOM for html2canvas to find, instead of relying
 * on either a <link>'s clone or a <style>'s clone to reflect an in-place CSSOM edit correctly. */
function fixStylesheetColors(): () => void {
  const restores: Array<() => void> = []
  const sheets = [...document.styleSheets, ...(document.adoptedStyleSheets ?? [])]
  for (const sheet of sheets) {
    let rules: CSSRuleList
    try {
      rules = sheet.cssRules
    } catch {
      continue
    }
    const cssText = Array.from(rules, (r) => r.cssText).join("\n")
    if (
      !cssText.includes("oklch(") &&
      !cssText.includes("oklab(") &&
      !cssText.includes("lch(") &&
      !cssText.includes("lab(") &&
      !cssText.includes("color-mix(")
    ) {
      continue
    }
    const fixed = stripUnsupportedColorFunctions(cssText)
    const style = document.createElement("style")
    style.textContent = fixed
    const ownerNode = sheet.ownerNode
    if (ownerNode instanceof HTMLLinkElement) {
      // Disabling (not removing) keeps the original <link> in the DOM, at its original position,
      // the whole time - a clean, trivial restore, and no risk of a flash of unstyled content on
      // the live (off-screen, but still a real rendered element) page while the swap is in effect.
      ownerNode.disabled = true
      ownerNode.after(style)
      restores.push(() => {
        style.remove()
        ownerNode.disabled = false
      })
    } else if (ownerNode instanceof HTMLStyleElement) {
      const original = ownerNode.textContent
      ownerNode.textContent = fixed
      restores.push(() => {
        ownerNode.textContent = original
      })
    }
    // A sheet with no ownerNode (e.g. one of document.adoptedStyleSheets) has nothing to swap -
    // there's no element for html2canvas to clone in the first place, so no fix is needed there.
  }
  return () => {
    for (const restore of restores) restore()
  }
}

/** Downloads a DOM element as a paginated PDF - entirely client-side, no backend involved (this
 * project just spent real effort keeping the Render free-tier backend's memory under its 512MB
 * ceiling; a server-side PDF render, especially one that would need to lay out LaTeX, would undo
 * that).
 *
 * Calls html2canvas directly and slices the resulting canvas into pages by hand, instead of going
 * through jsPDF's own `doc.html()` wrapper. `doc.html()` looks like it should handle pagination
 * for us, but its implementation (`jsPDFAPI.html`, in jspdf's own source) contains this line:
 * `options.html2canvas.canvas = options.html2canvas.canvas || this.canvas` - `this.canvas` is a
 * small canvas jsPDF keeps on the document instance for its own internal text-metrics use, sized
 * at the browser's default 300x150 unless something else resizes it. Since we never pass our own
 * `html2canvas.canvas`, jsPDF hands html2canvas THAT canvas as its render target; html2canvas's
 * `CanvasRenderer` only resizes the canvas it's given when the caller did NOT supply one
 * (`options.canvas ? options.canvas : document.createElement('canvas')`, followed by a resize
 * block guarded by `if (!options.canvas)`), so it silently renders the whole page into a
 * 300x150 target and reports success - confirmed live: `doc.html()`'s callback fires, a real PDF
 * saves, but every page in it is blank, because almost all of the actual content fell outside
 * that 300x150 canvas before jsPDF ever got to read it. Calling html2canvas(element, options)
 * ourselves never passes a `canvas` option, so it always takes the create-and-resize branch.
 *
 * This captures the element as a high-resolution image (`scale: 2`), not vector text - a real,
 * accepted tradeoff for a one-click download instead of the browser's own print-to-PDF (which
 * keeps the math as sharp, searchable vector text; see docs/dev_plans/notes_colors_and_pdf.md for
 * why the direct-download path was chosen anyway). The scale is high enough that the embedded
 * math still reads crisply at a normal reading/printing zoom, just not infinitely so.
 *
 * jsPDF and html2canvas are imported dynamically (not at module top level): this app has no
 * route-based code splitting at all yet, so a static import here would add their weight to EVERY
 * page's initial bundle, not just the one button that needs it - confirmed directly, the
 * production build's main chunk grew once jspdf/html2canvas were added. A dynamic import keeps
 * that weight out of the main bundle, fetched only the moment a student actually clicks
 * "Download PDF".
 *
 * Waits for document.fonts.ready first - KaTeX's math glyphs are web fonts, and capturing before
 * they've finished loading is a second, independent way to get a slow or visibly wrong render.
 * A 30s timeout guarantees the caller's awaited promise always settles - whatever else might still
 * go wrong on some student's content, "stuck on Preparing... forever with a frozen page" (the
 * un-caught, un-timed-out failure mode this replaces) must never be one of the possible outcomes. */
export async function downloadElementAsPdf(element: HTMLElement, filename: string): Promise<void> {
  const [{ jsPDF }, { default: html2canvas }] = await Promise.all([import("jspdf"), import("html2canvas")])
  await document.fonts.ready

  const restoreStylesheets = fixStylesheetColors()
  // Forces a synchronous style recalculation right now, before html2canvas's own
  // getComputedStyle() calls run. Confirmed live that without this, a known-good rewritten
  // stylesheet rule (patched correctly, verified clean, no leftover oklch() text anywhere in the
  // sheet) still gets served to getComputedStyle() as its OLD oklch() value, because mutating a
  // CSSStyleSheet via deleteRule()/insertRule() invalidates custom-property resolution lazily -
  // the browser doesn't necessarily finish recomputing every affected element's style before the
  // next synchronous line of JS runs. Reading a layout-dependent property is what forces that
  // recalculation to actually happen now instead of whenever the browser would otherwise get to it.
  void document.body.offsetHeight
  try {
    const capture = html2canvas(element, {
      scale: 2,
      backgroundColor: "#ffffff",
      windowWidth: element.scrollWidth || 700,
    })

    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("PDF generation timed out - try again, or a shorter note")), 30000),
    )

    const rendered = await Promise.race([capture, timeout])

    const doc = new jsPDF({ unit: "pt", format: "a4" })
    const margin = 32
    const pageWidth = doc.internal.pageSize.getWidth() - margin * 2
    const pageHeight = doc.internal.pageSize.getHeight() - margin * 2
    // How many of the canvas's own pixels correspond to one PDF page's height, at the scale
    // that maps the canvas's full width onto pageWidth.
    const pxPerPageHeight = (pageHeight / pageWidth) * rendered.width

    const slice = document.createElement("canvas")
    slice.width = rendered.width
    const sliceCtx = slice.getContext("2d")
    if (!sliceCtx) throw new Error("Couldn't generate the PDF. Please try again.")

    for (let renderedY = 0; renderedY < rendered.height; renderedY += pxPerPageHeight) {
      const sliceHeightPx = Math.min(pxPerPageHeight, rendered.height - renderedY)
      slice.height = sliceHeightPx
      sliceCtx.clearRect(0, 0, slice.width, sliceHeightPx)
      sliceCtx.drawImage(rendered, 0, renderedY, rendered.width, sliceHeightPx, 0, 0, rendered.width, sliceHeightPx)
      if (renderedY > 0) doc.addPage()
      doc.addImage(
        slice.toDataURL("image/jpeg", 0.92),
        "JPEG",
        margin,
        margin,
        pageWidth,
        (sliceHeightPx / rendered.width) * pageWidth,
      )
    }

    doc.save(filename)
  } finally {
    restoreStylesheets()
  }
}
