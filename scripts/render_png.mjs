// Renders the learning-curve SVGs in docs/ to PNG (2x) with the Playwright browser from web/.
//   cd web && cp ../scripts/render_png.mjs ./rp.tmp.mjs && node rp.tmp.mjs && rm rp.tmp.mjs
import { chromium } from "@playwright/test"
import fs from "node:fs"
const names = ["learning-curve", "learning-curve-dark", "learning-curve-bins", "learning-curve-bins-dark"]
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 900, height: 500 }, deviceScaleFactor: 2 })
for (const n of names) {
  await p.setContent(`<body style="margin:0">${fs.readFileSync(`../docs/${n}.svg`, "utf8")}</body>`)
  await (await p.$("svg")).screenshot({ path: `../docs/${n}.png` }); console.log(`wrote docs/${n}.png`)
}
await b.close()
