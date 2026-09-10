import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowRight,
  BookOpen,
  Boxes,
  Brain,
  Cable,
  ChevronDown,
  FlaskConical,
  GitBranch,
  Inbox as InboxIcon,
  LayoutDashboard,
  LogOut,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { api, setToken, token, type Identity } from "./api";
import { Badge, ErrorBox, Modal } from "./ui";
import Inbox from "./Inbox";
import {
  ApprovalsPage,
  DashboardPage,
  EvaluationPage,
  RunsPage,
} from "./Operations";
import KnowledgePage from "./Knowledge";
import RegistryPage from "./Registry";
import MemoryPage from "./Memory";
import BusinessPage from "./Business";
const pages = [
  {
    key: "inbox",
    label: "Support inbox",
    icon: InboxIcon,
    section: "WORKSPACE",
  },
  { key: "approvals", label: "Approvals", icon: ShieldCheck },
  { key: "business", label: "Business records", icon: Boxes },
  {
    key: "dashboard",
    label: "Overview",
    icon: LayoutDashboard,
    section: "OBSERVE & IMPROVE",
  },
  { key: "evaluation", label: "Evaluation lab", icon: FlaskConical },
  { key: "runs", label: "Runs & models", icon: Activity },
  {
    key: "knowledge",
    label: "Knowledge",
    icon: BookOpen,
    section: "CONFIGURATION",
  },
  { key: "registry", label: "Prompts & workflows", icon: GitBranch },
  { key: "memory", label: "Verified memory", icon: Brain },
];
export default function App() {
  const [me, setMe] = useState<Identity | null>(null);
  const [credential, setCredential] = useState(token());
  const [error, setError] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [page, setPage] = useState("inbox");
  const [revision, bump] = useState(0);
  const [settings, setSettings] = useState(false);
  const connect = async () => {
    setConnecting(true);
    setError("");
    setToken(credential.trim());
    try {
      setMe(await api<Identity>("/me"));
      setSettings(false);
    } catch (e) {
      setMe(null);
      setError((e as Error).message);
    } finally {
      setConnecting(false);
    }
  };
  useEffect(() => {
    if (!token()) return;
    let active = true;
    api<Identity>("/me")
      .then((value) => {
        if (active) setMe(value);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, []);
  const activity = useCallback(() => bump((v) => v + 1), []);
  const connectionForm = (
    <form
      className="connection-form"
      onSubmit={(e) => {
        e.preventDefault();
        void connect();
      }}
    >
      <label className="field">
        Workspace access token
        <input
          type="password"
          value={credential}
          onChange={(e) => setCredential(e.target.value)}
          placeholder="Enter the token configured on your server"
          autoComplete="off"
          autoFocus
          required
        />
      </label>
      <p className="muted small">
        Stored in this browser session only. Your identity and role come from
        the server. Local demo tokens are development credentials.
      </p>
      <ErrorBox error={error} />
      <button
        className="primary full"
        disabled={connecting || !credential.trim()}
      >
        {connecting ? "Connecting…" : "Connect workspace"}
        <ArrowRight size={16} />
      </button>
    </form>
  );
  if (!me)
    return (
      <main className="connection-screen">
        <div className="connection-brand">
          <div className="brand-symbol">
            <ShieldCheck size={27} />
          </div>
          <span>
            OpsPilot<span className="brand-ai">AI</span>
          </span>
        </div>
        <div className="connection-layout">
          <section>
            <span className="eyebrow">NOVAMART OPERATIONS CONSOLE</span>
            <h1>
              Business decisions.
              <br />
              <em>Backed by evidence.</em>
            </h1>
            <p>
              A customer support workspace where policy retrieval, agent
              execution and human approval meet.
            </p>
            <div className="connection-features">
              <span>
                <BookOpen size={18} />
                Current policy evidence
              </span>
              <span>
                <ShieldCheck size={18} />
                Auditable business actions
              </span>
              <span>
                <Activity size={18} />
                Measured system behavior
              </span>
            </div>
            <Badge>SIMULATED BUSINESS</Badge>
            <small className="block muted">
              Portfolio environment · no real customers or payments
            </small>
          </section>
          <section className="connection-card">
            <div className="connection-icon">
              <Cable size={23} />
            </div>
            <h2>Connect your workspace</h2>
            <p>Access your locally configured NovaMart environment.</p>
            {connectionForm}
            <div className="connection-foot">
              <span className="live-dot" />
              Backend endpoint <code>/api</code>
            </div>
          </section>
        </div>
        <footer>
          OpsPilot AI · Production-oriented customer support & business
          operations platform
        </footer>
      </main>
    );
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("inbox");
          }}
        >
          <div className="brand-symbol">
            <ShieldCheck size={22} />
          </div>
          <span>
            OpsPilot<span className="brand-ai">AI</span>
          </span>
        </a>
        <div className="workspace-switch">
          <div className="workspace-logo">N</div>
          <div>
            <strong>NovaMart</strong>
            <small>Operations workspace</small>
          </div>
          <ChevronDown size={14} />
        </div>
        <nav aria-label="Main navigation">
          {pages.map((p) => (
            <div key={p.key}>
              {p.section && <span className="nav-section">{p.section}</span>}
              <button
                aria-label={p.label}
                aria-current={page === p.key ? "page" : undefined}
                title={p.label}
                className={page === p.key ? "active" : ""}
                onClick={() => setPage(p.key)}
              >
                <p.icon size={17} />
                <span>{p.label}</span>
                {page === p.key && <span className="nav-active-dot" />}
              </button>
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="simulation-label">
            <span className="live-dot" />
            SIMULATED BUSINESS
          </div>
          <p>
            Local decisions. Real audit trail.
            <br />
            No real payment processing.
          </p>
          <button
            className="sidebar-settings"
            onClick={() => setSettings(true)}
          >
            <Settings2 size={16} />
            Connection settings
          </button>
          <div className="identity">
            <span className="identity-avatar">{me.name?.[0] || "O"}</span>
            <div>
              <strong>{me.name}</strong>
              <small>{me.role}</small>
            </div>
            <button
              aria-label="Disconnect workspace"
              title="Disconnect workspace"
              onClick={() => {
                setToken("");
                setCredential("");
                setMe(null);
              }}
            >
              <LogOut size={15} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div>
            <span>Workspace</span>
            <span className="slash">/</span>
            <strong>{pages.find((p) => p.key === page)?.label}</strong>
          </div>
          <div className="row">
            <span className="provider-label">
              <span className="live-dot" />
              {me.provider === "fake"
                ? "Fake provider · deterministic"
                : me.provider}
            </span>
            <Badge tone="soft">Local environment</Badge>
          </div>
        </header>
        <main key={me.id}>
          {page === "inbox" ? (
            <Inbox me={me} revision={revision} onActivity={activity} />
          ) : page === "approvals" ? (
            <ApprovalsPage me={me} revision={revision} onActivity={activity} />
          ) : page === "dashboard" ? (
            <DashboardPage revision={revision} />
          ) : page === "evaluation" ? (
            <EvaluationPage me={me} />
          ) : page === "knowledge" ? (
            <KnowledgePage me={me} />
          ) : page === "registry" ? (
            <RegistryPage me={me} />
          ) : page === "memory" ? (
            <MemoryPage me={me} />
          ) : page === "business" ? (
            <BusinessPage me={me} />
          ) : (
            <RunsPage />
          )}
        </main>
      </div>
      {settings && (
        <Modal title="Workspace connection" onClose={() => setSettings(false)}>
          <div className="modal-form">
            <p>
              Connected as <strong>{me.name}</strong> ({me.role}). Changing
              token changes the server-derived identity.
            </p>
            {connectionForm}
          </div>
        </Modal>
      )}
    </div>
  );
}
