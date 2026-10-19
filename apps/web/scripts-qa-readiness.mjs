import { chromium } from "playwright";
import path from "node:path";

const out = path.resolve("../../docs/ui-shots");
const base = "http://127.0.0.1:3000";
const pages = [
  ["qa-home", "/", "Forward clock is armed"],
  ["qa-market", "/market", "SPY"],
  ["qa-decisions", "/decisions", "2019"],
  ["qa-agents", "/agents", ""],
  ["qa-portfolio", "/portfolio", "$100"],
  ["qa-approvals", "/approvals", ""],
  ["qa-advanced", "/advanced", ""],
  ["qa-research", "/research", ""],
];

const browser = await chromium.launch({ channel: "msedge", headless: true });
const failures = [];

for (const [name, route, needle] of pages) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  const response = await page.goto(`${base}${route}`, { waitUntil: "networkidle", timeout: 60000 });
  await page.waitForTimeout(800);
  const body = await page.locator("body").innerText();
  const status = response ? response.status() : 0;
  if (status >= 400) failures.push(`${route} http ${status}`);
  if (needle && !body.includes(needle)) failures.push(`${route} missing ${needle}`);
  if (errors.length) failures.push(`${route} console ${errors.slice(0, 3).join(" | ")}`);
  await page.screenshot({ path: path.join(out, `${name}-1280x800.png`) });
  console.log("page", route, status, "chars", body.length, "errors", errors.length);
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${base}/`, { waitUntil: "networkidle", timeout: 60000 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  if (overflow > 1) failures.push(`mobile overflow ${overflow}`);
  if (errors.length) failures.push(`mobile ${errors.join(" | ")}`);
  await page.screenshot({ path: path.join(out, "qa-home-390x844.png") });
  console.log("mobile", overflow, errors.length);
  await context.close();
}

await browser.close();
if (failures.length) {
  console.log("FAILURES");
  for (const item of failures) console.log(item);
  process.exit(1);
}
console.log("qa pages ok");
