import { useState } from "react";
import { Plus } from "lucide-react";
import { api, label, type Identity, type Json, type List } from "./api";
import {
  ActionButton,
  Card,
  Empty,
  ErrorBox,
  Facts,
  Modal,
  PageTitle,
  Refresh,
  Status,
  useResource,
} from "./ui";
export default function BusinessPage({ me }: { me: Identity }) {
  const [kind, setKind] = useState("orders");
  const [rev, bump] = useState(0);
  const data = useResource<List<Json>>(`/${kind}`, { items: [] }, rev);
  const [selected, setSelected] = useState<Json | null>(null);
  const [note, setNote] = useState("");
  const [create, setCreate] = useState(false);
  const [customer, setCustomer] = useState("");
  const [order, setOrder] = useState("");
  const [subject, setSubject] = useState("");
  const writable = ["operator", "admin"].includes(me.role);
  const columns: Record<string, string[]> = {
    orders: [
      "id",
      "customer_id",
      "product_id",
      "status",
      "amount_cents",
      "quantity",
    ],
    customers: ["id", "name", "tier", "language", "email"],
    inventory: ["id", "product_id", "available", "warehouse"],
    tickets: ["id", "subject", "customer_id", "status", "priority"],
    refunds: ["id", "order_id", "status", "amount_cents", "created_at"],
    replacements: ["id", "order_id", "status", "created_at"],
  };
  return (
    <div className="page">
      <PageTitle
        eyebrow="BUSINESS RECORDS"
        title="NovaMart operations"
        action={<Refresh onClick={() => bump((v) => v + 1)} />}
      >
        Inspect actual simulated orders, inventory and support records.
      </PageTitle>
      <nav className="section-tabs">
        {Object.keys(columns).map((k) => (
          <button
            className={kind === k ? "active" : ""}
            key={k}
            onClick={() => {
              setKind(k);
              setSelected(null);
            }}
          >
            {label(k)}
          </button>
        ))}
      </nav>
      <ErrorBox error={data.error} />
      <Card
        title={label(kind)}
        action={
          kind === "tickets" && (
            <button
              className="secondary"
              disabled={!writable}
              onClick={() => setCreate(true)}
            >
              <Plus size={14} />
              Create ticket
            </button>
          )
        }
      >
        {data.data.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  {columns[kind].map((c) => (
                    <th key={c}>{label(c)}</th>
                  ))}
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.data.items.map((r, i) => (
                  <tr key={String(r.id || i)}>
                    {columns[kind].map((c) => (
                      <td key={c}>
                        {c === "status" ? (
                          <Status value={String(r[c])} />
                        ) : (
                          String(r[c] ?? "—")
                        )}
                      </td>
                    ))}
                    <td>
                      <button
                        className="text-button"
                        onClick={() => setSelected(r)}
                      >
                        Details
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title={data.loading ? "Loading records…" : "No records returned"}
          />
        )}
      </Card>
      {selected && (
        <Card title={`${label(kind)} · ${String(selected.id)}`}>
          <Facts value={selected} />
          {kind === "tickets" && (
            <>
              <label className="field">
                Add an operator note
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  rows={3}
                />
              </label>
              <ActionButton
                disabled={!writable || !note.trim()}
                onClick={async () => {
                  const result = await api<Json>(
                    `/tickets/${selected.id}/notes`,
                    "POST",
                    { text: note, idempotency_key: crypto.randomUUID() },
                  );
                  setSelected(result);
                  setNote("");
                  bump((v) => v + 1);
                }}
              >
                Save ticket note
              </ActionButton>
            </>
          )}
        </Card>
      )}
      {create && (
        <Modal title="Create support ticket" onClose={() => setCreate(false)}>
          <div className="modal-form">
            <label className="field">
              Customer ID
              <input
                value={customer}
                onChange={(e) => setCustomer(e.target.value)}
              />
            </label>
            <label className="field">
              Order ID (optional)
              <input value={order} onChange={(e) => setOrder(e.target.value)} />
            </label>
            <label className="field">
              Subject
              <input
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
              />
            </label>
            <ActionButton
              disabled={!customer || !subject}
              onClick={async () => {
                await api("/tickets", "POST", {
                  customer_id: customer,
                  subject,
                  ...(order ? { order_id: order } : {}),
                });
                setCreate(false);
                bump((v) => v + 1);
              }}
            >
              Create ticket
            </ActionButton>
          </div>
        </Modal>
      )}
    </div>
  );
}
