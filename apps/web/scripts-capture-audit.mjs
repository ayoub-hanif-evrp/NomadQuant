import { chromium } from "playwright";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const out = path.resolve("../../docs/ui-shots");
await mkdir(out, { recursive: true });

const browser = await chromium.launch({ headless: true });
const shot = async (page, name) => {
  const file = path.join(out, name);
  await page.screenshot({ path: file, fullPage: false });
  console.log("wrote", file);
};

try {
  const desktop = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await desktop.newPage();
  page.on("pageerror", (error) => console.error("PAGEERROR", error.message));

  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(1800);
  await shot(page, "audit-home-1280x800.png");

  await page.goto("http://127.0.0.1:3000/agents", { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(2000);
  await shot(page, "audit-agents-idle-1280x800.png");

  await page.getByRole("button", { name: "Run research review" }).click();
  await page.waitForTimeout(600);
  const runSelect = page.locator("select").first();
  await runSelect.selectOption({ index: 1 });
  const modelSelect = page.locator("select").nth(1);
  const models = await modelSelect.locator("option").allTextContents();
  if (models.includes("qwen3.5:9b")) {
    await modelSelect.selectOption("qwen3.5:9b");
  }
  await page.getByRole("button", { name: "Start local review" }).click();
  await page.waitForTimeout(2500);
  await shot(page, "audit-agents-working-1280x800.png");

  const deadline = Date.now() + 180000;
  while (Date.now() < deadline) {
    const body = await page.locator("body").innerText();
    if (body.includes("No review is running") && (body.includes("Finished") || body.includes("Verdict") || body.includes("failed"))) {
      break;
    }
    if (body.includes("verification") || body.includes("Finished in")) {
      const stillLive = body.includes("Thinking with") || body.includes("Waiting for the previous");
      if (!stillLive) {
        break;
      }
    }
    await page.waitForTimeout(4000);
  }
  await page.waitForTimeout(1500);
  await shot(page, "audit-agents-completed-1280x800.png");

  const newsHeading = page.getByText(/News|headline|Scout/i).first();
  if (await newsHeading.count()) {
    await newsHeading.scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
  }
  await shot(page, "audit-news-1280x800.png");

  await page.goto("http://127.0.0.1:3000/shadow", { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(1800);
  await shot(page, "audit-pilot-1280x800.png");

  await page.goto("http://127.0.0.1:3000/approvals", { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(1500);
  await shot(page, "audit-approvals-1280x800.png");

  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(1200);
  await page.getByRole("button", { name: "Copilot" }).click();
  await page.waitForTimeout(800);
  await page.getByRole("button", { name: "Why are there no trades yet?" }).click();
  await page.waitForTimeout(8000);
  await shot(page, "audit-copilot-why-no-trades-1280x800.png");
  await desktop.close();

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const mobilePage = await mobile.newPage();
  await mobilePage.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 60000 });
  await mobilePage.waitForTimeout(1200);
  await mobilePage.getByRole("button", { name: "Copilot" }).click();
  await mobilePage.waitForTimeout(800);
  await mobilePage.getByRole("button", { name: "Why are there no trades yet?" }).click();
  await mobilePage.waitForTimeout(8000);
  await shot(mobilePage, "audit-copilot-mobile-390x844.png");
  await mobile.close();
} finally {
  await browser.close();
}
