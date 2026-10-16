import { chromium } from "playwright";
import path from "node:path";

const out = path.resolve("../../docs/ui-shots");
const browser = await chromium.launch({ headless: true });
const pages = [
  ["guided-home", "http://127.0.0.1:3000/", "What needs attention"],
  ["guided-decisions", "http://127.0.0.1:3000/decisions", "Why the system would act"],
  ["guided-agents", "http://127.0.0.1:3000/agents", "How a review moves"],
  ["guided-portfolio", "http://127.0.0.1:3000/portfolio", "Internal $100 shadow book"],
  ["guided-market", "http://127.0.0.1:3000/market", "What the system is using"],
  ["guided-approvals", "http://127.0.0.1:3000/approvals", "Waiting for you"],
  ["guided-advanced", "http://127.0.0.1:3000/advanced", "Workbench"],
];
let failures = 0;

for (const [name, url, heading] of pages) {
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(url, { waitUntil: "networkidle", timeout: 60000 });
  await page.getByRole("heading", { name: heading }).first().waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(out, `${name}-1280x800.png`) });
  console.log(name, errors.length ? errors.join(" | ") : "ok");
  if (errors.length) failures += 1;
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 60000 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Approvals", exact: true }).click();
  await page.getByRole("heading", { name: "Waiting for you" }).waitFor({ timeout: 20000 });
  await page.screenshot({ path: path.join(out, "guided-approvals-390x844.png") });
  console.log("mobile-approvals", errors.length ? errors.join(" | ") : "ok");
  if (errors.length) failures += 1;
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:3000/approvals/respond/demo", { waitUntil: "networkidle" });
  const disabled = await page.getByRole("button", { name: "Approve shadow permission" }).isDisabled();
  console.log("confirm-disabled", disabled);
  if (!disabled) failures += 1;
  await page.screenshot({ path: path.join(out, "guided-approval-confirm-1280x800.png") });
  await context.close();
}

{
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle", timeout: 60000 });
  const body = await page.locator("body").innerText();
  for (const phrase of ["Waiting for market data", "No approval is waiting", "PAPER ONLY"]) {
    const ok = body.includes(phrase);
    console.log("phrase", phrase, ok);
    if (!ok) failures += 1;
  }
  await page.getByRole("link", { name: "Open the decision story" }).click();
  await page.waitForURL("**/decisions");
  await page.getByRole("link", { name: "Advanced evidence" }).click();
  await page.waitForURL("**/advanced");
  await page.getByRole("link", { name: "Shadow operations" }).click();
  await page.waitForURL("**/shadow");
  console.log("flow", page.url(), errors.length ? errors.join(" | ") : "ok");
  if (errors.length) failures += 1;
  await context.close();
}

await browser.close();
if (failures) {
  process.exit(1);
}
