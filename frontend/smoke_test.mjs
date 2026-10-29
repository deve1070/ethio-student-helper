import { chromium } from "playwright"

const SHOT_DIR = "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/shots"
import { mkdirSync } from "node:fs"
mkdirSync(SHOT_DIR, { recursive: true })

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 400, height: 860 } })
const errors = []
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`))
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(`console.error: ${msg.text()}`)
})

async function shot(name) {
  await page.screenshot({ path: `${SHOT_DIR}/${name}.png` })
  console.log("shot:", name)
}

try {
  await page.goto("http://localhost:5173/signup", { waitUntil: "networkidle" })
  await shot("01-signup")

  const uniq = Date.now()
  await page.fill("#fullName", "Test Student")
  await page.fill("#identifier", `smoketest${uniq}@example.com`)
  await page.fill("#password", "testpassword123")
  await page.click('button:has-text("Grade 11")')
  await shot("02-signup-filled")
  await page.click('button[type="submit"]')
  await page.waitForURL("**/", { timeout: 10000 })
  await shot("03-dashboard")

  // Explain
  await page.click('text=Ask a question')
  await page.waitForURL("**/explain")
  await shot("04-explain-empty")
  await page.fill("#subject", "biology")
  await page.fill("#question", "What is the difference between mitosis and meiosis?")
  await page.click('button:has-text("Ask")')
  await page.waitForTimeout(6000)
  await shot("05-explain-result")

  // Practice
  await page.goto("http://localhost:5173/practice", { waitUntil: "networkidle" })
  await shot("06-practice-subjects")
  const firstSubject = page.locator("button", { hasText: /questions$/ }).first()
  if (await firstSubject.count()) {
    await firstSubject.click()
    await page.waitForTimeout(1000)
    await shot("07-practice-units")
    await page.click('text=Mixed practice')
    await page.waitForTimeout(1500)
    await shot("08-practice-session")
    const firstOption = page.locator('[role="radio"]').first()
    if (await firstOption.count()) {
      await firstOption.click()
      await page.waitForTimeout(1500)
      await shot("09-practice-feedback")
    }
  } else {
    console.log("no practice subjects available for this grade, skipping")
  }

  // ESSLCE
  await page.goto("http://localhost:5173/esslce", { waitUntil: "networkidle" })
  await shot("10-esslce-subjects")
  const firstEsslceSubject = page.locator("button", { hasText: /questions$/ }).first()
  if (await firstEsslceSubject.count()) {
    await firstEsslceSubject.click()
    await page.waitForTimeout(1000)
    await shot("11-esslce-mode-picker")
    await page.click('text=Diagnostic test')
    await page.waitForTimeout(1500)
    await shot("12-esslce-diagnostic")
    const opt = page.locator('[role="radio"]').first()
    if (await opt.count()) {
      await opt.click()
      await page.waitForTimeout(1200)
      await shot("13-esslce-diagnostic-next")
    }
  }

  // Credits / buy
  await page.goto("http://localhost:5173/credits", { waitUntil: "networkidle" })
  await shot("14-credits")
  await page.click('text=Buy credits')
  await page.waitForTimeout(500)
  await shot("15-buy")
  await page.click('text=5 credits')
  await page.waitForTimeout(300)
  await shot("16-buy-bundle-selected")

  // Profile
  await page.goto("http://localhost:5173/profile", { waitUntil: "networkidle" })
  await shot("17-profile")

  console.log("\n=== console/page errors ===")
  console.log(errors.length ? errors.join("\n") : "none")
} catch (e) {
  console.error("TEST FAILED:", e)
  await shot("ERROR")
  console.log("\n=== console/page errors ===")
  console.log(errors.length ? errors.join("\n") : "none")
  process.exitCode = 1
} finally {
  await browser.close()
}
