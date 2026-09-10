"""Evidence export, not an Agent benchmark. Executes isolated simulated refund gates."""

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.business import BusinessVerifier, decide, propose
from backend.db import db_health, session_scope
from backend.models import AuditEntry, Order, Proposal, Refund, now
from backend.rag import search
from backend.security import Principal
from backend.seed import seed

ROOT = Path(__file__).resolve().parents[1]
OPERATOR = Principal("decision-script-operator", "Scripted demonstration operator", "operator")
REVIEWER = Principal("decision-script-reviewer", "Scripted demonstration reviewer", "approver")


def fresh_order(age=5):
    oid = "test_decision_" + uuid4().hex
    with session_scope() as session:
        session.add(
            Order(
                id=oid,
                customer_id="cus_ava",
                product_id="prod_speaker",
                quantity=1,
                amount_cents=12900,
                status="delivered",
                purchased_at=now() - timedelta(days=age + 3),
                delivered_at=now() - timedelta(days=age),
            )
        )
    return oid


def snapshot(oid, pid=None):
    with session_scope() as session:
        order = session.get(Order, oid)
        return {
            "order_id": oid,
            "order_status": order.status,
            "refund_count": session.scalar(select(func.count()).select_from(Refund).where(Refund.order_id == oid)),
            "proposal_status": session.get(Proposal, pid).status if pid else None,
            "audit_count": session.scalar(select(func.count()).select_from(AuditEntry).where(AuditEntry.target == pid))
            if pid
            else 0,
        }


def denied(call):
    try:
        call()
    except HTTPException as exc:
        return {"status_code": exc.status_code, "detail": exc.detail}
    raise AssertionError("Expected server denial, but the call succeeded")


def execute_boundary(include_retrieval=True):
    """Fresh IDs only; no reset or ordinary console order/stock mutations."""
    health = db_health()
    assert "PostgreSQL" in health["database"] and health["pgvector"]
    retrieval = (
        search("How many days after delivery can I request a refund?", "hybrid_rerank", 5)
        if include_retrieval
        else None
    )
    if retrieval is not None:
        assert any(
            r["document_id"] == "policy_refund_v2" and r["section"] == "Eligibility" for r in retrieval["results"]
        )

    old = fresh_order(age=31)
    expired = denied(lambda: propose(old, "refund", "31-day synthetic request", uuid4().hex, OPERATOR))
    expired_state = snapshot(old)
    assert expired["status_code"] == 409 and expired_state["refund_count"] == 0

    oid = fresh_order()
    proposal = propose(oid, "refund", "Synthetic decision walkthrough", uuid4().hex, OPERATOR)
    pending = snapshot(oid, proposal["id"])
    assert pending["order_status"] == "delivered" and pending["refund_count"] == 0
    unauthorized = denied(lambda: decide(proposal["id"], "approve", "Operator cannot approve", uuid4().hex, OPERATOR))
    denied_state = snapshot(oid, proposal["id"])
    assert unauthorized["status_code"] == 403 and denied_state["refund_count"] == 0
    key = uuid4().hex
    first = decide(proposal["id"], "approve", "Scripted QA review; not a human study", key, REVIEWER)
    replay = decide(proposal["id"], "approve", "Replay after simulated lost response", key, REVIEWER)
    verified = BusinessVerifier.verify(proposal["id"])
    after = snapshot(oid, proposal["id"])
    assert first["id"] == replay["id"] and verified["verified"]
    assert after["refund_count"] == 1 and after["audit_count"] == 1
    assert verified["record"]["amount_cents"] == proposal["parameters"]["amount_cents"] == 12900

    stale_oid = fresh_order()
    stale = propose(stale_oid, "refund", "Eligibility can age while awaiting review", uuid4().hex, OPERATOR)
    # A documented fixture mutation emulates crossing the policy window, without changing order.version.
    with session_scope() as session:
        session.get(Order, stale_oid).delivered_at = now() - timedelta(days=31)
    changed = denied(lambda: decide(stale["id"], "approve", "Review stale snapshot", uuid4().hex, REVIEWER))
    stale_state = snapshot(stale_oid, stale["id"])
    assert changed["status_code"] == 409 and "Eligibility changed" in str(changed["detail"])
    assert (
        stale_state["refund_count"] == 0
        and stale_state["audit_count"] == 0
        and stale_state["proposal_status"] == "pending"
    )
    return {
        "executed_at": now().isoformat(),
        "environment": {"python": platform.python_version(), "platform": platform.platform(), **health},
        "method": "Actual PostgreSQL service calls and independent reads; scripted principals; no language-model calls; no payment gateway",
        "retrieval": retrieval,
        "policy_evidence": proposal["evidence"],
        "approved_parameters": proposal["parameters"],
        "steps": [
            {
                "id": "expired-order",
                "title": "命中文档不替代订单资格",
                "observed": expired,
                "database_after": expired_state,
            },
            {"id": "pending", "title": "提案停在待审，尚未退款", "database_after": pending},
            {
                "id": "wrong-role",
                "title": "操作员批准被服务端拒绝",
                "observed": unauthorized,
                "database_after": denied_state,
            },
            {
                "id": "approved-replay",
                "title": "批准后重放：一条退款、一条审计",
                "database_after": after,
                "verification": verified,
            },
            {
                "id": "stale-eligibility",
                "title": "已生成提案，资格过期后仍不能批准",
                "fixture_change": "Only delivered_at set to now minus 31 days; order.version unchanged",
                "observed": changed,
                "database_after": stale_state,
            },
        ],
        "checks": {
            "expired_order_denied": True,
            "pending_has_no_refund": True,
            "operator_cannot_approve": True,
            "replay_refund_count": after["refund_count"],
            "approved_amount_matches": verified["checks"]["approved_amount_matches"],
            "stale_eligibility_rechecked": True,
        },
        "scope": "Sequential transaction walkthrough. Existing concurrency/barrier/mutation suites supply separate race evidence; this script does not retest concurrency.",
    }


