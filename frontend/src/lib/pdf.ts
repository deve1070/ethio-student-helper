/** Downloads a DOM element as a paginated PDF - entirely client-side, no backend involved (this
 * project just spent real effort keeping the Render free-tier backend's memory under its 512MB
 * ceiling; a server-side PDF render, especially one that would need to lay out LaTeX, would undo
 * that). Uses jsPDF's own `doc.html()`, which handles multi-page pagination internally (via
 * html2canvas) rather than hand-slicing one tall canvas image into pages.
 *
 * This captures the element as a high-resolution image (`scale: 2`), not vector text - a real,
 * accepted tradeoff for a one-click download instead of the browser's own print-to-PDF (which
 * keeps the math as sharp, searchable vector text; see docs/dev_plans/notes_colors_and_pdf.md for
 * why the direct-download path was chosen anyway). The scale is high enough that the embedded
 * math still reads crisply at a normal reading/printing zoom, just not infinitely so.
 *
 * jsPDF is imported dynamically (not at module top level): this app has no route-based code
 * splitting at all yet, so a static import here would add jsPDF's own weight to EVERY page's
 * initial bundle, not just the one button that needs it - confirmed directly, the production
 * build's main chunk grew once jspdf/html2canvas were added. A dynamic import keeps that weight
 * out of the main bundle, fetched only the moment a student actually clicks "Download PDF". */
export async function downloadElementAsPdf(element: HTMLElement, filename: string): Promise<void> {
  const { jsPDF } = await import("jspdf")
  const doc = new jsPDF({ unit: "pt", format: "a4" })
  const margin = 32
  const pageWidth = doc.internal.pageSize.getWidth() - margin * 2
  return new Promise((resolve) => {
    doc.html(element, {
      x: margin,
      y: margin,
      width: pageWidth,
      windowWidth: element.scrollWidth || 700,
      html2canvas: { scale: 2 },
      callback: (d) => {
        d.save(filename)
        resolve()
      },
    })
  })
}
