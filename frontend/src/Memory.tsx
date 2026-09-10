import { useState } from "react";
import { Brain, Plus } from "lucide-react";
import {
  api,
  date,
  type Customer,
  type Identity,
  type List,
  type Memory,
} from "./api";
import {
  ActionButton,
  Badge,
  Card,
  Empty,
  ErrorBox,
  Modal,
  PageTitle,
  Status,
  useResource,
} from "./ui";
export default function MemoryPage({ me }: { me: Identity }) {
  const [rev, bump] = useState(0);
  const resource = useResource<List<Memory>>("/memories", { items: [] }, rev);
  const customers = useResource<List<Customer>>("/customers", { items: [] });
  const [open, setOpen] = useState(false);
  const [customer, setCustomer] = useState("");
  const [scope, setScope] = useState("case");
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [source, setSource] = useState("");
  const [filter, setFilter] = useState("all");
  const writable = ["operator", "admin"].includes(me.role);
  const items = resource.data.items.filter(
    (m) => filter === "all" || (filter === "valid" ? m.valid : !m.valid),
  );
  return (
    <div className="page">
      <PageTitle
        eyebrow="CONTEXT WITH PROVENANCE"
        title="Verified memory"
        action={
          <button
            className="primary"
            disabled={!writable}
            onClick={() => setOpen(true)}
          >
            <Plus size={15} />
            Record verified fact
          </button>
        }
      >
        Useful customer facts, scoped sources and explicit invalidation. Model
        guesses do not belong here.
      </PageTitle>
      <div className="info-box">
        <Brain size={19} />
        <span>
          Conversation history, case facts, customer preferences and operational
          observations have different scopes. Expired or invalidated facts must
          not enter retrieval.
        </span>
      </div>
      <div className="row filter-row">
        {["all", "valid", "invalidated"].map((x) => (
          <button
            className={`chip ${filter === x ? "active" : ""}`}
            key={x}
            onClick={() => setFilter(x)}
          >
            {x}
          </button>
        ))}
      </div>
      <ErrorBox error={resource.error} />
      {items.length ? (
        <div className="memory-grid">
          {items.map((m) => (
            <Card
              key={m.id}
              title={m.key}
              action={<Status value={m.valid ? "active" : "invalidated"} />}
            >
              <div className="row">
                <Badge>{m.scope}</Badge>
                <code>{m.customer_id || "operational"}</code>
              </div>
              <p className="memory-value">{m.value}</p>
              <div className="memory-source">
                <strong>Verified source</strong>
                <p>{m.source}</p>
                <small>
                  Confidence {m.confidence} · {date(m.created_at)}
                  <br />
                  Expires {m.expires_at ? date(m.expires_at) : "not set"}
                </small>
              </div>
              <div className="row">
                {m.valid && (
                  <ActionButton
                    className="secondary"
                    disabled={!writable}
                    onClick={async () => {
                      await api(`/memories/${m.id}/invalidate`, "POST", {
                        reason:
                          "Operator invalidated from console after review",
                      });
                      bump((v) => v + 1);
                    }}
                  >
                    Invalidate
                  </ActionButton>
                )}
                {me.role === "admin" && (
                  <details className="delete-confirm">
                    <summary>Delete…</summary>
                    <p>
                      Permanently remove this memory from the demo database.
                    </p>
                    <ActionButton
                      className="secondary danger-text"
                      onClick={async () => {
                        await api(`/memories/${m.id}`, "DELETE");
                        bump((v) => v + 1);
                      }}
                    >
                      Confirm deletion
                    </ActionButton>
                  </details>
                )}
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <Empty
          title={resource.loading ? "Loading memory…" : "No matching memory"}
        >
          Verified operator facts and successfully verified workflows appear
          here.
        </Empty>
      )}
      {open && (
        <Modal title="Record a verified fact" onClose={() => setOpen(false)}>
          <div className="modal-form">
            <label className="field">
              Customer
              <select
                value={customer}
                onChange={(e) => setCustomer(e.target.value)}
              >
                <option value="">Choose customer</option>
                {customers.data.items.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Scope
              <select value={scope} onChange={(e) => setScope(e.target.value)}>
                {["case", "preference", "operational"].map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Fact key
              <input
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="serial_number"
              />
            </label>
            <label className="field">
              Verified value
              <textarea
                rows={3}
                value={value}
                onChange={(e) => setValue(e.target.value)}
              />
            </label>
            <label className="field">
              Source / evidence
              <input
                value={source}
                onChange={(e) => setSource(e.target.value)}
                placeholder="Customer confirmed in ticket …"
              />
            </label>
            <ActionButton
              disabled={!customer || !key || !value || !source}
              onClick={async () => {
                await api("/memories", "POST", {
                  customer_id: customer,
                  scope,
                  key,
                  value,
                  source,
                });
                setOpen(false);
                bump((v) => v + 1);
              }}
            >
              Save verified fact
            </ActionButton>
          </div>
        </Modal>
      )}
    </div>
  );
}
