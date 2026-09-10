import { useState } from "react";
import { CheckCheck, ShieldCheck, X } from "lucide-react";
import { api, date, type Proposal } from "./api";
import { Badge, ErrorBox, EvidenceList, Facts, Status } from "./ui";
export default function Approval({
  proposal,
  role,
  onChange,
}: {
  proposal: Proposal;
  role: string;
  onChange: () => Promise<void> | void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const authorized = ["approver", "admin"].includes(role);
  const decide = async (decision: "approve" | "reject") => {
    setBusy(true);
    setError("");
    try {
      await api(`/approvals/${proposal.id}/decision`, "POST", {
        decision,
        reason: reason.trim(),
        idempotency_key: `${proposal.id}:${decision}`,
      });
      await onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <article className="approval-panel">
      <div className="row spread">
        <span className="approval-heading">
          <ShieldCheck size={19} />
          {proposal.status === "pending"
            ? "Human decision required"
            : "Business decision audit"}
        </span>
        <Status value={proposal.status} />
      </div>
      <h3>
        {proposal.action[0]?.toUpperCase() + proposal.action.slice(1)} ·{" "}
        {proposal.order_id}
      </h3>
      <p>{proposal.reason}</p>
      <div className="approval-summary">
        <Facts
          value={{
            affected_order: proposal.order_id,
            action: proposal.action,
            proposal: proposal.id,
            requested_by: proposal.requested_by,
          }}
        />
      </div>
      <h4>Action parameters</h4>
      <Facts value={proposal.parameters} />
      <h4>Policy evidence</h4>
      <EvidenceList items={proposal.evidence || []} />
      {proposal.status === "pending" ? (
        <>
          <label className="field">
            Decision reason
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Record why this action is approved or rejected…"
              rows={2}
              maxLength={1000}
            />
          </label>
          <p className="muted small">
            The server rechecks policy, locks the order and records your
            authenticated identity before executing.
          </p>
          {!authorized && (
            <Badge tone="warn">Approver or admin role required</Badge>
          )}
          <div className="row">
            <button
              className="primary"
              disabled={busy || !authorized || reason.trim().length < 3}
              onClick={() => void decide("approve")}
            >
              <CheckCheck size={15} />
              Approve & verify
            </button>
            <button
              className="secondary danger-text"
              disabled={busy || !authorized || reason.trim().length < 3}
              onClick={() => void decide("reject")}
            >
              <X size={15} />
              Reject
            </button>
          </div>
        </>
      ) : (
        <>
          <div className="audit-line">
            <ShieldCheck size={15} />
            {proposal.approved_by
              ? `${proposal.approved_by} · ${date(proposal.approved_at)}`
              : "Decision recorded by server"}
          </div>
          <h4>Before state</h4>
          <Facts value={proposal.before_state} />
          <h4>After state</h4>
          <Facts value={proposal.after_state} />
          <h4>Independent verification</h4>
          <Facts value={proposal.verification} />
        </>
      )}
      <ErrorBox error={error} />
    </article>
  );
}
