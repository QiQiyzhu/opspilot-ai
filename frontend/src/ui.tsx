import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  AlertCircle,
  Check,
  Database,
  LoaderCircle,
  RefreshCw,
  X,
} from "lucide-react";
import { api, label, type Evidence } from "./api";
export function useResource<T>(path: string, initial: T, revision = 0) {
  const [data, setData] = useState<T>(initial);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError("");
    api<T>(path)
      .then((value) => {
        if (alive) setData(value);
      })
      .catch((e) => {
        if (alive) setError(String(e.message));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [path, revision]);
  return { data, error, loading, setData };
}
export function Badge({
  children,
  tone = "",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function Status({ value }: { value: string }) {
  const tone = /failed|rejected|cancelled/.test(value)
    ? "danger"
    : /completed|executed|active|passed/.test(value)
      ? "good"
      : /pending|waiting|running/.test(value)
        ? "warn"
        : "";
  return <Badge tone={tone}>{label(value)}</Badge>;
}
export function ErrorBox({ error }: { error?: string }) {
  return error ? (
    <div className="error-box" role="alert">
      <AlertCircle size={16} />
      <span>{error}</span>
    </div>
  ) : null;
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <Database size={25} />
      <strong>{title}</strong>
      <p>
        {children ||
          "Records appear here after the corresponding workflow runs."}
      </p>
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle size={17} className="spin" /> Loading workspace data…
    </div>
  );
}
export function PageTitle({
  eyebrow,
  title,
  children,
  action,
}: {
  eyebrow: string;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className="page-title">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{children}</p>
      </div>
      {action}
    </header>
  );
}
export function Card({
  title,
  children,
  action,
  className = "",
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      <header className="card-head">
        <h2>{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}
export function Facts({ value }: { value: unknown }) {
  if (!value || typeof value !== "object")
    return (
      <span className="value">
        {value === undefined || value === null ? "—" : String(value)}
      </span>
    );
  return (
    <dl className="facts">
      {Object.entries(value).map(([key, val]) => (
        <div key={key}>
          <dt>{label(key)}</dt>
          <dd>
            {typeof val === "object" && val !== null ? (
              <code>{JSON.stringify(val)}</code>
            ) : (
              String(val ?? "—")
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
export function EvidenceList({ items }: { items: Evidence[] }) {
  return items?.length ? (
    <div className="evidence-list">
      {items.map((e, i) => (
        <article className="evidence" key={e.chunk_id || e.id || i}>
          <div className="row">
            <span className="cite-index">{i + 1}</span>
            <strong>{e.title || e.document_id || "Policy evidence"}</strong>
            <Badge>v{e.version ?? "?"}</Badge>
          </div>
          <p className="evidence-section">{e.section || e.chunk_id}</p>
          <p>
            {e.text ||
              (e.rules
                ? "Policy rules captured with this proposal:"
                : "Open the trace for the full evidence payload.")}
          </p>
          {e.rules != null && <Facts value={e.rules} />}
          {typeof e.score === "number" && (
            <small>Retrieval score {e.score.toFixed(4)}</small>
          )}
        </article>
      ))}
    </div>
  ) : (
    <Empty title="No evidence attached">
      Only retrieved policy evidence is shown here.
    </Empty>
  );
}
export function ActionButton({
  children,
  onClick,
  disabled = false,
  className = "primary",
}: {
  children: ReactNode;
  onClick: () => Promise<unknown>;
  disabled?: boolean;
  className?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <div>
      <button
        disabled={busy || disabled}
        className={className}
        onClick={() => {
          setBusy(true);
          setError("");
          onClick()
            .catch((e) => setError(e.message))
            .finally(() => setBusy(false));
        }}
      >
        {busy ? <LoaderCircle size={14} className="spin" /> : null}
        {children}
      </button>
      <ErrorBox error={error} />
    </div>
  );
}
export function Refresh({ onClick }: { onClick: () => void }) {
  return (
    <button className="secondary" onClick={onClick}>
      <RefreshCw size={14} />
      Refresh
    </button>
  );
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLElement>(null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") close.current();
      if (e.key === "Tab") {
        const items = Array.from(
          dialog.current?.querySelectorAll<HTMLElement>(
            'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
          ) || [],
        );
        const first = items[0];
        const last = items.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    if (!dialog.current?.contains(document.activeElement))
      dialog.current
        ?.querySelector<HTMLElement>("input, select, textarea, button")
        ?.focus();
    return () => {
      document.removeEventListener("keydown", handler);
      previous?.focus();
    };
  }, []);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section
        ref={dialog}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="card-head">
          <h2>{title}</h2>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={19} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="notice">
      <Check size={16} />
      <span>{children}</span>
    </div>
  );
}
