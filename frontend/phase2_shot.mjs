import { chromium } from "playwright"
import { readFileSync } from "node:fs"

const { access_token, user_id } = JSON.parse(readFileSync(
  "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/signup_resp.json", "utf8"
))
const SHOT_DIR = "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/shots"

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 400, height: 860 } })
page.on("pageerror", (e) => console.log("pageerror:", e.message))
page.on("console", (msg) => { if (msg.type() === "error") console.log("console.error:", msg.text()) })
page.on("dialog", async (d) => { console.log("dialog:", d.message()); await d.accept() })

await page.goto("http://localhost:5173/", { waitUntil: "networkidle" })
await page.evaluate(({ token, userId }) => {
  localStorage.setItem("esh_token", token)
  localStorage.setItem("esh_user_id", userId)
  localStorage.setItem("esh_grade", "12")
}, { token: access_token, userId: user_id })

// --- Mistakes page ---
await page.goto("http://localhost:5173/mistakes", { waitUntil: "networkidle" })
await page.waitForTimeout(800)
await page.click('text=ESSLCE')
await page.waitForTimeout(1200)
await page.screenshot({ path: `${SHOT_DIR}/mistakes-esslce.png` })

// --- Exam navigator: find a chemistry paper and start a mock exam ---
await page.goto("http://localhost:5173/esslce", { waitUntil: "networkidle" })
await page.waitForTimeout(500)
await page.click('text=Chemistry')
await page.waitForTimeout(800)
await page.screenshot({ path: `${SHOT_DIR}/esslce-modepicker.png` })
await page.click('text=Mock exam')
await page.waitForTimeout(800)
await page.screenshot({ path: `${SHOT_DIR}/esslce-papers.png` })
// click the first paper's "Start" / row
const firstPaperButton = page.locator("button, [role=button]").filter({ hasText: /Start|questions/i }).first()
await firstPaperButton.click()
await page.waitForTimeout(1200)
await page.screenshot({ path: `${SHOT_DIR}/exam-navigator-q1.png` })

// answer question 1
const opt = page.locator('[role="radio"]').first()
if (await opt.count()) {
  await opt.click()
  await page.waitForTimeout(1000)
  await page.screenshot({ path: `${SHOT_DIR}/exam-navigator-answered-q1.png` })
}

// flag question, jump to question 5 via navigator grid, answer it too
const flagBtn = page.locator("text=Mark for review")
if (await flagBtn.count()) await flagBtn.click()
await page.waitForTimeout(300)

const nav5 = page.locator("button", { hasText: "5" }).first()
if (await nav5.count()) {
  await nav5.click()
  await page.waitForTimeout(800)
  const opt5 = page.locator('[role="radio"]').nth(1)
  if (await opt5.count()) { await opt5.click(); await page.waitForTimeout(800) }
}
await page.screenshot({ path: `${SHOT_DIR}/exam-navigator-jumped.png` })

// jump back to q1 to see flag + answered state preserved
const nav1 = page.locator("button", { hasText: "1" }).first()
if (await nav1.count()) { await nav1.click(); await page.waitForTimeout(500) }
await page.screenshot({ path: `${SHOT_DIR}/exam-navigator-back-to-q1.png` })

await browser.close()
console.log("done")
