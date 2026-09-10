import { useEffect, useState } from "react";
import { BookOpen, FilePlus2, Search } from "lucide-react";
import {
  api,
  label,
  metric,
  type Evidence,
  type Identity,
  type Json,
  type Knowledge,
  type List,
} from "./api";
import {
  ActionButton,
  Badge,
  Card,
  Empty,
  ErrorBox,
  EvidenceList,
  Facts,
  Loading,
  Modal,
  PageTitle,
  Status,
  useResource,
} from "./ui";
export default function KnowledgePage({ me }: { me: Identity }) {
  const [rev, bump] = useState(0);
  const docs = useResource<List<Knowledge>>("/knowledge", { items: [] }, rev);
  const [selected, setSelected] = useState("");
  const [tab, setTab] = useState("library");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("hybrid_rerank");
  const [topK, setTopK] = useState(5);
  const [category, setCategory] = useState("");
  const [result, setResult] = useState<{
    results: Evidence[];
    candidates: Evidence[];
    duration_ms: number;
    embedding_model: string;
    reranker: string;
    filters: Json;
  } | null>(null);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [docCategory, setDocCategory] = useState("refund");
  const [format, setFormat] = useState("md");
  const [version, setVersion] = useState(1);
  const [content, setContent] = useState("");
  const [effective, setEffective] = useState(
    new Date().toISOString().slice(0, 10),
  );
  const listed =
    docs.data.items.find((d) => d.id === selected) || docs.data.items[0];
  const [document, setDocument] = useState<Knowledge | null>(null);
  const [detailError, setDetailError] = useState("");
  useEffect(() => {
    if (!listed) return;
    let active = true;
    setDetailError("");
    api<Knowledge>(`/knowledge/${listed.id}`)
      .then((value) => {
        if (active) setDocument(value);
      })
      .catch((e) => {
        if (active) setDetailError(e.message);
      });
    return () => {
      active = false;
    };
  }, [listed, rev]);
  const chosen = document?.id === listed?.id ? document : listed;
  const canManage = me.role === "admin";
  return (
    <div className="page">
      <PageTitle
        eyebrow="KNOWLEDGE & RETRIEVAL"
        title="Policy intelligence"
        action={
          <button
            className="primary"
            disabled={!canManage}
            onClick={() => setOpen(true)}
          >
            <FilePlus2 size={15} />
            Ingest document
          </button>
        }
      >
        Versioned policy sources, traceable chunks and inspectable retrieval.
      </PageTitle>
      <nav className="section-tabs">
        <button
          className={tab === "library" ? "active" : ""}
          onClick={() => setTab("library")}
        >
          <BookOpen size={15} />
          Knowledge library
        </button>
        <button
          className={tab === "search" ? "active" : ""}
          onClick={() => setTab("search")}
        >
          <Search size={15} />
          Retrieval inspector
        </button>
      </nav>
      <ErrorBox error={docs.error || detailError} />
      {tab === "library" ? (
        <>
          {docs.loading && !docs.data.items.length ? (
            <Loading />
          ) : !chosen ? (
            <Empty title="No knowledge documents">
              An administrator can ingest Markdown, text, HTML or JSON.
            </Empty>
          ) : (
            <div className="knowledge-grid">
              <div className="document-list">
                {docs.data.items.map((d) => (
                  <button
                    key={d.id}
                    className={`document-item ${chosen.id === d.id ? "selected" : ""}`}
                    onClick={() => setSelected(d.id)}
                  >
                    <div className="row spread">
                      <Badge>{label(d.category)}</Badge>
                      <Status value={d.active ? "active" : "superseded"} />
                    </div>
                    <strong>{d.title}</strong>
                    <small>
                      Version {d.version} · {d.format.toUpperCase()} ·{" "}
                      {d.effective_date}
                    </small>
                  </button>
                ))}
              </div>
              <Card
                title={chosen.title}
                action={<Badge>Version {chosen.version}</Badge>}
              >
                <div className="row spread">
                  <span className="muted small">
                    Effective {chosen.effective_date} ·{" "}
                    {chosen.expires_at
                      ? `Expires ${chosen.expires_at}`
                      : "No expiry set"}
                  </span>
                  {!chosen.active && (
                    <ActionButton
                      className="secondary"
                      disabled={!canManage}
                      onClick={async () => {
                        await api(
                          `/knowledge/${chosen.id}/activate`,
                          "POST",
                          {},
                        );
                        bump((v) => v + 1);
                      }}
                    >
                      Activate this version
                    </ActionButton>
                  )}
                </div>
                <pre className="document-content">{chosen.content}</pre>
                <h3>Indexed chunks</h3>
                {chosen.chunks?.length ? (
                  chosen.chunks.map((c, i) => (
                    <article className="chunk" key={c.id}>
                      <div className="row">
                        <span className="cite-index">{i + 1}</span>
                        <strong>{c.section}</strong>
                        <code>{c.id.slice(0, 12)}</code>
                      </div>
                      <p>{c.text}</p>
                      <small>Version {c.version}</small>
                    </article>
                  ))
                ) : (
                  <p className="muted">
                    Chunk details are not included in this list response.
                  </p>
                )}
                <details>
                  <summary>Document metadata</summary>
                  <Facts value={chosen.metadata} />
                </details>
              </Card>
            </div>
          )}
        </>
      ) : (
        <>
          <Card title="Inspect a retrieval request">
            <div className="retrieval-form">
              <label className="field grow">
                Query
                <input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="When can a damaged item be replaced?"
                />
              </label>
              <label className="field">
                Mode
                <select value={mode} onChange={(e) => setMode(e.target.value)}>
                  {["keyword", "dense", "hybrid", "hybrid_rerank"].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                Top K
                <select
                  value={topK}
                  onChange={(e) => setTopK(Number(e.target.value))}
                >
                  {[3, 5, 10].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                Category
                <input
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="All categories"
                />
              </label>
            </div>
            <ActionButton
              disabled={query.trim().length < 3}
              onClick={async () =>
                setResult(
                  await api("/retrieval/search", "POST", {
                    query,
                    mode,
                    top_k: topK,
                    ...(category ? { filters: { category } } : {}),
                  }),
                )
              }
            >
              <Search size={15} />
              Search actual index
            </ActionButton>
          </Card>
          {result && (
            <>
              <div className="source-note">
                <Badge>{result.results.length} selected</Badge>
                <span>{metric(result.duration_ms, " ms")}</span>
                <span>Embedding: {result.embedding_model}</span>
                <span>Reranker: {result.reranker}</span>
              </div>
              <div className="two-columns">
                <Card title="Final context">
                  <EvidenceList items={result.results} />
                </Card>
                <Card title="Candidate scores">
                  {result.candidates.length ? (
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            <th>Chunk</th>
                            <th>Lexical</th>
                            <th>Vector</th>
                            <th>Combined</th>
                            <th>Rerank</th>
                          </tr>
                        </thead>
                        <tbody>
                          {result.candidates.map((c, i) => (
                            <tr key={c.chunk_id || i}>
                              <td>
                                {c.title}
                                <small className="block">{c.section}</small>
                              </td>
                              <td>{metric(c.lexical_score)}</td>
                              <td>{metric(c.vector_score)}</td>
                              <td>{metric(c.score)}</td>
                              <td>{metric(c.rerank_score)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <Empty title="No candidates match" />
                  )}
                  <details>
                    <summary>Applied metadata filters</summary>
                    <Facts value={result.filters} />
                  </details>
                </Card>
              </div>
            </>
          )}
        </>
      )}
      {open && (
        <Modal
          title="Ingest a versioned document"
          onClose={() => setOpen(false)}
        >
          <div className="modal-form">
            <div className="form-grid">
              <label className="field">
                Title
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                />
              </label>
              <label className="field">
                Category
                <input
                  value={docCategory}
                  onChange={(e) => setDocCategory(e.target.value)}
                />
              </label>
              <label className="field">
                Version
                <input
                  type="number"
                  min={1}
                  value={version}
                  onChange={(e) => setVersion(Number(e.target.value))}
                />
              </label>
              <label className="field">
                Format
                <select
                  value={format}
                  onChange={(e) => setFormat(e.target.value)}
                >
                  {["md", "txt", "html", "json"].map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                Effective date
                <input
                  type="date"
                  value={effective}
                  onChange={(e) => setEffective(e.target.value)}
                />
              </label>
            </div>
            <label className="field">
              Source content
              <textarea
                rows={9}
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="Paste the source policy, with its headings and factual rules."
              />
            </label>
            <div className="info-box">
              Ingestion parses, cleans, chunks and indexes the document.
              Activating a new version supersedes older versions of the same
              title.
            </div>
            <ActionButton
              disabled={!title.trim() || !content.trim()}
              onClick={async () => {
                const d = await api<Knowledge>("/knowledge", "POST", {
                  title,
                  category: docCategory,
                  version,
                  format,
                  content,
                  effective_date: effective,
                  expires_at: null,
                  active: true,
                  metadata: { source: "operator-ingestion" },
                });
                setSelected(d.id);
                setOpen(false);
                bump((v) => v + 1);
                setContent("");
              }}
            >
              Ingest and index
            </ActionButton>
          </div>
        </Modal>
      )}
    </div>
  );
}
