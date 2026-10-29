import { chromium } from "playwright"
import { readFileSync } from "node:fs"

const TOKEN_FILE = "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/signup_resp.json"
const { access_token, user_id } = JSON.parse(readFileSync(TOKEN_FILE, "utf8"))
const SHOT_DIR = "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/shots"

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 400, height: 860 } })
page.on("pageerror", (e) => console.log("pageerror:", e.message))
page.on("console", (msg) => { if (msg.type() === "error") console.log("console.error:", msg.text()) })

await page.goto("http://localhost:5173/", { waitUntil: "networkidle" })
await page.evaluate(({ token, userId }) => {
  localStorage.setItem("esh_token", token)
  localStorage.setItem("esh_user_id", userId)
  localStorage.setItem("esh_grade", "12")
}, { token: access_token, userId: user_id })
await page.goto("http://localhost:5173/progress", { waitUntil: "networkidle" })
await page.waitForTimeout(1500)
await page.screenshot({ path: `${SHOT_DIR}/progress-practice-empty.png` })

await page.click('text=ESSLCE')
await page.waitForTimeout(1500)
await page.screenshot({ path: `${SHOT_DIR}/progress-esslce.png` })

// hover the trend chart to capture the tooltip in one shot too
const svg = page.locator("svg[aria-label='Accuracy over the last 7 days']")
const box = await svg.boundingBox()
if (box) await page.mouse.move(box.x + box.width - 15, box.y + box.height / 2)
await page.waitForTimeout(300)
await page.screenshot({ path: `${SHOT_DIR}/progress-esslce-hover.png` })

await browser.close()
console.log("done")

const browser2 = await chromium.launch()
const page2 = await browser2.newPage({ viewport: { width: 400, height: 860 } })
await page2.goto("http://localhost:5173/", { waitUntil: "networkidle" })
await page2.evaluate(({ token, userId }) => {
  localStorage.setItem("esh_token", token)
  localStorage.setItem("esh_user_id", userId)
  localStorage.setItem("esh_grade", "12")
}, { token: access_token, userId: user_id })
await page2.goto("http://localhost:5173/progress", { waitUntil: "networkidle" })
await page2.click('text=ESSLCE')
await page2.waitForTimeout(1200)
await page2.evaluate(() => window.scrollTo(0, document.body.scrollHeight))
await page2.locator("main").evaluate((el) => el.scrollTo(0, el.scrollHeight))
await page2.waitForTimeout(300)
await page2.screenshot({ path: `${SHOT_DIR}/progress-esslce-scrolled.png` })
await browser2.close()
