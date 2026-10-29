import { chromium } from "playwright"
import { readFileSync } from "node:fs"
const { access_token, user_id } = JSON.parse(readFileSync(
  "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/dash_signup.json", "utf8"
))
const SHOT_DIR = "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/shots"
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 400, height: 860 } })
const errors = []
page.on("pageerror", (e) => errors.push("pageerror: " + e.message))
page.on("console", (msg) => { if (msg.type() === "error") errors.push("console.error: " + msg.text()) })

await page.goto("http://localhost:5173/", { waitUntil: "networkidle" })
await page.evaluate(({ token, userId }) => {
  localStorage.setItem("esh_token", token)
  localStorage.setItem("esh_user_id", userId)
  localStorage.setItem("esh_grade", "12")
}, { token: access_token, userId: user_id })
await page.goto("http://localhost:5173/", { waitUntil: "networkidle" })
await page.waitForTimeout(1500)
await page.screenshot({ path: `${SHOT_DIR}/dashboard-studyplan.png` })

// check off the first task and confirm it persists after reload
await page.locator("button[aria-label='Mark done']").first().click()
await page.waitForTimeout(600)
await page.screenshot({ path: `${SHOT_DIR}/dashboard-studyplan-checked.png` })
await page.reload({ waitUntil: "networkidle" })
await page.waitForTimeout(1200)
await page.screenshot({ path: `${SHOT_DIR}/dashboard-studyplan-reloaded.png` })

console.log("errors:", errors.length ? errors.join("\n") : "none")
await browser.close()
