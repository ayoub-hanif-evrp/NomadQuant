import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const outDir = path.resolve("../../docs/ui-shots");
await mkdir(outDir, { recursive: true });

const pages = [
  { name: "command-center", url: "http://127.0.0.1:3000/", waitMs: 2500 },
  { name: "market-explorer", url: "http://127.0.0.1:3000/market-data", waitMs: 4000 },
  { name: "research-lab", url: "http://127.0.0.1:3000/research", waitMs: 4000 },
  { name: "decision-intelligence", url: "http://127.0.0.1:3000/decisions", waitMs: 3000 },
  { name: "activity", url: "http://127.0.0.1:3000/activity", waitMs: 3000 },
  { name: "runs", url: "http://127.0.0.1:3000/runs", waitMs: 2500 },
  { name: "agents", url: "http://127.0.0.1:3000/agents", waitMs: 3500 },
];

const viewports = [
  { name: "1920x1080", width: 1920, height: 1080 },
  { name: "1440x900", width: 1440, height: 900 },
  { name: "1280x800", width: 1280, height: 800 },
  { name: "390x844", width: 390, height: 844 },
];

const browser = await chromium.launch({ headless: true });
try {
  for (const viewport of viewports) {
    const context = await browser.newContext({
      viewport: { width: viewport.width, height: viewport.height },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage();
    page.on("pageerror", (error) => {
      console.error(`PAGEERROR ${viewport.name}:`, error.message);
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        console.error(`CONSOLE ${viewport.name}:`, msg.text());
      }
    });
    for (const target of pages) {
      await page.goto(target.url, { waitUntil: "networkidle", timeout: 60000 });
      await page.waitForTimeout(target.waitMs);
      const file = path.join(outDir, `${target.name}-${viewport.name}.png`);
      await page.screenshot({ path: file, fullPage: true });
      console.log("wrote", file);
    }
    if (viewport.name === "390x844") {
      await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle" });
      await page.waitForTimeout(1000);
      const menu = page.getByRole("button", { name: "Open navigation" });
      if (await menu.count()) {
        await menu.click();
        await page.waitForTimeout(500);
        await page.screenshot({
          path: path.join(outDir, `mobile-nav-${viewport.name}.png`),
          fullPage: true,
        });
        console.log("wrote mobile nav");
      }
    }
    await context.close();
  }
} finally {
  await browser.close();
}
