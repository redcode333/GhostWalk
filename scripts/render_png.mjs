// Renders docs/learning-curve.svg and docs/learning-curve-dark.svg to PNG (2x) with the Playwright browser from web/.
//   cd web && cp ../scripts/render_png.mjs ./rp.tmp.mjs && node rp.tmp.mjs && rm rp.tmp.mjs
import { chromium } from "@playwright/test"
import fs from "node:fs"
const b = await chromium.launch(); const p = await b.newPage({ viewport: { width: 760, height: 360 }, deviceScaleFactor: 2 })
for (const [svgName, png] of [["learning-curve.svg", "learning-curve.png"], ["learning-curve-dark.svg", "learning-curve-dark.png"]]) {
  await p.setContent(`<body style="margin:0">${fs.readFileSync("../docs/" + svgName, "utf8")}</body>`)
  await (await p.$("svg")).screenshot({ path: "../docs/" + png }); console.log("wrote docs/" + png)
}
await b.close()
