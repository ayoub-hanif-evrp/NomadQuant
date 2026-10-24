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
  await desktop.goto(`${base}/paper`, { waitUntil: "domcontentloaded" });
  await assertPaper(desktop);
  await desktop.goto(`${base}/`, { waitUntil: "domcontentloaded" });
  await desktop.getByRole("link", { name: "Alpaca Paper" }).click();
  await desktop.waitForURL("**/paper");
  await assertPaper(desktop);
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto(`${base}/paper`, { waitUntil: "domcontentloaded" });
  await assertPaper(mobile);
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
  } catch (error) {
    const facts = await page.evaluate(() => ({
      text: document.body.textContent.includes("Execution audit"),
      inner: document.body.innerText.includes("Execution audit"),
    }));
    const body = await page.locator("body").innerText();
    throw new Error(`${page.url()} ${JSON.stringify(facts)}\n${body.slice(0, 400)}\n${error.message}`);
  }
  const body = await page.locator("body").innerText();
  if (!body.includes("The paper status could not be read.") && !body.includes("Accounting:")) {
    throw new Error(`No status or read failure.\n${body.slice(0, 400)}`);
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
