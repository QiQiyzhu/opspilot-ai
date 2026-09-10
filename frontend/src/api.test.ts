import { afterEach, describe, expect, it, vi } from "vitest";
import {
  api,
  isTerminal,
  metric,
  money,
  parseSseBlock,
  percent,
  setToken,
  streamRun,
  type Trace,
} from "./api";
afterEach(() => vi.unstubAllGlobals());
function storage() {
  const values = new Map<string, string>();
  vi.stubGlobal("sessionStorage", {
    getItem: (k: string) => values.get(k) || null,
    setItem: (k: string, v: string) => values.set(k, v),
    removeItem: (k: string) => values.delete(k),
  });
  return values;
}
describe("authenticated request boundary", () => {
  it("attaches current session token and does not send a GET body", async () => {
    storage();
    setToken("test-only");
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response('{"id":"viewer"}', { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    await api("/me");
    expect(fetch).toHaveBeenCalledWith("/api/me", {
      method: "GET",
      headers: { Authorization: "Bearer test-only" },
    });
  });
  it("preserves the approval decision and idempotency key without client actor", async () => {
    storage();
    const fetch = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    await api("/approvals/p1/decision", "POST", {
      decision: "approve",
      reason: "Policy reviewed",
      idempotency_key: "p1:approve",
    });
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body).toEqual({
      decision: "approve",
      reason: "Policy reviewed",
      idempotency_key: "p1:approve",
    });
    expect(body).not.toHaveProperty("approved_by");
  });
  it("surfaces the server authorization rejection", async () => {
    storage();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response('{"detail":"Approver role required"}', { status: 403 }),
        ),
    );
    await expect(api("/approvals/p1/decision", "POST", {})).rejects.toThrow(
      "Approver role required",
    );
  });
});
describe("trace and measurement honesty", () => {
  it("preserves SSE frames when CRLF boundaries split across network chunks", async () => {
    storage();
    const event = {
      sequence: 9,
      type: "verification.completed",
      run_id: "r2",
      created_at: "",
      payload: { verified: true },
    };
    const encoder = new TextEncoder();
    const body = new ReadableStream({
      start(controller) {
        for (const part of [
          `id: 9\r`,
          `\ndata: ${JSON.stringify(event)}\r`,
          "\n\r",
          "\n",
        ])
          controller.enqueue(encoder.encode(part));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    const received: Trace[] = [];
    await streamRun("r2", 8, new AbortController().signal, (value) =>
      received.push(value),
    );
    expect(received).toEqual([event]);
  });
  it("parses named SSE events and ignores heartbeat / invalid frames", () => {
    const event = {
      sequence: 4,
      type: "approval.required",
      run_id: "r1",
      payload: { action: "refund" },
    };
    expect(
      parseSseBlock(
        `id: 4\nevent: approval.required\ndata: ${JSON.stringify(event)}`,
      ),
    ).toEqual(event);
    expect(parseSseBlock(": heartbeat")).toBeNull();
    expect(parseSseBlock("data: {invalid")).toBeNull();
  });
  it("distinguishes unavailable values from measured zero", () => {
    expect(metric(null)).toBe("—");
    expect(metric(0)).toBe("0");
    expect(percent(null)).toBe("—");
    expect(percent(0)).toBe("0.0%");
    expect(money(1005)).toBe("$10.05");
  });
  it("does not treat awaiting human approval as completion", () => {
    expect(isTerminal("waiting_approval")).toBe(false);
    expect(isTerminal("completed")).toBe(true);
    expect(isTerminal("failed")).toBe(true);
  });
});
