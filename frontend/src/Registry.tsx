import { useEffect, useState } from "react";
import { GitCompareArrows, GitBranch, Plus, ShieldCheck } from "lucide-react";
import {
  api,
  date,
  type Evaluation,
  type Identity,
  type List,
  type Registry,
} from "./api";
import {
  ActionButton,
  Badge,
  Card,
  Empty,
  ErrorBox,
  Facts,
  Modal,
  PageTitle,
  useResource,
} from "./ui";
export default function RegistryPage({ me }: { me: Identity }) {
  const [kind, setKind] = useState("prompts");
  const [rev, bump] = useState(0);
  const registry = useResource<List<Registry>>(`/${kind}`, { items: [] }, rev);
  const evals = useResource<List<Evaluation>>(
    "/evaluations",
    { items: [] },
    rev,
  );
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Registry | null>(null);
  const [error, setError] = useState("");
  const [version, setVersion] = useState(1);
  const [from, setFrom] = useState(1);
  const [diff, setDiff] = useState("");
  const [evaluation, setEvaluation] = useState("");
  const [content, setContent] = useState("");
  const [open, setOpen] = useState(false);
  const chosen =
    registry.data.items.find((p) => p.id === selected) ||
    registry.data.items[0];
  useEffect(() => {
    if (!chosen) return;
    let live = true;
    api<Registry>(`/${kind}/${chosen.id}`)
      .then((d) => {
        if (live) {
          setDetail(d);
          setVersion(d.active_version);
          setDiff("");
        }
      })
      .catch((e) => {
        if (live) setError(e.message);
      });
    return () => {
      live = false;
    };
  }, [chosen, kind, rev]);
  const selectedVersion = detail?.versions?.find((v) => v.version === version);
  const admin = me.role === "admin";
  return (
    <div className="page">
      <PageTitle
        eyebrow="LLMOPS / VERSION CONTROL"
        title="Prompt & workflow registry"
        action={<Badge>Explicit release gates</Badge>}
      >
        Inspect versions, compare definitions and release prompts against
        evaluation evidence.
      </PageTitle>
      <nav className="section-tabs">
        <button
          className={kind === "prompts" ? "active" : ""}
          onClick={() => {
            setKind("prompts");
            setSelected("");
            setDetail(null);
          }}
        >
          <GitCompareArrows size={15} />
          Prompt versions
        </button>
        <button
          className={kind === "workflows" ? "active" : ""}
          onClick={() => {
            setKind("workflows");
            setSelected("");
            setDetail(null);
          }}
        >
          <GitBranch size={15} />
          Workflow definitions
        </button>
      </nav>
      <ErrorBox error={registry.error || error} />
      {chosen && detail ? (
        <>
          <div className="registry-toolbar">
            <label className="field grow">
              Registry item
              <select
                value={chosen.id}
                onChange={(e) => setSelected(e.target.value)}
              >
                {registry.data.items.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name || p.id}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Inspect version
              <select
                value={version}
                onChange={(e) => setVersion(Number(e.target.value))}
              >
                {detail.versions.map((v) => (
                  <option key={v.version} value={v.version}>
                    v{v.version}
                    {v.version === detail.active_version ? " · active" : ""}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="secondary"
              disabled={!admin}
              onClick={() => {
                setContent(
                  selectedVersion?.content ||
                    JSON.stringify(selectedVersion?.definition || {}, null, 2),
                );
                setOpen(true);
              }}
            >
              <Plus size={15} />
              New version
            </button>
          </div>
          <div className="two-columns">
            <Card
              title={detail.name || detail.id}
              action={<Badge>Active v{detail.active_version}</Badge>}
            >
              {kind === "prompts" ? (
                <pre className="prompt-content">{selectedVersion?.content}</pre>
              ) : (
                <>
                  <div className="workflow-nodes">
                    {(
                      (selectedVersion?.definition?.nodes || []) as {
                        id: string;
                        type: string;
                        config: unknown;
                      }[]
                    ).map((n, i) => (
                      <article key={n.id}>
                        <span className="cite-index">{i + 1}</span>
                        <div>
                          <strong>{n.type}</strong>
                          <small>{n.id}</small>
                        </div>
                        <details>
                          <summary>Config</summary>
                          <Facts value={n.config} />
                        </details>
                      </article>
                    ))}
                  </div>
                  <p className="card-foot">
                    Ordered validated workflow. High-risk actions remain behind
                    server-side approval.
                  </p>
                </>
              )}
              <small className="muted">
                Created {date(selectedVersion?.created_at)}
              </small>
            </Card>
            <div>
              <Card title="Compare versions">
                <div className="row">
                  <label className="field">
                    From
                    <select
                      value={from}
                      onChange={(e) => setFrom(Number(e.target.value))}
                    >
                      {detail.versions.map((v) => (
                        <option key={v.version}>{v.version}</option>
                      ))}
                    </select>
                  </label>
                  <span>→</span>
                  <Badge>v{version}</Badge>
                  <ActionButton
                    className="secondary"
                    onClick={async () => {
                      const d = await api<{ diff: string }>(
                        `/${kind}/${detail.id}/diff?from_version=${from}&to_version=${version}`,
                      );
                      setDiff(d.diff);
                    }}
                  >
                    Compare
                  </ActionButton>
                </div>
                {diff ? (
                  <pre className="diff-content">
                    {diff.split("\n").map((line, i) => (
                      <span
                        key={i}
                        className={
                          line.startsWith("+")
                            ? "add"
                            : line.startsWith("-")
                              ? "remove"
                              : ""
                        }
                      >
                        {line}
                        {"\n"}
                      </span>
                    ))}
                  </pre>
                ) : (
                  <p className="muted">
                    Choose two versions to inspect their actual diff.
                  </p>
                )}
              </Card>
              {kind === "prompts" && (
                <Card
                  title="Evaluation release gate"
                  action={<ShieldCheck size={18} />}
                >
                  <p>
                    A version is activated only when its linked offline
                    evaluation passes the server's regression policy.
                  </p>
                  <label className="field">
                    Evaluation report
                    <select
                      value={evaluation}
                      onChange={(e) => setEvaluation(e.target.value)}
                    >
                      <option value="">Select measured report</option>
                      {evals.data.items.map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.kind} · {r.status} · {r.id.slice(0, 12)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <ActionButton
                    disabled={!admin || !evaluation}
                    onClick={async () => {
                      await api(`/prompts/${detail.id}/release`, "POST", {
                        version,
                        evaluation_id: evaluation,
                      });
                      bump((v) => v + 1);
                    }}
                  >
                    Evaluate gate & release v{version}
                  </ActionButton>
                  <p className="card-foot">
                    A rejected gate remains rejected; the UI cannot override it.
                  </p>
                </Card>
              )}
            </div>
          </div>
        </>
      ) : (
        <Empty
          title={
            registry.loading
              ? "Loading registry…"
              : "No registry entries returned"
          }
        />
      )}
      {open && detail && (
        <Modal
          title={`Create ${kind === "prompts" ? "prompt" : "workflow"} version`}
          onClose={() => setOpen(false)}
        >
          <div className="modal-form">
            <label className="field">
              {kind === "prompts"
                ? "Prompt content"
                : "Workflow definition JSON"}
              <textarea
                rows={15}
                value={content}
                onChange={(e) => setContent(e.target.value)}
              />
            </label>
            <ActionButton
              disabled={!content.trim()}
              onClick={async () => {
                await api(
                  `/${kind}/${detail.id}/versions`,
                  "POST",
                  kind === "prompts"
                    ? { content }
                    : { definition: JSON.parse(content) },
                );
                setOpen(false);
                bump((v) => v + 1);
              }}
            >
              Save immutable version
            </ActionButton>
          </div>
        </Modal>
      )}
    </div>
  );
}
