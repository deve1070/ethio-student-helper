import { chromium } from "playwright"
import { readFileSync } from "node:fs"
const { access_token, user_id } = JSON.parse(readFileSync(
  "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/signup_resp.json", "utf8"
))
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 400, height: 860 } })
await page.goto("http://localhost:5173/", { waitUntil: "networkidle" })
await page.evaluate(({ token, userId }) => {
  localStorage.setItem("esh_token", token)
  localStorage.setItem("esh_user_id", userId)
  localStorage.setItem("esh_grade", "12")
}, { token: access_token, userId: user_id })
await page.goto("http://localhost:5173/mistakes", { waitUntil: "networkidle" })
await page.click('text=ESSLCE')
await page.waitForResponse((r) => r.url().includes("/v1/esslce/mistakes"))
await page.waitForTimeout(500)
await page.screenshot({
  path: "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/shots/mistakes-esslce-final.png",
})
await browser.close()
