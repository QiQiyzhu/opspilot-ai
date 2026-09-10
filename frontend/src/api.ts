export type Json = Record<string, unknown>;
export type List<T> = { items: T[]; total?: number };
export type Identity = {
  id: string;
  name: string;
  role: string;
  business: string;
  provider: string;
};
export type Customer = {
  id: string;
  name: string;
  email: string;
  tier: string;
  language: string;
  created_at: string;
};
export type Order = {
  id: string;
  customer_id: string;
  product_id: string;
  quantity: number;
  amount_cents: number;
  status: string;
  purchased_at: string;
  delivered_at?: string;
  tracking?: string;
  version: number;
  product?: { id: string; name: string; sku: string; warranty_days: number };
};
export type Message = {
  id: string;
  role: string;
  text: string;
  run_id?: string;
  created_at: string;
};
export type Conversation = {
  id: string;
  customer_id: string;
  title: string;
  created_at: string;
  messages?: Message[];
};
export type Ticket = {
  id: string;
  customer_id: string;
  order_id?: string;
  subject: string;
  priority: string;
  status: string;
  notes?: { text: string; actor: string; created_at: string }[];
};
export type Evidence = {
  chunk_id?: string;
  document_id?: string;
  id?: string;
  title?: string;
  section?: string;
  text?: string;
  version?: number;
  score?: number;
  lexical_score?: number;
  vector_score?: number;
  rerank_score?: number;
  [key: string]: unknown;
};
export type Trace = {
  sequence: number;
  type: string;
  run_id: string;
  created_at: string;
  payload: Json;
};
export type Run = {
  id: string;
  conversation_id: string;
  status: string;
  state: string;
  category?: string;
  next_step?: {
    kind: "clarify" | "review";
    title: string;
    question: string;
    detail: string;
    draft: string;
    contract_version: number;
  } | null;
  input: string;
  response?: string;
  config: Json;
  plan: unknown[];
  evidence: Evidence[];
  verification: unknown[];
  tool_calls: Json[];
  trace: Trace[];
  proposal_id?: string;
  duration_ms?: number;
  tokens?: { input: number; output: number } | null;
  error?: string;
  created_at: string;
};
export type Proposal = {
  id: string;
  run_id?: string;
  order_id: string;
  action: string;
  reason: string;
  evidence: Evidence[];
  parameters: Json;
  status: string;
  requested_by: string;
  approved_by?: string;
  approved_at?: string;
  before_state?: Json;
  after_state?: Json;
  verification?: unknown;
};
export type Knowledge = {
  id: string;
  title: string;
  category: string;
  version: number;
  active: boolean;
  effective_date: string;
  expires_at?: string;
  format: string;
  content: string;
  metadata: Json;
  chunks?: { id: string; section: string; text: string; version: number }[];
};
export type Registry = {
  id: string;
  name: string;
  active_version: number;
  versions: {
    version: number;
    content?: string;
    definition?: Json;
    created_at?: string;
  }[];
};
export type Evaluation = {
  id: string;
  kind: string;
  status: string;
  provider?: string;
  dataset_id?: string;
  metrics?: Json;
  results?: Json[];
  config?: Json;
  created_at?: string;
  [key: string]: unknown;
};
export type Memory = {
  id: string;
  customer_id?: string;
  scope: string;
  key: string;
  value: string;
  source: string;
  confidence: number;
  expires_at?: string;
  valid: boolean;
  created_at: string;
};
export type Alert = {
  id: string;
  metric: string;
  threshold: number;
  current_value: number;
  first_seen: string;
  status: string;
  [key: string]: unknown;
};
export type Dashboard = {
  business: string;
  provider: string;
  run_count: number;
  completed: number;
  failed: number;
  waiting_approval: number;
  p50_ms: number | null;
  p95_ms: number | null;
  tool_error_rate: number | null;
  escalation_rate: number | null;
  unsafe_action_count: number;
  token_usage: number | null;
  task_success_rate: number | null;
  retrieval_recall: number | null;
  category_counts: Json[];
  daily_runs: Json[];
  recent_runs: Run[];
  alerts: Alert[];
  limitations: string[];
};
export function token(): string {
  return sessionStorage.getItem("opspilot-token") || "";
}
export function setToken(value: string) {
  if (value) sessionStorage.setItem("opspilot-token", value);
  else sessionStorage.removeItem("opspilot-token");
}
async function responseError(response: Response): Promise<string> {
  const data = await response.json().catch(() => ({}));
  return typeof data.detail === "string"
    ? data.detail
    : JSON.stringify(data.detail || `HTTP ${response.status}`);
}
export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token()}`,
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api${path}`, {
    method,
    headers,
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) throw new Error(await responseError(response));
  if (response.status === 204) return undefined as T;
  return response.json();
}
export function parseSseBlock(block: string): Trace | null {
  const data = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return null;
  try {
    return JSON.parse(data) as Trace;
  } catch {
    return null;
  }
}
export async function streamRun(
  id: string,
  after: number,
  signal: AbortSignal,
  onEvent: (event: Trace) => void,
): Promise<void> {
  const response = await fetch(`/api/runs/${id}/events?after=${after}`, {
    headers: {
      Authorization: `Bearer ${token()}`,
      ...(after ? { "Last-Event-ID": String(after) } : {}),
    },
    signal,
  });
  if (!response.ok) throw new Error(await responseError(response));
  if (!response.body)
    throw new Error("Streaming is unavailable in this browser.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (!signal.aborted) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer = (buffer + decoder.decode(value, { stream: true })).replaceAll(
        "\r\n",
        "\n",
      );
      let end;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const event = parseSseBlock(buffer.slice(0, end));
        buffer = buffer.slice(end + 2);
        if (event) onEvent(event);
      }
    }
  } finally {
    reader.releaseLock();
  }
}
export const isTerminal = (status: string) =>
  ["completed", "failed", "cancelled"].includes(status);
export const money = (cents?: number) =>
  cents === undefined
    ? "Unavailable"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
      }).format(cents / 100);
export const metric = (value: unknown, suffix = "") =>
  value === undefined || value === null
    ? "—"
    : `${typeof value === "number" ? Number(value.toFixed(2)) : String(value)}${suffix}`;
export const percent = (value: unknown) =>
  typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "—";
export const label = (value: string) =>
  value.replaceAll("_", " ").replaceAll(".", " · ");
export const short = (value?: string) => (value ? value.slice(0, 14) : "—");
export const date = (value?: string) =>
  value
    ? new Date(value).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "—";
