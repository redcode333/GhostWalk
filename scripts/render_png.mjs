// Renders docs/learning-curve.svg to docs/learning-curve.png (2x) with the Playwright browser from web/.
//   cd web && node ../scripts/render_png.mjs
import { chromium } from "@playwright/test"
import fs from "node:fs"
const svg = fs.readFileSync("../docs/learning-curve.svg", "utf8")
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 760, height: 360 }, deviceScaleFactor: 2 })
await p.setContent(`<body style="margin:0;background:#fff">${svg}</body>`)
await (await p.$("svg")).screenshot({ path: "../docs/learning-curve.png" })
await b.close(); console.log("wrote docs/learning-curve.png")
