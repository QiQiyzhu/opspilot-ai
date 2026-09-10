import numpy as np
from sqlalchemy import select, text
from backend.db import session_scope
from backend.models import AgentRun, ToolCall, EvaluationRun, Alert, as_dict


def dashboard():
    with session_scope() as s:
        runs = s.scalars(select(AgentRun).order_by(AgentRun.created_at.desc()).limit(10000)).all()
        calls = s.scalars(select(ToolCall).limit(10000)).all()
        reports = s.scalars(
            select(EvaluationRun).where(EvaluationRun.status == "completed").order_by(EvaluationRun.created_at.desc())
        ).all()
        latencies = [r.duration_ms for r in runs if r.duration_ms is not None]
        agent_report = next((r for r in reports if r.kind == "agent"), None)
        rag_report = next((r for r in reports if r.kind == "rag"), None)
        categories = (
            s.execute(text("SELECT category, count(*) AS count FROM agent_runs GROUP BY category ORDER BY count DESC"))
            .mappings()
            .all()
        )
        daily = (
            s.execute(
                text("SELECT created_at::date AS day, count(*) AS count FROM agent_runs GROUP BY day ORDER BY day")
            )
            .mappings()
            .all()
        )
        return {
            "business": "SIMULATED BUSINESS",
            "provider": "mixed recorded providers; default fake",
            "run_count": len(runs),
            "completed": sum(r.status == "completed" for r in runs),
            "failed": sum(r.status == "failed" for r in runs),
            "waiting_approval": sum(r.status == "waiting_approval" for r in runs),
            "p50_ms": float(np.percentile(latencies, 50)) if latencies else None,
            "p95_ms": float(np.percentile(latencies, 95)) if latencies else None,
            "tool_error_rate": sum(c.status == "error" for c in calls) / len(calls) if calls else None,
            "escalation_rate": sum(r.category in {"out_of_scope", "ambiguous"} or r.status == "failed" for r in runs)
            / len(runs)
            if runs
            else None,
            "unsafe_action_count": agent_report.metrics.get("unsafe_actions", 0) if agent_report else None,
            "token_usage": sum((r.tokens.get("input") or 0) + (r.tokens.get("output") or 0) for r in runs if r.tokens)
            if any(r.tokens for r in runs)
            else None,
            "task_success_rate": agent_report.metrics.get("task_success_rate") if agent_report else None,
            "retrieval_recall": rag_report.metrics.get("recall_at_5") if rag_report else None,
            "category_counts": [dict(v) for v in categories],
            "daily_runs": [{**dict(v), "day": str(v["day"])} for v in daily],
            "recent_runs": [as_dict(r) for r in runs[:10]],
            "alerts": [as_dict(a) for a in s.scalars(select(Alert).order_by(Alert.created_at.desc()))],
            "limitations": [
                "Completion is not task success. Success and recall come only from synthetic labeled evaluation reports.",
                "Latency includes approval waiting time; performance reports separately measure active execution.",
                "Fake provider token usage and cost are unavailable, not zero tokens.",
                "Dashboard run/tool queries bounded at 10000 records for this single-instance demo.",
            ],
        }


def evaluate_alerts():
    data = dashboard()
    checks = [("tool_error_rate", 0.10, data["tool_error_rate"]), ("p95_ms", 10000, data["p95_ms"])]
    with session_scope() as s:
        latest = s.scalar(
            select(EvaluationRun).where(EvaluationRun.kind == "agent").order_by(EvaluationRun.created_at.desc())
        )
        checks.append(
            ("unsupported_claim_rate", 0.05, latest.metrics.get("unsupported_claim_rate") if latest else None)
        )
        for metric, threshold, value in checks:
            if value is not None and value > threshold:
                existing = s.scalar(select(Alert).where(Alert.metric == metric, Alert.status == "open"))
                if existing:
                    existing.current_value = value
                else:
                    s.add(Alert(metric=metric, threshold=threshold, current_value=value))
    return dashboard()["alerts"]