def build_export(boundary):
    paths = [
        "evals/data/rag-v1.json",
        *[f"evals/reports/rag-{mode}.json" for mode in ("keyword", "dense", "hybrid", "hybrid_rerank")],
        "evals/reports/container-smoke.json",
        "backend/rag.py",
        "backend/business.py",
        "evals/decision_case.py",
    ]
    reports = {
        mode: json.loads((ROOT / f"evals/reports/rag-{mode}.json").read_text())
        for mode in ("keyword", "dense", "hybrid", "hybrid_rerank")
    }
    dataset = json.loads((ROOT / paths[0]).read_text())
    selected = {
        "rag_01": "命中退款资格，仍需执行资格和权限检查",
        "rag_02": "总体 MRR 提升仍可能损害单条口语问题",
        "rag_29": "税务 return 被错当作退货，拒答失败",
        "rag_30": "同一阈值也存在正确拒答：保留反例",
    }
    return {
        "schema_version": 1,
        "project": "opspilot",
        "title": "检索命中 ≠ 可以自动退款",
        "provenance": {
            "source_head_before_change": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "data": "SYNTHETIC BENCHMARK / SIMULATED BUSINESS",
            "embedding": "Actual BAAI/bge-small-en-v1.5 ONNX CPU, 384 dimensions",
            "reranker": "lexical-feature-v1; heuristic, not cross encoder",
            "agent_provider": "No Agent or LLM invoked by this case; existing Agent reports use FakeModelProvider",
            "human_review": "AI-reviewed gold; independent human review pending; approvals here are scripted QA",
        },
        "sources": [
            {
                "path": p,
                "sha256": hashlib.sha256((ROOT / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
                "sha256_scope": "UTF-8 source text, CRLF normalized to LF for GitHub/fresh-clone comparison",
                "working_tree_sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest(),
            }
            for p in paths
        ],
        "summary": {
            "dataset_cases": 30,
            "answerable_cases": 26,
            "no_answer_cases": 4,
            "variants": [
                {"variant": mode, "report_id": r["id"], "executed_at": r["created_at"], **r["metrics"]}
                for mode, r in reports.items()
            ],
        },
        "cases": [
            {
                "case_id": cid,
                "title": title,
                "input": next(d for d in dataset if d["id"] == cid),
                "variants": [
                    {"variant": mode, **next(r for r in report["results"] if r["case_id"] == cid)}
                    for mode, report in reports.items()
                ],
            }
            for cid, title in selected.items()
        ],
        "all_cases": [{"variant": mode, **row} for mode, report in reports.items() for row in report["results"]],
        "boundary_execution": boundary,
        "decision": {
            "chosen": "Use retrieval for reviewable evidence; retain independent current-policy/role/transaction/verifier gates.",
            "rejected": [
                "Auto-refund whenever a retrieved policy appears",
                "Choose retrieval solely by aggregate MRR",
                "Call lexical rerank a learned cross encoder",
            ],
            "limits": [
                "Historical RAG ranks are fixed development observations, not fresh generalization evidence",
                "No generated answer quality or real payment outcome measured",
                "Gate correctness does not repair irrelevant prose",
            ],
        },
        "next_experiment": {
            "status": "PLANNED / NOT EXECUTED",
            "proposal": "Freeze 40 new questions (20 answerable, 20 no-answer/near-domain) before calibration; split by intent into 20 calibration and 20 held-out cases; independently review labels; measure abstention and coverage separately.",
            "stop_rule": "Any unsafe executed action blocks a release regardless of retrieval score; no automatic refund mode is proposed.",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="evals/reports/decision-case.json")
    args = parser.parse_args()
    seed()
    report = build_export(execute_boundary())
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(path), "checks": report["boundary_execution"]["checks"]}))


if __name__ == "__main__":
    main()
