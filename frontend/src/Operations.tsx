import { useState } from "react";
import {
  Activity,
  ArrowUpRight,
  CheckCheck,
  Clock3,
  FlaskConical,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import {
  api,
  date,
  label,
  metric,
  percent,
  short,
  type Alert,
  type Dashboard,
  type Evaluation,
  type Identity,
  type Json,
  type List,
  type Proposal,
  type Run,
} from "./api";
import Approval from "./Approval";
import {
  ActionButton,
  Badge,
  Card,
  Empty,
  ErrorBox,
  Facts,
  Loading,
  PageTitle,
  Refresh,
  Status,
  useResource,
} from "./ui";
function Stat({
  title,
  value,
  note,
  icon,
}: {
  title: string;
  value: string;
  note: string;
  icon: React.ReactNode;
}) {
  return (
    <article className="stat">
      <div className="row spread">
        <span>{title}</span>
        {icon}
      </div>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}
export function DashboardPage({ revision }: { revision: number }) {
  const [rev, bump] = useState(0);
  const { data, error, loading } = useResource<Dashboard | null>(
    "/dashboard",
    null,
    revision + rev,
  );
  return (
    <div className="page">
      <PageTitle
        eyebrow="OPERATIONS / LIVE TELEMETRY"
        title="Operational overview"
        action={<Refresh onClick={() => bump((v) => v + 1)} />}
      >
        A clear view of agent activity, operational risk and verified outcomes.
      </PageTitle>
      <div className="source-note">
        <span className="live-dot" />
        Recorded local runs <Badge>SIMULATED BUSINESS</Badge>
        <span>Completion is separate from evaluated task success.</span>
      </div>
      <ErrorBox error={error} />
      {loading && !data && <Loading />}
      {data && (
        <>
          <div className="stats-grid">
            <Stat
              title="Agent runs"
              value={metric(data.run_count)}
              note={`${metric(data.completed)} completed · ${metric(data.failed)} failed`}
              icon={<Activity size={19} />}
            />
            <Stat
              title="Awaiting approval"
              value={metric(data.waiting_approval)}
              note="Actions paused at the human gate"
              icon={<ShieldCheck size={19} />}
            />
            <Stat
              title="P95 run latency"
              value={metric(data.p95_ms, " ms")}
              note={`P50 ${metric(data.p50_ms, " ms")} · current stored runs`}
              icon={<Clock3 size={19} />}
            />
            <Stat
              title="Unsafe actions"
              value={metric(data.unsafe_action_count)}
              note="From recorded safety evaluations"
              icon={<ShieldAlert size={19} />}
            />
          </div>
          <div className="two-columns">
            <Card
              title="Quality & operational signals"
              action={<Badge>Measured, never estimated</Badge>}
            >
              <div className="signal-grid">
                {[
                  ["Task success", percent(data.task_success_rate)],
                  ["Retrieval recall", percent(data.retrieval_recall)],
                  ["Tool error rate", percent(data.tool_error_rate)],
                  ["Escalation rate", percent(data.escalation_rate)],
                  ["Token usage", metric(data.token_usage)],
                  ["Provider", data.provider],
                ].map(([key, val]) => (
                  <div key={key}>
                    <span>{key}</span>
                    <strong>{val}</strong>
                  </div>
                ))}
              </div>
              <p className="card-foot">
                — means unavailable. Fake-provider latency and tokens do not
                represent real LLM inference.
              </p>
            </Card>
            <Card
              title="Monitoring alerts"
              action={
                <ActionButton
                  className="secondary"
                  onClick={async () => {
                    await api("/alerts/evaluate", "POST", {});
                    bump((v) => v + 1);
                  }}
                >
                  Evaluate rules
                </ActionButton>
              }
            >
              {data.alerts?.length ? (
                data.alerts.map((a) => (
                  <AlertRow
                    key={a.id}
                    alert={a}
                    refresh={() => bump((v) => v + 1)}
                  />
                ))
              ) : (
                <Empty title="No recorded alerts">
                  Evaluate rules against real stored telemetry.
                </Empty>
              )}
            </Card>
          </div>
          <Card
            title="Recent agent runs"
            action={<Badge>{data.recent_runs?.length || 0} records</Badge>}
          >
            <RunsTable runs={data.recent_runs || []} />
          </Card>
          <Card title="Telemetry boundaries">
            <ul className="plain-list">
              {(data.limitations?.length
                ? data.limitations
                : [
                    "NovaMart contains simulated business data.",
                    "Provider and retrieval modes must be interpreted using their recorded implementation.",
                    "No production user, revenue or efficiency claims are made.",
                  ]
              ).map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
function AlertRow({ alert, refresh }: { alert: Alert; refresh: () => void }) {
  return (
    <div className="alert-row">
      <div>
        <strong>{label(alert.metric)}</strong>
        <p>
          Observed {metric(alert.current_value)} · threshold{" "}
          {metric(alert.threshold)}
        </p>
        <small>{date(alert.first_seen)}</small>
      </div>
      <div>
        <Status value={alert.status} />
        {alert.status !== "acknowledged" && (
          <ActionButton
            className="text-button"
            onClick={async () => {
              await api(`/alerts/${alert.id}/acknowledge`, "POST", {});
              refresh();
            }}
          >
            Acknowledge
          </ActionButton>
        )}
      </div>
    </div>
  );
}
function RunsTable({ runs }: { runs: Run[] }) {
  return runs.length ? (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Run</th>
            <th>Category</th>
            <th>Status</th>
            <th>Provider</th>
            <th>Latency</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td>
                <code>{short(r.id)}</code>
              </td>
              <td>{label(r.category || "unclassified")}</td>
              <td>
                <Status value={r.status} />
              </td>
              <td>{String(r.config?.provider || "—")}</td>
              <td>{metric(r.duration_ms, " ms")}</td>
              <td>{date(r.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <Empty title="No runs recorded yet" />
  );
}
export function ApprovalsPage({
  me,
  revision,
  onActivity,
}: {
  me: Identity;
  revision: number;
  onActivity: () => void;
}) {
  const [rev, bump] = useState(0);
  const { data, error, loading } = useResource<List<Proposal>>(
    "/approvals",
    { items: [] },
    revision + rev,
  );
  const [selected, setSelected] = useState("");
  const [show, setShow] = useState("all");
  const filtered = data.items.filter(
    (p) => show === "all" || p.status === show,
  );
  const chosen = data.items.find((p) => p.id === selected) || filtered[0];
  return (
    <div className="page">
      <PageTitle
        eyebrow="BUSINESS CONTROLS"
        title="Approval center"
        action={<Refresh onClick={() => bump((v) => v + 1)} />}
      >
        Review policy evidence and exact parameters before a business action
        executes.
      </PageTitle>
      <div className="row filter-row">
        {["all", "pending", "executed", "rejected"].map((s) => (
          <button
            className={show === s ? "chip active" : "chip"}
            key={s}
            onClick={() => setShow(s)}
          >
            {label(s)}{" "}
            {s === "pending"
              ? data.items.filter((p) => p.status === s).length
              : ""}
          </button>
        ))}
        <Badge>
          Identity: {me.name} · {me.role}
        </Badge>
      </div>
      <ErrorBox error={error} />
      {loading && !data.items.length ? (
        <Loading />
      ) : !filtered.length ? (
        <Empty title="No matching approval requests">
          Start a refund, replacement or cancellation workflow from the inbox.
        </Empty>
      ) : (
        <div className="approval-grid">
          <div className="approval-list">
            {filtered.map((p) => (
              <button
                className={`approval-item ${chosen?.id === p.id ? "selected" : ""}`}
                key={p.id}
                onClick={() => setSelected(p.id)}
              >
                <div className="row spread">
                  <strong>{label(p.action)}</strong>
                  <Status value={p.status} />
                </div>
                <code>{p.order_id}</code>
                <p>{p.reason}</p>
                <small>{short(p.id)}</small>
              </button>
            ))}
          </div>
          {chosen && (
            <Approval
              key={chosen.id}
              proposal={chosen}
              role={me.role}
              onChange={() => {
                bump((v) => v + 1);
                onActivity();
              }}
            />
          )}
        </div>
      )}
    </div>
  );
}
export function EvaluationPage({ me }: { me: Identity }) {
  const [rev, bump] = useState(0);
  const reports = useResource<List<Evaluation>>(
    "/evaluations",
    { items: [] },
    rev,
  );
  const datasets = useResource<List<Json>>(
    "/evaluations/datasets",
    { items: [] },
    rev,
  );
  const shipped = useResource<List<Json>>(
    "/evaluations/reports",
    { items: [] },
    rev,
  );
  const [selected, setSelected] = useState("");
  const [kind, setKind] = useState("rag");
  const [mode, setMode] = useState("hybrid_rerank");
  const [dataset, setDataset] = useState("");
  const [detail, setDetail] = useState<Evaluation | null>(null);
  const [error, setError] = useState("");
  const pick = async (id: string) => {
    setSelected(id);
    setError("");
    try {
      setDetail(await api<Evaluation>(`/evaluations/${id}`));
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className="page">
      <PageTitle
        eyebrow="EVALUATION LAB"
        title="Evidence over assumptions"
        action={<Badge tone="warn">SYNTHETIC BENCHMARK</Badge>}
      >
        Compare retrieval and agent behavior on labeled NovaMart scenarios.
      </PageTitle>
      <div className="info-box">
        <FlaskConical size={18} />
        <span>
          These are synthetic cases against simulated policies. Deterministic
          provider results validate system behavior, not LLM quality or real
          customer outcomes.
        </span>
      </div>
      <div className="two-columns">
        <Card title="Run an offline evaluation">
          <div className="form-grid">
            <label className="field">
              Evaluation type
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                <option value="rag">Retrieval quality</option>
                <option value="agent">Agent scenarios</option>
              </select>
            </label>
            <label className="field">
              Retrieval mode
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                {["keyword", "dense", "hybrid", "hybrid_rerank"].map((x) => (
                  <option key={x}>{x}</option>
                ))}
              </select>
            </label>
            <label className="field">
              Dataset
              <select
                value={dataset}
                onChange={(e) => setDataset(e.target.value)}
              >
                <option value="">Server default for selected type</option>
                {datasets.data.items.map((d) => (
                  <option key={String(d.id)} value={String(d.id)}>
                    {String(d.label || d.id)}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <ActionButton
            disabled={!["operator", "admin"].includes(me.role)}
            onClick={async () => {
              const result = await api<Evaluation>("/evaluations", "POST", {
                kind,
                ...(dataset ? { dataset_id: dataset } : {}),
                prompt_version: 1,
                mode,
              });
              setDetail(result);
              setSelected(result.id);
              bump((v) => v + 1);
            }}
          >
            <FlaskConical size={15} />
            Run actual evaluation
          </ActionButton>
        </Card>
        <Card title="Dataset provenance">
          {datasets.error ? (
            <ErrorBox error={datasets.error} />
          ) : datasets.data.items.length ? (
            datasets.data.items.map((d) => (
              <div className="dataset-row" key={String(d.id)}>
                <div className="row spread">
                  <strong>{String(d.label || d.id)}</strong>
                  <Badge>{String(d.case_count)} cases</Badge>
                </div>
                <p>{String(d.provenance || "Synthetic policy scenarios")}</p>
                <small>
                  Review: {String(d.human_review_status || "Not reported")}
                </small>
              </div>
            ))
          ) : (
            <Empty title="No datasets returned" />
          )}
        </Card>
      </div>
      <ErrorBox error={error || reports.error || shipped.error} />
      <BenchmarkComparisons reports={shipped.data.items} />
      <Card
        title="Evaluation history"
        action={<Refresh onClick={() => bump((v) => v + 1)} />}
      >
        {reports.loading && !reports.data.items.length ? (
          <Loading />
        ) : reports.data.items.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Report</th>
                  <th>Kind</th>
                  <th>Provider</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {reports.data.items.map((r) => (
                  <tr
                    className={selected === r.id ? "selected-row" : ""}
                    key={r.id}
                  >
                    <td>
                      <code>{short(r.id)}</code>
                    </td>
                    <td>{r.kind}</td>
                    <td>{r.provider || "—"}</td>
                    <td>
                      <Status value={r.status} />
                    </td>
                    <td>{date(r.created_at)}</td>
                    <td>
                      <button
                        className="text-button"
                        onClick={() => void pick(r.id)}
                      >
                        Inspect <ArrowUpRight size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No evaluations have run">
            Run an evaluation to persist measured metrics and case outcomes.
          </Empty>
        )}
      </Card>
      {detail && (
        <Card
          title={`Report · ${detail.kind}`}
          action={<Status value={detail.status} />}
        >
          <div className="metric-cards">
            {Object.entries(detail.metrics || {})
              .filter(([, v]) => typeof v === "number" || v === null)
              .map(([k, v]) => (
                <div key={k}>
                  <span>{label(k)}</span>
                  <strong>
                    {typeof v === "object" ? JSON.stringify(v) : metric(v)}
                  </strong>
                </div>
              ))}
          </div>
          {typeof detail.metrics?.limitations === "string" && (
            <p className="card-foot">{detail.metrics.limitations}</p>
          )}
          <details>
            <summary>Recorded configuration</summary>
            <Facts value={detail.config} />
          </details>
          {detail.results?.length ? (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    {Object.keys(detail.results[0])
                      .slice(0, 7)
                      .map((k) => (
                        <th key={k}>{label(k)}</th>
                      ))}
                  </tr>
                </thead>
                <tbody>
                  {detail.results.map((row, i) => (
                    <tr key={i}>
                      {Object.keys(detail.results![0])
                        .slice(0, 7)
                        .map((k) => (
                          <td key={k}>
                            {typeof row[k] === "object" ? (
                              <code>{JSON.stringify(row[k])}</code>
                            ) : (
                              String(row[k] ?? "—")
                            )}
                          </td>
                        ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted">No per-case results returned.</p>
          )}
        </Card>
      )}
      <Card title="Reproducible benchmark reports">
        {shipped.data.items.length ? (
          shipped.data.items.map((r, i) => (
            <details key={i}>
              <summary>
                {String(
                  r.file ||
                    r.title ||
                    r.name ||
                    r.kind ||
                    r.id ||
                    `Report ${i + 1}`,
                )}
              </summary>
              <Facts
                value={Object.fromEntries(
                  Object.entries(r).filter(
                    ([k]) => !["results", "cases"].includes(k),
                  ),
                )}
              />
            </details>
          ))
        ) : (
          <Empty title="No shipped reports available">
            The backend publishes these only after the benchmark has actually
            run.
          </Empty>
        )}
      </Card>
    </div>
  );
}
function BenchmarkComparisons({ reports }: { reports: Json[] }) {
  const rag = reports.find((r) => r.file === "rag-comparison.json");
  const agent = reports.find((r) => r.file === "agent-ablation.json");
  return (
    <>
      {rag && (
        <Card
          title="Retrieval baseline comparison"
          action={<Badge>SYNTHETIC · 30 cases</Badge>}
        >
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Retrieval</th>
                  <th>Recall@1</th>
                  <th>Recall@3</th>
                  <th>Recall@5</th>
                  <th>MRR</th>
                  <th>nDCG</th>
                  <th>P95</th>
                </tr>
              </thead>
              <tbody>
                {((rag.results as Json[]) || []).map((r) => (
                  <tr key={String(r.mode)}>
                    <td>
                      <strong>{label(String(r.mode))}</strong>
                    </td>
                    {["recall_at_1", "recall_at_3", "recall_at_5"].map((k) => (
                      <td key={k}>{percent(r[k])}</td>
                    ))}
                    <td>{metric(r.mrr)}</td>
                    <td>{metric(r.ndcg)}</td>
                    <td>{metric(r.latency_p95_ms, " ms")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="card-foot">
            Measured retrieval over synthetic policy questions. These metrics do
            not measure generated answer quality. Human review:{" "}
            {String(rag.human_review_status || "Not reported")}.
          </p>
        </Card>
      )}
      {agent && (
        <Card
          title="Agent configuration ablation"
          action={<Badge tone="warn">FAKE PROVIDER HARNESS</Badge>}
        >
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Configuration</th>
                  <th>Cases</th>
                  <th>Task success</th>
                  <th>Evidence</th>
                  <th>Tool selection</th>
                  <th>Unsafe actions</th>
                  <th>P95</th>
                </tr>
              </thead>
              <tbody>
                {((agent.results as Json[]) || []).map((r) => (
                  <tr key={String(r.mode)}>
                    <td>
                      <strong>{label(String(r.mode))}</strong>
                    </td>
                    <td>{metric(r.cases)}</td>
                    <td>{percent(r.task_success_rate)}</td>
                    <td>{percent(r.correct_evidence_rate)}</td>
                    <td>{percent(r.correct_tool_selection)}</td>
                    <td>{metric(r.unsafe_actions)}</td>
                    <td>{metric(r.latency_p95_ms, " ms")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="card-foot">
            Deterministic routing and execution harness, not a real LLM quality
            comparison.{" "}
            {String(
              agent.real_llm_status || "Real provider results unavailable",
            )}
            . Evidence and tool metrics check golden-set inclusion, not
            precision.
          </p>
        </Card>
      )}
    </>
  );
}
export function RunsPage() {
  const [rev, bump] = useState(0);
  const resource = useResource<List<Run>>("/runs", { items: [] }, rev);
  const models = useResource<List<Json>>("/models", { items: [] }, rev);
  return (
    <div className="page">
      <PageTitle
        eyebrow="LLMOPS / EXECUTION HISTORY"
        title="Runs & models"
        action={<Refresh onClick={() => bump((v) => v + 1)} />}
      >
        Provider configuration and immutable run settings, visible in one place.
      </PageTitle>
      <Card title="Model registry">
        {models.error ? (
          <ErrorBox error={models.error} />
        ) : (
          <div className="model-grid">
            {models.data.items.map((m) => (
              <article key={`${String(m.provider)}:${String(m.id)}`}>
                <div className="row spread">
                  <strong>{String(m.id)}</strong>
                  <Badge tone={m.configured ? "good" : "warn"}>
                    {m.configured ? "Configured" : "Not configured"}
                  </Badge>
                </div>
                <p>{String(m.description || "")}</p>
                <small>{String(m.provider)}</small>
              </article>
            ))}
          </div>
        )}
      </Card>
      <ErrorBox error={resource.error} />
      <Card title="Recorded runs">
        {resource.loading && !resource.data.items.length ? (
          <Loading />
        ) : (
          <RunsTable runs={resource.data.items} />
        )}
      </Card>
      <div className="info-box">
        <CheckCheck size={18} />
        Every run captures provider, prompt version, retrieval, transport,
        memory and workflow settings. Fake-provider records are explicitly
        labeled.
      </div>
    </div>
  );
}
