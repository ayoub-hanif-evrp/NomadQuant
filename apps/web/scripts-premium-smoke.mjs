import { chromium } from "playwright";
import path from "node:path";

const out = path.resolve("../../docs/ui-shots");
const base = "http://127.0.0.1:3000";
const pages = [
  ["premium-home", "/", "Today at a glance"],
  ["premium-intelligence", "/decisions", "Why the system would act"],
  ["premium-agents", "/agents", "Your AI research crew"],
  ["premium-markets", "/market", "Stored daily market"],
  ["premium-portfolio", "/portfolio", "Internal $100 shadow book"],
  ["premium-approvals", "/approvals", "Waiting for you"],
];
const viewports = [
  [1920, 1080],
  [1440, 900],
  [1280, 800],
];
let failures = 0;

function fail(message) {
  failures += 1;
  console.log("FAIL", message);
}

const decide = await fetch("http://127.0.0.1:8000/api/approvals/scanner/decide");
console.log("get-decide", decide.status);
if (decide.status !== 405) fail("GET decide must be 405");

const browser = await chromium.launch({ headless: true });

for (const [width, height] of viewports) {
  for (const [name, route, heading] of pages) {
    const context = await browser.newContext({ viewport: { width, height } });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`${base}${route}`, { waitUntil: "networkidle", timeout: 60000 });
    await page.getByRole("heading", { name: heading }).first().waitFor({ timeout: 20000 });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    if (overflow > 1) fail(`${name} ${width} overflow ${overflow}`);
    if (errors.length) fail(`${name} ${width} ${errors.join(" | ")}`);
    if (width === 1280) {
      await page.screenshot({ path: path.join(out, `${name}-1280x800.png`) });
    }
    if (width === 1920 && route === "/") {
      await page.screenshot({ path: path.join(out, "premium-home-1920x1080.png") });
    }
    await context.close();
  }
}

{
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${base}/`, { waitUntil: "networkidle", timeout: 60000 });
  await page.locator("canvas").first().waitFor({ timeout: 20000 });
  await page.getByText("Chart shows finished daily bars through").waitFor({ timeout: 20000 });
  const body = await page.locator("body").innerText();
  if (!body.includes("Oct 15, 2026")) fail("missing stored session");
  if (!body.toLowerCase().includes("is the system working?")) fail("missing system status panel");
  await page.getByRole("button", { name: "QQQ" }).click();
  await page.getByRole("heading", { name: /^QQQ/ }).waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(out, "premium-home-scrolled-1280x800.png"), fullPage: true });
  await page.getByRole("button", { name: "Copilot" }).click();
  await page.getByRole("heading", { name: "Ask me anything about your app" }).waitFor();
  await page.getByRole("button", { name: "How much virtual money do I have?" }).click();
  const sources = page.getByRole("button", { name: /Show \d+ sources?/ });
  await sources.first().waitFor({ timeout: 90000 });
  await sources.first().click();
  const answer = await page.locator("aside").last().innerText();
  if (answer.includes("999")) fail("assistant invented 999");
  console.log("copilot-answer", answer.split("\n").slice(0, 12).join(" / ").slice(0, 600));
  await page.screenshot({ path: path.join(out, "premium-copilot-1280x800.png") });
  console.log("copilot", errors.length ? errors.join(" | ") : "ok");
  if (errors.length) fail(errors.join(" | "));
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto(`${base}/agents`, { waitUntil: "networkidle", timeout: 60000 });
  const idle = await page.getByText("No review is running").count();
  console.log("agents-idle-copy", idle);
  await page.screenshot({ path: path.join(out, "premium-agents-full-1280x800.png"), fullPage: true });
  const run = page.getByRole("button", { name: /Run \d+/ }).first();
  if (await run.count()) {
    await run.click();
    await page.getByRole("button", { name: "Replay recorded activity" }).click();
    await page.getByText("REPLAY of a stored run").waitFor({ timeout: 5000 });
    await page.screenshot({ path: path.join(out, "premium-agents-replay-1280x800.png") });
    console.log("replay", "ok");
  } else {
    console.log("replay", "no stored run button");
  }
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${base}/`, { waitUntil: "networkidle", timeout: 60000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  if (overflow > 1) fail(`mobile overflow ${overflow}`);
  await page.getByRole("button", { name: "Copilot" }).click();
  await page.getByRole("heading", { name: "Ask me anything about your app" }).waitFor();
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(out, "premium-copilot-390x844.png") });
  if (errors.length) fail(errors.join(" | "));
  await context.close();
}

await browser.close();
if (failures) {
  console.log("failures", failures);
  process.exit(1);
}
console.log("premium smoke ok");
