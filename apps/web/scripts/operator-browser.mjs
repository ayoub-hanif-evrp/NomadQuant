import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";

const port = process.env.NOMAD_WEB_PORT || "3010";
const base = process.env.NOMAD_WEB || `http://127.0.0.1:${port}`;
const startedHere = !process.env.NOMAD_WEB;
const cwd = fileURLToPath(new URL("..", import.meta.url));
const server = startedHere
  ? spawn(process.execPath, ["node_modules/next/dist/bin/next", "start", "--hostname", "127.0.0.1", "--port", port], {
      cwd,
      stdio: "inherit",
    })
  : null;

try {
  await waitFor(`${base}/paper`);
  const browser = await chromium.launch();
  const desktop = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  desktop.on("pageerror", (error) => console.error("pageerror", error.message));
  await desktop.route("http://127.0.0.1:8000/**", (route) => route.abort());
  await desktop.goto(`${base}/paper`, { waitUntil: "domcontentloaded" });
  await assertPaper(desktop);
  await desktop.goto(`${base}/`, { waitUntil: "domcontentloaded" });
  await desktop.getByRole("link", { name: "Alpaca Paper" }).click();
  await desktop.waitForURL("**/paper");
  await assertPaper(desktop);
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.route("http://127.0.0.1:8000/**", (route) => route.abort());
  await mobile.goto(`${base}/paper`, { waitUntil: "domcontentloaded" });
  await assertPaper(mobile);
  await assertRoute(desktop, "/agents", ["None of them can place an order"]);
  await assertRoute(desktop, "/health", ["Health unavailable", "could not be reached"]);
  await assertRoute(desktop, "/research", ["Research Lab unavailable"]);
  await assertRoute(desktop, "/market-data", [
    "Market status unavailable",
    "not a live quote stream",
  ]);
  await assertRoute(desktop, "/portfolio", [
    "Simulated ledger only",
    "not the Alpaca paper account",
    "No forward trading results yet",
  ]);
  await assertRoute(mobile, "/portfolio", ["Simulated ledger only", "not the Alpaca paper account"]);
  await browser.close();
  console.log("operator browser check passed");
} finally {
  if (server) server.kill();
}

async function assertPaper(page) {
  const audit = page.getByText("Execution audit", { exact: true });
  try {
    await page.getByRole("heading", { name: /FAKE MONEY/ }).waitFor({ timeout: 15000 });
    await audit.waitFor({ state: "attached", timeout: 15000 });
    await audit.scrollIntoViewIfNeeded();
    await audit.waitFor({ state: "visible", timeout: 5000 });
    await page.getByText("Portfolio truth", { exact: true }).waitFor();
    await page.getByText("permission to trade").waitFor();
    await page.getByText("does not submit an order").waitFor();
    await page.getByText("The paper status could not be read.").waitFor({ timeout: 25000 });
    await page.getByText("Daily status could not be read.").waitFor();
    await page.getByText("No NomadQuant paper order is stored.").waitFor();
    await page.getByText("is not the strategy budget").waitFor();
  } catch (error) {
    const facts = await page.evaluate(() => ({
      text: document.body.textContent.includes("Execution audit"),
      inner: document.body.innerText.includes("Execution audit"),
    }));
    const body = await page.locator("body").innerText();
    throw new Error(`${page.url()} ${JSON.stringify(facts)}\n${body.slice(0, 400)}\n${error.message}`);
  }
}

async function assertRoute(page, path, phrases) {
  await page.goto(`${base}/`, { waitUntil: "domcontentloaded" });
  await page.goto(`${base}${path}`, { waitUntil: "domcontentloaded" });
  try {
    await page.waitForFunction(
      (expected) => expected.every((phrase) => document.body.textContent.includes(phrase)),
      phrases,
      { timeout: 25000 },
    );
  } catch (error) {
    const body = await page.locator("body").innerText();
    throw new Error(`${page.url()}\n${body.slice(0, 400)}\n${error.message}`);
  }
}

async function waitFor(url) {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The server is still starting.
    }
    await delay(500);
  }
  throw new Error(`The dashboard did not answer at ${url}.`);
}
