import { chromium } from "playwright"
import { mkdirSync } from "node:fs"

const SHOT_DIR = "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/shots"
mkdirSync(SHOT_DIR, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 400, height: 860 } })
const errors = []
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`))
page.on("console", (msg) => { if (msg.type() === "error") errors.push(`console.error: ${msg.text()}`) })

async function shot(name) {
  await page.screenshot({ path: `${SHOT_DIR}/${name}.png` })
  console.log("shot:", name)
}

try {
  await page.goto("http://localhost:5173/signup", { waitUntil: "networkidle" })
  const uniq = Date.now()
  await page.fill("#fullName", "Onboard Test")
  await page.fill("#identifier", `onboard${uniq}@example.com`)
  await page.fill("#password", "testpassword123")
  await page.click('button:has-text("Grade 12")')
  await page.click('button[type="submit"]')

  // should land on /onboarding, not dashboard
  await page.waitForURL("**/onboarding", { timeout: 10000 })
  await page.waitForTimeout(600)
  await shot("ob-01-stream")

  await page.click('text=Natural Science')
  await page.click('button:has-text("Continue")')
  await page.waitForTimeout(600)
  await shot("ob-02-subjects")

  // pick a few subjects
  await page.click('button:has-text("Biology")')
  await page.click('button:has-text("Chemistry")')
  await page.click('button:has-text("Mathematics")')
  await shot("ob-02b-subjects-selected")
  await page.click('button:has-text("Continue")')
  await page.waitForTimeout(600)
  await shot("ob-03-examdate")

  await page.fill('input[type="date"]', "2026-11-30")
  await page.click('button:has-text("Continue")')
  await page.waitForTimeout(600)
  await shot("ob-04-goal")

  await page.click('text=2 hours')
  await page.click('button:has-text("Continue")')
  await page.waitForTimeout(600)
  await shot("ob-05-done")

  await page.click('button:has-text("Go to Dashboard")')
  await page.waitForURL("**/", { timeout: 10000 })
  await page.waitForTimeout(800)
  await shot("ob-06-dashboard")

  // profile shows the collected data
  await page.goto("http://localhost:5173/profile", { waitUntil: "networkidle" })
  await page.waitForTimeout(500)
  await shot("ob-07-profile")

  // edit setup re-entry
  await page.click('text=Edit')
  await page.waitForTimeout(600)
  await shot("ob-08-edit-reentry")

  console.log("\n=== errors ===")
  console.log(errors.length ? errors.join("\n") : "none")
} catch (e) {
  console.error("FAILED:", e)
  await shot("ob-ERROR")
  console.log("\n=== errors ===")
  console.log(errors.length ? errors.join("\n") : "none")
  process.exitCode = 1
} finally {
  await browser.close()
}
