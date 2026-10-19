import { chromium } from "playwright";

const browser = await chromium.launch({ channel: "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on("response", async (response) => {
  if (!response.url().includes("/api/market-data/bars")) return;
  const body = await response.json();
  console.log("url", response.url());
  console.log(
    "api",
    body.symbol,
    body.total,
    body.items.length,
    body.items[0]?.session_date,
    body.items.at(-1)?.session_date,
  );
});
await page.goto("http://127.0.0.1:3000/market", { waitUntil: "networkidle", timeout: 60000 });
await page.waitForTimeout(500);
await page.screenshot({ path: "../../docs/ui-shots/qa-market-fixed-1y.png" });
await page.getByRole("button", { name: "1M" }).click();
await page.waitForTimeout(1000);
await page.screenshot({ path: "../../docs/ui-shots/qa-market-fixed-1m.png" });
const box = await page.locator('[aria-label="Daily price chart"]').boundingBox();
console.log("box", JSON.stringify(box));
await browser.close();
