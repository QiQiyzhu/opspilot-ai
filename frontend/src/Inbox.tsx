import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  CheckCheck,
  ChevronRight,
  FileSearch,
  ListTree,
  MessageSquare,
  Plus,
  Send,
  ShieldCheck,
  Copy,
  Square,
  UserRound,
} from "lucide-react";
import {
  api,
  date,
  isTerminal,
  label,
  money,
  short,
  streamRun,
  type Conversation,
  type Customer,
  type Identity,
  type List,
  type Order,
  type Proposal,
  type Run,
  type Ticket,
  type Trace,
} from "./api";
import Approval from "./Approval";
import {
  Badge,
  Card,
  Empty,
  ErrorBox,
  EvidenceList,
  Facts,
  Loading,
  Modal,
  Status,
  useResource,
} from "./ui";

const steps = [
  "INTAKE",
  "UNDERSTAND",
  "RETRIEVE",
  "PLAN",
  "ACT",
  "VERIFY",
  "RESPOND",
  "COMPLETE",
];
export default function Inbox({
  me,
  revision,
  onActivity,
}: {
  me: Identity;
  revision: number;
  onActivity: () => void;
}) {
  const [localRev, bump] = useState(0);
  const rev = revision + localRev;
  const conversations = useResource<List<Conversation>>(
    "/conversations",
    { items: [] },
    rev,
  );
  const customers = useResource<List<Customer>>(
    "/customers",
    { items: [] },
    revision,
  );
  const tickets = useResource<List<Ticket>>("/tickets", { items: [] }, rev);
  const [selected, setSelected] = useState(
    () => sessionStorage.getItem(`opspilot-conversation:${me.id}`) || "",
  );
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [runId, setRunId] = useState("");
  const currentRun = useRef(runId);
  currentRun.current = runId;
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<Trace[]>([]);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [tab, setTab] = useState<"context" | "evidence" | "trace">("context");
  const [text, setText] = useState("");
  const [orderId, setOrderId] = useState("");
  const [transport, setTransport] = useState("native");
  const [provider, setProvider] = useState(me.provider);
  const [retrieval, setRetrieval] = useState("hybrid_rerank");
  const [memory, setMemory] = useState(true);
  const [multiAgent, setMultiAgent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copiedFollowUp, setCopiedFollowUp] = useState(false);
  const [streamStatus, setStreamStatus] = useState("Idle");
  const [newOpen, setNewOpen] = useState(false);
  const [newCustomer, setNewCustomer] = useState("");
  const [title, setTitle] = useState("");
  const [filter, setFilter] = useState("");
  const customerId = conversation?.customer_id || "";
  const customer = customers.data.items.find((c) => c.id === customerId);
  const orders = useResource<List<Order>>(
    customerId
      ? `/orders?customer_id=${encodeURIComponent(customerId)}`
      : "/orders",
    { items: [] },
    rev,
  );
  const selectedOrder = orders.data.items.find((o) => o.id === orderId);
  const messageEnd = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!selected && conversations.data.items.length)
      setSelected(conversations.data.items[0].id);
  }, [conversations.data.items, selected]);
  useEffect(() => {
    if (!newCustomer && customers.data.items.length)
      setNewCustomer(customers.data.items[0].id);
  }, [customers.data.items, newCustomer]);
  useEffect(() => {
    if (!selected) return;
    sessionStorage.setItem(`opspilot-conversation:${me.id}`, selected);
    let alive = true;
    setError("");
    setRunId("");
    setRun(null);
    setEvents([]);
    setProposal(null);
    api<Conversation>(`/conversations/${selected}`)
      .then((c) => {
        if (!alive) return;
        setConversation(c);
        const latest = [...(c.messages || [])].reverse().find((m) => m.run_id);
        if (latest?.run_id) setRunId(latest.run_id);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [selected, me.id]);
  useEffect(() => {
    setOrderId("");
  }, [customerId]);
  const refreshRun = useCallback(async (id: string) => {
    const current = await api<Run>(`/runs/${id}`);
    if (currentRun.current !== id) return current;
    setRun(current);
    if (current.trace?.length)
      setEvents((previous) => {
        const merged = new Map(previous.map((e) => [e.sequence, e]));
        current.trace.forEach((e) => merged.set(e.sequence, e));
        return [...merged.values()].sort((a, b) => a.sequence - b.sequence);
      });
    if (current.proposal_id) {
      const matched = await api<Proposal>(`/approvals/${current.proposal_id}`);
      if (currentRun.current !== id) return current;
      setProposal(matched);
    }
    if (isTerminal(current.status)) {
      const persisted = await api<Conversation>(
        `/conversations/${current.conversation_id}`,
      );
      if (currentRun.current === id) setConversation(persisted);
    }
    return current;
  }, []);
  useEffect(() => {
    if (!runId) return;
    let active = true;
    let cursor = 0;
    let controller = new AbortController();
    let connecting = false;
    let terminal = false;
    const refresh = async () => {
      if (!active) return;
      try {
        const current = await refreshRun(runId);
        if (isTerminal(current.status)) {
          terminal = true;
          setStreamStatus("Trace persisted");
          controller.abort();
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
    };
    const connect = async () => {
      if (connecting || terminal || !active) return;
      connecting = true;
      controller = new AbortController();
      setStreamStatus("Live · SSE");
      try {
        await streamRun(runId, cursor, controller.signal, (event) => {
          if (!active) return;
          if (event.sequence <= cursor) return;
          cursor = Math.max(cursor, event.sequence);
          setEvents((previous) =>
            previous.some((e) => e.sequence === event.sequence)
              ? previous
              : [...previous, event],
          );
          if (event.type === "response.delta") {
            setRun((previous) =>
              previous
                ? {
                    ...previous,
                    response:
                      (previous.response || "") +
                      String(event.payload.text || ""),
                  }
                : previous,
            );
          }
        });
      } catch (e) {
        if (active && !controller.signal.aborted)
          setStreamStatus(`Polling fallback · ${(e as Error).message}`);
      } finally {
        connecting = false;
        if (active) await refresh();
      }
    };
    void refresh();
    void connect();
    const timer = window.setInterval(() => {
      if (!terminal) {
        void refresh();
        if (!connecting) void connect();
      }
    }, 1000);
    return () => {
      active = false;
      controller.abort();
      clearInterval(timer);
    };
  }, [runId, refreshRun]);
  useEffect(() => {
    messageEnd.current?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }, [conversation?.messages?.length, run?.response]);
  const perform = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const createConversation = () =>
    perform(async () => {
      const created = await api<Conversation>("/conversations", "POST", {
        customer_id: newCustomer,
        title: title.trim() || "New support conversation",
      });
      setNewOpen(false);
      setTitle("");
      bump((v) => v + 1);
      setSelected(created.id);
      onActivity();
    });
  const send = () =>
    perform(async () => {
      const result = await api<{ run_id: string }>("/messages", "POST", {
        conversation_id: selected,
        text: text.trim(),
        ...(orderId ? { order_id: orderId } : {}),
        config: {
          provider,
          retrieval,
          top_k: 5,
          transport,
          memory,
          multi_agent: multiAgent,
          prompt_version: 1,
          workflow_id: "support-qa",
          workflow_version: 1,
        },
      });
      setRun(null);
      setCopiedFollowUp(false);
      setEvents([]);
      setProposal(null);
      setRunId(result.run_id);
      setText("");
      setConversation(await api<Conversation>(`/conversations/${selected}`));
      onActivity();
    });
  const canWrite = ["operator", "admin"].includes(me.role);
  const ongoing = run && !isTerminal(run.status);
  return (
    <div className="inbox-workspace">
      <aside className="inbox-list">
        <header>
          <div className="row spread">
            <h1>Support inbox</h1>
            <Badge>
              {conversations.data.total ?? conversations.data.items.length}
            </Badge>
          </div>
          <p>Every case, with a clear next step.</p>
          <button
            className="primary full"
            disabled={!canWrite}
            onClick={() => setNewOpen(true)}
          >
            <Plus size={16} />
            New conversation
          </button>
          <input
            aria-label="Search conversations"
            className="search"
            placeholder="Search conversations…"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
        </header>
        <div className="list-scroll">
          <span className="list-label">CONVERSATIONS</span>
          {conversations.loading && <Loading />}
          <ErrorBox error={conversations.error} />
          {!conversations.loading && !conversations.data.items.length && (
            <Empty title="An empty inbox">
              Start a support conversation to run the agent.
            </Empty>
          )}
          {conversations.data.items
            .filter((c) =>
              `${c.title} ${c.customer_id}`
                .toLowerCase()
                .includes(filter.toLowerCase()),
            )
            .map((c) => (
              <button
                className={`conversation-item ${selected === c.id ? "selected" : ""}`}
                key={c.id}
                onClick={() => {
                  setSelected(c.id);
                  setText("");
                }}
              >
                <span className="row spread">
                  <strong>
                    {customers.data.items.find((x) => x.id === c.customer_id)
                      ?.name || c.customer_id}
                  </strong>
                  <ChevronRight size={13} />
                </span>
                <span>{c.title}</span>
                <small>{date(c.created_at)}</small>
              </button>
            ))}
          <span className="list-label">SUPPORT TICKETS</span>
          {tickets.data.items.slice(0, 8).map((t) => (
            <div className="ticket-mini" key={t.id}>
              <strong>{t.subject}</strong>
              <span className="row">
                <Status value={t.status} />
                <small>{t.priority}</small>
              </span>
            </div>
          ))}
        </div>
        <footer>
          <ShieldCheck size={15} />
          <span>Business actions require approval</span>
        </footer>
      </aside>
      <section className="conversation-area">
        <header className="conversation-head">
          <div className="row">
            <div className="avatar">
              {customer?.name[0] || <MessageSquare size={18} />}
            </div>
            <div>
              <h2>{conversation?.title || "A workspace for accountable AI"}</h2>
              <p>
                {customer
                  ? `${customer.name} · ${customer.tier} customer`
                  : "Select a case or start a conversation"}
              </p>
            </div>
          </div>
          {run && <Status value={run.status} />}
        </header>
        <div className="messages">
          {!conversation ? (
            <div className="welcome">
              <div className="welcome-mark">
                <ShieldCheck size={32} />
              </div>
              <span className="eyebrow">NOVAMART SUPPORT OPERATIONS</span>
              <h2>
                Understand. Act.
                <br />
                Verify every outcome.
              </h2>
              <p>
                Ground replies in current policies. Review proposed business
                actions and follow every step of the agent.
              </p>
              <div className="welcome-cards">
                <span>
                  <FileSearch size={18} />
                  Policy evidence
                </span>
                <span>
                  <ShieldCheck size={18} />
                  Human approvals
                </span>
                <span>
                  <CheckCheck size={18} />
                  Verified outcomes
                </span>
              </div>
            </div>
          ) : (
            <>
              {(conversation.messages || []).map((m) => (
                <article
                  className={`message ${m.role === "user" ? "customer-message" : "agent-message"}`}
                  key={m.id}
                >
                  <div className="message-by">
                    <span>
                      {m.role === "user" ? (
                        <UserRound size={14} />
                      ) : (
                        <ShieldCheck size={14} />
                      )}{" "}
                      {m.role === "user"
                        ? customer?.name || "Customer"
                        : "OpsPilot"}
                    </span>
                    <time>{date(m.created_at)}</time>
                  </div>
                  <p>{m.text}</p>
                  {m.run_id && (
                    <button
                      className="text-button"
                      onClick={() => {
                        setRunId(m.run_id!);
                        setTab("trace");
                      }}
                    >
                      View run <ArrowUpRight size={12} />
                    </button>
                  )}
                </article>
              ))}
              {ongoing && run?.response && (
                <article className="message agent-message">
                  <div className="message-by">OpsPilot · streaming</div>
                  <p>{run.response}</p>
                </article>
              )}
              {run && (
                <section className="run-progress">
                  <div className="row spread">
                    <strong>
                      <ListTree size={15} />
                      Agent activity
                    </strong>
                    <span className="live-label">{streamStatus}</span>
                  </div>
                  <div className="progress-steps">
                    {steps.map((s, i) => (
                      <span
                        key={s}
                        className={
                          s === run.state
                            ? "current"
                            : i < steps.indexOf(run.state)
                              ? "done"
                              : ""
                        }
                        title={s}
                      >
                        {label(s.toLowerCase())}
                      </span>
                    ))}
                  </div>
                  <div className="row spread">
                    <small>
                      {run.state} · {short(run.id)} ·{" "}
                      {run.config?.provider
                        ? String(run.config.provider)
                        : provider}
                    </small>
                    <button
                      className="text-button"
                      onClick={() => setTab("trace")}
                    >
                      Inspect trace <ArrowUpRight size={12} />
                    </button>
                  </div>
                  {run.error && <ErrorBox error={run.error} />}
                </section>
              )}
              {proposal && (
                <Approval
                  proposal={proposal}
                  role={me.role}
                  onChange={async () => {
                    await refreshRun(runId);
                    bump((v) => v + 1);
                    onActivity();
                  }}
                />
              )}
              <div ref={messageEnd} />
              {run?.next_step && !ongoing && (
                <section className="next-step-panel" aria-label="Required next step">
                  <span className="eyebrow">NEXT STEP · {run.next_step.kind === "clarify" ? "CUSTOMER CHOICE" : "POLICY REVIEW"}</span>
                  <h3>{run.next_step.title}</h3>
                  <p>{run.next_step.question}</p>
                  <p className="small muted">{run.next_step.detail}</p>
                  <button
                    className="secondary"
                    onClick={() => void perform(async () => {
                      await navigator.clipboard.writeText(run.next_step!.draft);
                      setCopiedFollowUp(true);
                    })}
                  >
                    <Copy size={14} /> {copiedFollowUp ? "Copied follow-up question" : "Copy follow-up question"}
                  </button>
                  <small>Copying sends nothing and creates no request. Record the customer's answer as a new message.</small>
                </section>
              )}
            </>
          )}
        </div>
        <div className="composer">
          <ErrorBox error={error} />
          {conversation && (
            <>
              <div className="composer-toolbar">
                <label>
                  Order
                  <select
                    aria-label="Affected order"
                    value={orderId}
                    onChange={(e) => setOrderId(e.target.value)}
                  >
                    <option value="">No specific order</option>
                    {orders.data.items
                      .filter((o) => o.customer_id === customerId)
                      .map((o) => (
                        <option key={o.id} value={o.id}>
                          {o.id} · {o.status}
                        </option>
                      ))}
                  </select>
                </label>
                <label>
                  Transport
                  <select
                    aria-label="Tool transport"
                    value={transport}
                    onChange={(e) => setTransport(e.target.value)}
                  >
                    <option value="native">Native</option>
                    <option value="mcp">MCP HTTP</option>
                  </select>
                </label>
                <details className="run-settings">
                  <summary>Run settings</summary>
                  <div>
                    <label className="field">
                      Provider
                      <select
                        value={provider}
                        onChange={(e) => setProvider(e.target.value)}
                      >
                        <option value="fake">
                          Fake · deterministic fixture
                        </option>
                        <option value="deepseek">DeepSeek · server API</option>
                        <option value="openai-compatible">
                          OpenAI compatible · configured key
                        </option>
                        <option value="qwen">Qwen · configured key</option>
                      </select>
                    </label>
                    <label className="field">
                      Retrieval
                      <select
                        value={retrieval}
                        onChange={(e) => setRetrieval(e.target.value)}
                      >
                        {["keyword", "dense", "hybrid", "hybrid_rerank"].map(
                          (x) => (
                            <option key={x}>{x}</option>
                          ),
                        )}
                      </select>
                    </label>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={memory}
                        onChange={(e) => setMemory(e.target.checked)}
                      />
                      Verified memory
                    </label>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={multiAgent}
                        onChange={(e) => setMultiAgent(e.target.checked)}
                      />
                      Router + specialists
                    </label>
                  </div>
                </details>
              </div>
              <textarea
                aria-label="Customer message"
                placeholder="Enter the customer’s question or describe their issue…"
                value={text}
                onChange={(e) => setText(e.target.value)}
                rows={3}
                maxLength={8000}
                onKeyDown={(e) => {
                  if (
                    e.ctrlKey &&
                    e.key === "Enter" &&
                    text.trim() &&
                    !ongoing &&
                    !busy
                  )
                    void send();
                }}
              />
              <div className="row spread">
                <span className="small muted">
                  {provider === "fake"
                    ? "Deterministic provider · no LLM inference"
                    : "Uses server-configured provider"}{" "}
                  · Ctrl ↵
                </span>
                {ongoing ? (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      void perform(async () => {
                        await api(`/runs/${runId}/cancel`, "POST", {});
                        await refreshRun(runId);
                      })
                    }
                  >
                    <Square size={13} />
                    Cancel run
                  </button>
                ) : (
                  <button
                    className="primary"
                    disabled={busy || !canWrite || text.trim().length < 3}
                    onClick={() => void send()}
                  >
                    <Send size={15} />
                    {busy ? "Submitting…" : "Run agent"}
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      </section>
      <aside className="context-area">
        <nav className="context-tabs" aria-label="Case context">
          {[
            ["context", "Customer"],
            ["evidence", "Evidence"],
            ["trace", "Trace"],
          ].map(([key, name]) => (
            <button
              className={tab === key ? "active" : ""}
              key={key}
              onClick={() => setTab(key as typeof tab)}
            >
              {name}
              {key === "evidence" && !!run?.evidence?.length && (
                <span>{run.evidence.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="context-content">
          {tab === "context" && (
            <>
              <Card title="Customer profile">
                {customer ? (
                  <>
                    <div className="profile">
                      <div className="avatar large">{customer.name[0]}</div>
                      <h3>{customer.name}</h3>
                      <p>{customer.email}</p>
                      <Badge>{customer.tier}</Badge>
                    </div>
                    <Facts
                      value={{
                        customer_id: customer.id,
                        language: customer.language,
                        member_since: date(customer.created_at),
                      }}
                    />
                  </>
                ) : (
                  <Empty title="No customer selected" />
                )}
              </Card>
              <Card title="Order details">
                {selectedOrder ? (
                  <>
                    <div className="row spread">
                      <strong>{selectedOrder.id}</strong>
                      <Status value={selectedOrder.status} />
                    </div>
                    <h3>
                      {selectedOrder.product?.name || selectedOrder.product_id}
                    </h3>
                    <Facts
                      value={{
                        amount: money(selectedOrder.amount_cents),
                        quantity: selectedOrder.quantity,
                        purchased: date(selectedOrder.purchased_at),
                        delivered: date(selectedOrder.delivered_at),
                        tracking: selectedOrder.tracking || "Not available",
                        version: selectedOrder.version,
                      }}
                    />
                  </>
                ) : (
                  <Empty title="Select an affected order">
                    Choose an order in the message composer to inspect its
                    current business state.
                  </Empty>
                )}
              </Card>
              {run?.verification?.length ? (
                <Card title="Business verification">
                  {run.verification.map((v, i) => (
                    <Facts key={i} value={v} />
                  ))}
                </Card>
              ) : null}
            </>
          )}
          {tab === "evidence" && (
            <>
              <div className="panel-intro">
                <FileSearch size={20} />
                <h3>Grounded in current policy</h3>
                <p>
                  Retrieved sources from this run. Superseded policies must be
                  excluded by the server.
                </p>
              </div>
              <EvidenceList items={run?.evidence || []} />
            </>
          )}
          {tab === "trace" && (
            <>
              <div className="panel-intro">
                <ListTree size={20} />
                <h3>Auditable execution</h3>
                <p>
                  Structured plans and observations. These events are not
                  private model reasoning.
                </p>
              </div>
              {run && (
                <div className="trace-summary">
                  <Facts
                    value={{
                      run: run.id,
                      state: run.state,
                      model: run.config?.provider,
                      transport: run.config?.transport,
                      duration_ms: run.duration_ms,
                      tokens: run.tokens,
                    }}
                  />
                  {isTerminal(run.status) && (
                    <button
                      className="secondary full"
                      disabled={busy || !canWrite}
                      onClick={() =>
                        void perform(async () => {
                          const r = await api<{ run_id?: string; id?: string }>(
                            `/runs/${runId}/replay`,
                            "POST",
                            {},
                          );
                          setEvents([]);
                          setProposal(null);
                          setRunId(r.run_id || r.id || "");
                          onActivity();
                        })
                      }
                    >
                      Replay with new approval
                    </button>
                  )}
                </div>
              )}
              {events.length ? (
                <div className="trace-list">
                  {events.map((e, i) => (
                    <details key={`${e.sequence}-${i}`} className="trace-event">
                      <summary>
                        <span className="trace-dot" />
                        <div>
                          <strong>{label(e.type || "event")}</strong>
                          <small>
                            #{e.sequence} · {date(e.created_at)}
                          </small>
                        </div>
                      </summary>
                      <Facts value={e.payload} />
                    </details>
                  ))}
                </div>
              ) : (
                <Empty title="No run events yet" />
              )}
            </>
          )}
        </div>
      </aside>
      {newOpen && (
        <Modal
          title="New support conversation"
          onClose={() => setNewOpen(false)}
        >
          <form
            className="modal-form"
            onSubmit={(e) => {
              e.preventDefault();
              void createConversation();
            }}
          >
            <label className="field">
              Customer
              <select
                value={newCustomer}
                onChange={(e) => setNewCustomer(e.target.value)}
              >
                {customers.data.items.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} · {c.id}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Conversation title
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Damaged delivery · replacement"
                maxLength={200}
                autoFocus
              />
            </label>
            <div className="info-box">
              NovaMart is simulated business data. Agent actions affect this
              local demonstration database.
            </div>
            <ErrorBox error={error} />
            <button className="primary full" disabled={busy || !newCustomer}>
              Create conversation
            </button>
          </form>
        </Modal>
      )}
    </div>
  );
}
