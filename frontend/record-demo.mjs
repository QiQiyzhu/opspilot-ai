// Records actual local UI actions. Requires a fresh eligible simulated order.
import { chromium, expect } from "@playwright/test";
import { mkdir, copyFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const access = process.env.OPSPILOT_E2E_TOKEN;
const order = process.env.OPSPILOT_RECORD_ORDER;
if (!access || !order)
  throw new Error(
    "Set OPSPILOT_E2E_TOKEN and OPSPILOT_RECORD_ORDER. This records and approves one simulated refund.",
  );
const artifacts = resolve("../docs/assets");
const temporary = resolve(
  process.env.OPSPILOT_RECORD_DIR || "test-results/recording",
);
await mkdir(artifacts, { recursive: true });
await mkdir(temporary, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
const context = await browser.newContext({
  viewport: { width: 1560, height: 1020 },
  recordVideo: { dir: temporary, size: { width: 1560, height: 1020 } },
});
await context.addInitScript(
  (value) => sessionStorage.setItem("opspilot-token", value),
  access,
);
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
let runId;
page.on("response", async (response) => {
  if (
    response.url().endsWith("/api/messages") &&
    response.request().method() === "POST" &&
    response.ok()
  )
    runId = (await response.json()).run_id;
});
const started = Date.now();
await page.goto("http://127.0.0.1:5176/");
await page
  .getByRole("button", { name: "New conversation", exact: true })
  .click();
await page
  .getByRole("dialog")
  .getByRole("combobox", { name: "Customer", exact: true })
  .selectOption("cus_ava");
await page
  .getByLabel("Conversation title")
  .fill("Refund request · delivery issue");
await page
  .getByRole("button", { name: "Create conversation", exact: true })
  .click();
await page.getByLabel("Affected order").selectOption(order);
await page.getByLabel("Tool transport").selectOption("mcp");
await page
  .getByLabel("Customer message")
  .fill(
    "My order arrived five days ago. I would like a full refund. Please check the current policy before taking any action.",
  );
await page.waitForTimeout(1400);
await page.getByRole("button", { name: "Run agent", exact: true }).click();
await expect(page.locator(".approval-panel")).toBeVisible({ timeout: 45000 });
await page
  .getByRole("navigation", { name: "Case context" })
  .getByRole("button", { name: /^Evidence/ })
  .click();
await page.locator(".approval-panel").scrollIntoViewIfNeeded();
await page.waitForTimeout(1800);
await page.screenshot({ path: resolve(artifacts, "demo-approval.png") });
await page
  .getByLabel("Decision reason")
  .fill(
    "Delivery date and full-order amount match Refund Policy v2. Approve this simulated ledger request.",
  );
await page.waitForTimeout(1200);
await page
  .getByRole("button", { name: "Approve & verify", exact: true })
  .click();
await expect(page.locator(".approval-panel .badge").first()).toHaveText(
  "executed",
  { timeout: 20000 },
);
await expect(page.locator(".conversation-head .badge")).toHaveText("completed");
await page.getByRole("button", { name: "Trace", exact: true }).click();
await page
  .locator(".trace-event")
  .filter({ hasText: "verification · completed" })
  .first()
  .locator("summary")
  .click();
await page.waitForTimeout(1600);
await page.screenshot({ path: resolve(artifacts, "demo-verified.png") });
await page.getByRole("button", { name: "Evaluation lab", exact: true }).click();
await page
  .getByRole("heading", { name: "Retrieval baseline comparison" })
  .scrollIntoViewIfNeeded();
await page.waitForTimeout(1700);
await page.screenshot({ path: resolve(artifacts, "evaluation.png") });
await page.getByRole("button", { name: "Overview", exact: true }).click();
await expect(page.locator(".stats-grid")).toBeVisible();
await page.waitForTimeout(Math.max(1500, 33000 - (Date.now() - started)));
await page.screenshot({ path: resolve(artifacts, "operations.png") });
if (!runId) throw new Error("Recording did not observe the real run response.");
const headers = { Authorization: `Bearer ${access}` };
const runResponse = await fetch(`http://127.0.0.1:8003/api/runs/${runId}`, {
  headers,
});
if (!runResponse.ok)
  throw new Error(`Trace export failed: ${runResponse.status}`);
const run = await runResponse.json();
const proposalResponse = await fetch(
  `http://127.0.0.1:8003/api/approvals/${run.proposal_id}`,
  { headers },
);
if (!proposalResponse.ok)
  throw new Error(`Approval export failed: ${proposalResponse.status}`);
const proposal = await proposalResponse.json();
await writeFile(
  resolve(artifacts, "demo-run.json"),
  JSON.stringify(
    {
      source: "Actual local PostgreSQL-backed run",
      business: "SIMULATED BUSINESS",
      provider: "fake-rules-v1; no LLM inference",
      run,
      proposal,
    },
    null,
    2,
  ) + "\n",
);
const video = page.video();
await context.close();
const original = await video.path();
await copyFile(original, resolve(artifacts, "demo.webm"));
await browser.close();
await writeFile(
  resolve(artifacts, "demo-recording.json"),
  JSON.stringify(
    {
      kind: "actual-local-browser-recording",
      created_at: new Date().toISOString(),
      business: "SIMULATED BUSINESS",
      model: "fake-rules-v1",
      transport: "MCP Streamable HTTP",
      run_id: runId,
      order_id: order,
      wall_time_ms: Date.now() - started,
      viewport: { width: 1560, height: 1020 },
      editing: "None; continuous recording of actual UI interactions",
      page_errors: errors,
    },
    null,
    2,
  ) + "\n",
);
if (errors.length) throw new Error(`Browser errors: ${errors.join("; ")}`);
console.log(
  JSON.stringify({
    run_id: runId,
    status: run.status,
    video: "docs/assets/demo.webm",
    errors,
  }),
);
