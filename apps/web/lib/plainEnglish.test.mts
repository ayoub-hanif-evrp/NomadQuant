import assert from "node:assert/strict";
import { test } from "node:test";
import { explainIntent, explainPilot } from "./plainEnglish.ts";

test("waiting for a session is explained without a trade instruction", () => {
  const status = explainPilot("WAITING_FOR_SESSION");
  assert.equal(status.title, "No action needed right now");
  assert.match(status.means, /not complete yet/);
  assert.equal(status.tone, "info");
});

test("a blocked pilot stays a refusal", () => {
  const status = explainPilot("BLOCKED");
  assert.match(status.means, /will not take the action/);
  assert.equal(status.tone, "err");
});

test("unknown status is not treated as an order", () => {
  const status = explainPilot("RISK_REJECTED");
  assert.match(status.why, /not instructions to buy or sell/);
});

test("intents stay inside the shadow ledger", () => {
  assert.match(explainIntent("buy"), /internal shadow ledger/);
  assert.match(explainIntent("no_trade"), /No shadow trade/);
});
