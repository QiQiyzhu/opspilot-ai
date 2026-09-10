import { test, expect, type Page } from "@playwright/test";
const admin = process.env.OPSPILOT_E2E_TOKEN;
test.skip(
  !admin,
  "Set OPSPILOT_E2E_TOKEN to a local simulated-business admin token.",
);
const headers = () => ({ Authorization: `Bearer ${admin}` });
async function connect(page: Page, access = admin!) {
  await page.goto("/");
  await page.getByLabel("Workspace access token").fill(access);
  await page
    .getByRole("button", { name: "Connect workspace", exact: true })
    .click();
  await expect(
    page.getByRole("navigation", { name: "Main navigation" }),
  ).toBeVisible();
}
async function conversation(page: Page, title: string) {
  await page
    .getByRole("button", { name: "New conversation", exact: true })
    .click();
  await page
    .getByRole("dialog", { name: "New support conversation" })
    .getByRole("combobox", { name: "Customer", exact: true })
    .selectOption("cus_ava");
  await page.getByLabel("Conversation title").fill(title);
  await page
    .getByRole("button", { name: "Create conversation", exact: true })
    .click();
  await expect(page.locator(".conversation-head")).toContainText(title);
}
test("policy QA streams real evidence, persists messages and exposes MCP transport", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await connect(page);
  await conversation(page, `Policy question ${Date.now()}`);
  await page.getByLabel("Tool transport").selectOption("mcp");
  await page
    .getByLabel("Customer message")
    .fill("What is the current refund policy and settlement time?");
  await page.getByRole("button", { name: "Run agent", exact: true }).click();
  await expect(page.locator(".conversation-head .badge")).toHaveText(
    "completed",
    { timeout: 45000 },
  );
  await expect(page.locator(".agent-message")).toContainText(/refund|policy/i);
  await page
    .getByRole("navigation", { name: "Case context" })
    .getByRole("button", { name: /^Evidence/ })
    .click();
  await expect(
    page.locator(".context-content .evidence").first(),
  ).toBeVisible();
  await page.screenshot({
    path: "../docs/assets/inbox-evidence.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Trace", exact: true }).click();
  await expect(page.locator(".trace-list")).toContainText("tool");
  await expect(page.locator(".trace-summary")).toContainText("mcp");
  await page.screenshot({
    path: "../docs/assets/agent-trace.png",
    fullPage: true,
  });
  await page.reload();
  await expect(page.locator(".agent-message")).toContainText(/refund|policy/i);
  expect(errors).toEqual([]);
});
test("replacement proposal shows evidence and audited rejection without executing", async ({
  page,
  request,
}) => {
  await connect(page);
  await conversation(page, `Damaged delivery ${Date.now()}`);
  await page.getByLabel("Affected order").selectOption("ord_damaged");
  await page
    .getByLabel("Customer message")
    .fill(
      "The speaker was damaged on delivery. I want a replacement after checking the warranty.",
    );
  await page.getByRole("button", { name: "Run agent", exact: true }).click();
  await expect(page.locator(".approval-panel")).toBeVisible({ timeout: 45000 });
  await expect(page.locator(".approval-panel")).toContainText("ord_damaged");
  await expect(page.locator(".approval-panel")).toContainText(
    "Policy evidence",
  );
  await expect(page.locator(".approval-panel .evidence").first()).toBeVisible();
  await page.screenshot({
    path: "../docs/assets/human-approval.png",
    fullPage: true,
  });
  await page
    .getByLabel("Decision reason")
    .fill("Need customer confirmation of troubleshooting before replacement.");
  await page.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(page.locator(".approval-panel .badge").first()).toHaveText(
    "rejected",
  );
  const order = await request.get(
    "http://127.0.0.1:8003/api/orders/ord_damaged",
    { headers: headers() },
  );
  expect((await order.json()).status).toBe("delivered");
});
test("viewer cannot submit writes and server rejects bypass attempts", async ({
  page,
  request,
}) => {
  const viewer = process.env.OPSPILOT_E2E_VIEWER_TOKEN;
  test.skip(
    !viewer,
    "Set local viewer token to exercise server authorization.",
  );
  await connect(page, viewer!);
  await expect(
    page.getByRole("button", { name: "New conversation", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Approvals", exact: true }).click();
  const response = await request.post(
    "http://127.0.0.1:8003/api/orders/ord_recent/proposals",
    {
      headers: { Authorization: `Bearer ${viewer}` },
      data: {
        action: "refund",
        reason: "Unauthorized direct attempt",
        idempotency_key: crypto.randomUUID(),
      },
    },
  );
  expect(response.status()).toBe(403);
});
test("knowledge retrieval uses current evidence and registry compares real versions", async ({
  page,
}) => {
  await connect(page);
  await page.getByRole("button", { name: "Knowledge", exact: true }).click();
  await expect(
    page.getByText("Refund Policy", { exact: true }).first(),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Retrieval inspector", exact: true })
    .click();
  await page
    .getByLabel("Query", { exact: true })
    .fill("How long after delivery can I request a refund?");
  await page
    .getByRole("button", { name: "Search actual index", exact: true })
    .click();
  await expect(page.locator(".evidence").first()).toBeVisible({
    timeout: 30000,
  });
  await expect(page.locator(".page")).toContainText("BAAI");
  await page.screenshot({
    path: "../docs/assets/retrieval.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Prompts & workflows", exact: true })
    .click();
  await page.getByLabel("Inspect version").selectOption("2");
  await page.getByRole("button", { name: "Compare", exact: true }).click();
  await expect(page.locator(".diff-content")).toContainText("settlement");
  await page.screenshot({
    path: "../docs/assets/prompt-registry.png",
    fullPage: true,
  });
});
test("overview displays recorded data and mobile stays within viewport", async ({
  page,
}) => {
  await connect(page);
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(page.getByText("Agent runs", { exact: true })).toBeVisible();
  await expect(page.locator(".stats-grid")).not.toContainText("NaN");
  await page.screenshot({
    path: "../docs/assets/operations.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.screenshot({ path: "../docs/assets/mobile.png", fullPage: true });
});
test("offline retrieval evaluation persists measured metrics and comparison tables", async ({
  page,
}) => {
  await connect(page);
  await page
    .getByRole("button", { name: "Evaluation lab", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Retrieval baseline comparison" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Agent configuration ablation" }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Run actual evaluation", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Report · rag", exact: true }),
  ).toBeVisible({ timeout: 45000 });
  await expect(page.locator(".metric-cards")).toContainText("recall");
  await page
    .getByRole("heading", { name: "Retrieval baseline comparison" })
    .scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../docs/assets/evaluation.png" });
});
test("waiting run cancellation is persisted and prevents a late approval", async ({
  page,
  request,
}) => {
  await connect(page);
  await conversation(page, `Cancellation control ${Date.now()}`);
  await page.getByLabel("Affected order").selectOption("ord_damaged");
  await page
    .getByLabel("Customer message")
    .fill("Please replace my damaged speaker under its warranty.");
  await page.getByRole("button", { name: "Run agent", exact: true }).click();
  await expect(page.locator(".approval-panel")).toBeVisible({ timeout: 45000 });
  const proposalText = await page.locator(".approval-summary").innerText();
  const response = await request.get("http://127.0.0.1:8003/api/approvals", {
    headers: headers(),
  });
  const proposal = (await response.json()).items.find((p: { id: string }) =>
    proposalText.includes(p.id),
  );
  expect(proposal).toBeTruthy();
  await page.getByRole("button", { name: "Cancel run", exact: true }).click();
  await expect(page.locator(".conversation-head .badge")).toHaveText(
    "cancelled",
  );
  const denied = await request.post(
    `http://127.0.0.1:8003/api/approvals/${proposal.id}/decision`,
    {
      headers: headers(),
      data: {
        decision: "approve",
        reason: "Late request after cancellation must be rejected",
        idempotency_key: `late:${proposal.id}`,
      },
    },
  );
  expect(denied.status()).toBe(409);
});
test("refund requires human approval, verifies state and remains idempotent", async ({
  page,
  request,
}) => {
  const orderId = process.env.OPSPILOT_E2E_REFUND_ORDER;
  test.skip(
    !orderId,
    "Set a fresh eligible simulated order ID. This case executes one simulated refund.",
  );
  await connect(page);
  await conversation(page, `Refund approval ${Date.now()}`);
  await page.getByLabel("Affected order").selectOption(orderId!);
  await page
    .getByLabel("Customer message")
    .fill(
      "I want a full refund for this delivered order within the current refund window.",
    );
  await page.getByRole("button", { name: "Run agent", exact: true }).click();
  await expect(page.locator(".approval-panel")).toBeVisible({ timeout: 45000 });
  await expect(page.locator(".approval-panel")).toContainText(
    "Action parameters",
  );
  await page
    .getByLabel("Decision reason")
    .fill(
      "Reviewed delivery date, amount and active Refund Policy. Approve this simulated ledger refund.",
    );
  await page
    .getByRole("button", { name: "Approve & verify", exact: true })
    .click();
  await expect(page.locator(".approval-panel .badge").first()).toHaveText(
    "executed",
    { timeout: 20000 },
  );
  await expect(page.locator(".approval-panel")).toContainText("refunded");
  await expect(page.locator(".approval-panel")).toContainText("admin-local");
  await page.screenshot({
    path: "../docs/assets/verified-refund.png",
    fullPage: true,
  });
  const approvals = await request.get("http://127.0.0.1:8003/api/approvals", {
    headers: headers(),
  });
  const proposal = (await approvals.json()).items.find(
    (p: { order_id: string; status: string }) =>
      p.order_id === orderId && p.status === "executed",
  );
  expect(proposal).toBeTruthy();
  const replay = await request.post(
    `http://127.0.0.1:8003/api/approvals/${proposal.id}/decision`,
    {
      headers: headers(),
      data: {
        decision: "approve",
        reason: "Retry of the same authenticated decision",
        idempotency_key: `${proposal.id}:approve`,
      },
    },
  );
  expect(replay.ok()).toBe(true);
  const refunds = await request.get(
    `http://127.0.0.1:8003/api/refunds?order_id=${orderId}`,
    { headers: headers() },
  );
  expect(
    (await refunds.json()).items.filter(
      (r: { order_id: string }) => r.order_id === orderId,
    ),
  ).toHaveLength(1);
  const persisted = await request.get(
    `http://127.0.0.1:8003/api/orders/${orderId}`,
    { headers: headers() },
  );
  expect((await persisted.json()).status).toBe("refunded");
});
