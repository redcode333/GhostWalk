import { defineConfig } from "@playwright/test"

/** Uses the Chrome that is installed (no browser download). BASE_URL picks the target: the dev server by default, the live site for the post-deploy check. */
export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: process.env.BASE_URL ?? "http://127.0.0.1:5173", channel: "chrome", headless: true, launchOptions: { args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] } },
})
