import { chromium } from "playwright"
import { readFileSync } from "node:fs"
const { access_token, user_id } = JSON.parse(readFileSync(
  "/tmp/claude-1000/-home-dmk-ethio-student-helper/f6fb86e1-cf96-4ba3-957c-ed29e4f68492/scratchpad/signup_resp.json", "utf8"
))
const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 400, height: 860 } })
page.on("console", (msg) => console.log("console:", msg.text()))
page.on("pageerror", (e) => console.log("pageerror:", e.message))
page.on("requestfinished", async (req) => {
  if (req.url().includes("/v1/esslce/mistakes") || req.url().includes("/v1/esslce/subjects")) {
    const res = await req.response()
    console.log("REQ", req.url(), "->", res?.status())
  }
})
await page.goto("http://localhost:5173/", { waitUntil: "networkidle" })
await page.evaluate(({ token, userId }) => {
  localStorage.setItem("esh_token", token)
  localStorage.setItem("esh_user_id", userId)
  localStorage.setItem("esh_grade", "12")
}, { token: access_token, userId: user_id })
await page.goto("http://localhost:5173/mistakes", { waitUntil: "networkidle" })
await page.click('text=ESSLCE')
await page.waitForTimeout(3000)
await browser.close()
console.log("done")
