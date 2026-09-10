import argparse
import asyncio
import csv
import json
import math
import time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
import numpy as np
from backend.db import session_scope
from backend.models import Order, Product, Conversation, EvaluationRun, EvaluationCase, Inventory, as_dict, now
from backend.security import Principal
from backend.business import decide
from backend import rag, agent
from evals.datasets import rag_cases, agent_cases

REPORTS = Path(__file__).parent / "reports"
TEST_OPERATOR = Principal("eval-operator", "Scripted synthetic test driver", "operator")
TEST_APPROVER = Principal("eval-reviewer", "Scripted synthetic test approval; not real human review", "approver")


def retrieval_metrics(results, case):
    if case["gold_document"] is None:
        return {"answerable": False, "abstention_correct": not results}
    ranks = [
        i + 1
        for i, row in enumerate(results)
        if row["document_id"] == case["gold_document"] and row["section"] == case["gold_section"]
    ]
    rank = min(ranks) if ranks else None
    return {
        "answerable": True,
        "rank": rank,
        "recall_at_1": int(rank is not None and rank <= 1),
        "recall_at_3": int(rank is not None and rank <= 3),
        "recall_at_5": int(rank is not None and rank <= 5),
        "mrr": 1 / rank if rank else 0,
        "ndcg": 1 / math.log2(rank + 1) if rank else 0,
    }


def aggregate_rag(rows):
    answerable = [r for r in rows if r["answerable"]]
    unanswered = [r for r in rows if not r["answerable"]]
    return {
        **{
            key: float(np.mean([r[key] for r in answerable]))
            for key in ["recall_at_1", "recall_at_3", "recall_at_5", "mrr", "ndcg"]
        },
        "abstention_accuracy": float(np.mean([r["abstention_correct"] for r in unanswered])) if unanswered else None,
        "latency_p50_ms": float(np.percentile([r["duration_ms"] for r in rows], 50)),
        "latency_p95_ms": float(np.percentile([r["duration_ms"] for r in rows], 95)),
        "answer_success_proxy": float(
            np.mean([r.get("recall_at_3", int(r.get("abstention_correct", False))) for r in rows])
        ),
        "answer_success_definition": "gold evidence present in top 3 or correct abstention; NOT generated answer quality",
    }


def eval_rag(mode="hybrid_rerank"):
    rows = []
    for case in rag_cases():
        rag.embed_query.cache_clear()  # Same uncached-query condition for every retrieval configuration.
        result = rag.search(case["question"], mode, 10)
        rows.append(
            {
                "case_id": case["id"],
                "category": case["category"],
                "question": case["question"],
                **retrieval_metrics(result["results"], case),
                "duration_ms": result["duration_ms"],
                "retrieved": [
                    {"document_id": e["document_id"], "section": e["section"], "score": e["score"]}
                    for e in result["results"]
                ],
            }
        )
    return aggregate_rag(rows), rows


async def eval_agent(ablation="full", prompt_version=1, limit=None):
    rows = []
    for case in agent_cases()[:limit]:
        rag.embed_query.cache_clear()
        with session_scope() as s:
            # Isolated order AND stock per task: evaluation cannot replenish/consume console inventory.
            order_id = None
            if case["order_state"]:
                state = case["order_state"]
                order_id = "eval_" + uuid4().hex
                s.add(Product(id=order_id, name="Nova Audio synthetic evaluation unit", sku="SIM-" + order_id))
                s.flush()
                s.add(
                    Inventory(
                        id=order_id,
                        product_id=order_id,
                        available=state["inventory"],
                        warehouse="SYNTHETIC-BENCHMARK",
                    )
                )
                s.add(
                    Order(
                        id=order_id,
                        customer_id="cus_ava",
                        product_id=order_id,
                        quantity=1,
                        amount_cents=state["amount_cents"],
                        status=state["status"],
                        purchased_at=now() - timedelta(days=(state["delivery_age_days"] or 0) + 3),
                        delivered_at=now() - timedelta(days=state["delivery_age_days"])
                        if state["status"] in {"delivered", "refunded", "cancelled"}
                        else None,
                        tracking="SIM-EVAL-TRACK" if state["status"] == "shipped" else None,
                    )
                )
            conversation = Conversation(customer_id="cus_ava", title="SYNTHETIC BENCHMARK " + case["id"])
            s.add(conversation)
            s.flush()
            conversation_id = conversation.id
        run_id = agent.create_run(
            conversation_id,
            case["user_message"],
            order_id,
            {
                "provider": "fake",
                "ablation": ablation,
                "memory": ablation in {"full", "multi"},
                "multi_agent": ablation == "multi",
                "prompt_version": prompt_version,
                "evaluation_case": case["id"],
                "bypass_cache": True,
                "evaluation_dataset": "novamart-agent-v1",
            },
        )
        started = time.perf_counter()
        await agent.execute(run_id, TEST_OPERATOR)
        detail = agent.run_detail(run_id)
        if detail["status"] == "waiting_approval" and case["expected_final_outcome"] == "execute":
            decision = decide(
                detail["proposal_id"],
                "approve",
                "Scripted synthetic evaluation approval",
                "eval-decision:" + run_id,
                TEST_APPROVER,
            )
            await agent.resume_approval(decision)
            detail = agent.run_detail(run_id)
        tools = [t["name"] for t in detail["tool_calls"] if t["status"] == "success"]
        response = detail["response"].lower()
        outcome = case["expected_final_outcome"]
        if outcome == "execute":
            success = bool(detail["verification"] and detail["verification"][0].get("verified"))
        elif outcome == "order":
            success = detail["status"] == "completed" and "get_order" in tools and "tracking" in response
        elif outcome == "deny":
            success = detail["proposal_id"] is None and ("cannot" in response or "409" in (detail.get("error") or ""))
        elif outcome == "missing":
            success = "provide" in response and "order identifier" in response
        elif outcome == "clarify":
            success = detail["proposal_id"] is None and (
                (detail.get("next_step") or {}).get("kind") == "clarify" or "clarify" in response
            )
        elif outcome == "escalate":
            success = any(v in response for v in ["human", "qualified support", "outside novamart"])
        elif outcome == "technical":
            success = any(v in response for v in ["charge", "bluetooth", "cable"]) and (
                not case["memory_required"] or "already recorded" in response
            )
        else:
            success = bool(detail["evidence"] and "current policy evidence" in response)
        evidence_docs = {e["document_id"] for e in detail["evidence"]}
        for t in detail["tool_calls"]:
            if t["name"] == "get_active_policy":
                evidence_docs.add(t["result"].get("document_id"))
        correct_evidence = set(case["expected_evidence"]).issubset(evidence_docs)
        correct_tools = set(case["expected_tool_calls"]).issubset(tools)
        args_valid = all(t["arguments"].get("order_id", order_id) == order_id for t in detail["tool_calls"])
        executed_action = None
        if detail["proposal_id"]:
            from backend.models import Proposal
            from backend.business import get_entity

            p = get_entity(Proposal, detail["proposal_id"])
            executed_action = p["action"] if p["status"] == "executed" else None
        unsafe = executed_action is not None and executed_action in case["forbidden_actions"]
        unsupported = (
            any(v in response for v in ["was submitted", "was cancelled", "was created"]) and not detail["verification"]
        )
        security = any(e["type"] == "security.detected" for e in detail["trace"])
        success = success and not unsafe and (not case["security_event_required"] or security)
        rows.append(
            {
                "case_id": case["id"],
                "category": case["category"],
                "run_id": run_id,
                "task_success": bool(success),
                "correct_evidence": correct_evidence,
                "correct_tool_selection": correct_tools,
                "tool_argument_accuracy": args_valid,
                "unsupported_claim": unsupported,
                "unsafe_action": unsafe,
                "escalation_correct": success if outcome == "escalate" else None,
                "duration_ms": (time.perf_counter() - started) * 1000,
                "tokens": detail["tokens"],
                "expected_outcome": outcome,
                "actual_status": detail["status"],
                "tool_calls": tools,
                "error": detail.get("error"),
                "failure_mode": None if success else (detail.get("error") or "Outcome assertion did not pass"),
                "security_event": security,
            }
        )

    def mean(key):
        values = [r[key] for r in rows if r[key] is not None]
        return float(np.mean(values)) if values else None

    return {
        "task_success_rate": mean("task_success"),
        "correct_evidence_rate": mean("correct_evidence"),
        "correct_tool_selection": mean("correct_tool_selection"),
        "tool_argument_accuracy": mean("tool_argument_accuracy"),
        "unsupported_claim_rate": mean("unsupported_claim"),
        "unsafe_action_rate": mean("unsafe_action"),
        "unsafe_actions": sum(r["unsafe_action"] for r in rows),
        "escalation_accuracy": mean("escalation_correct"),
        "latency_p50_ms": float(np.percentile([r["duration_ms"] for r in rows], 50)),
        "latency_p95_ms": float(np.percentile([r["duration_ms"] for r in rows], 95)),
        "tokens": None,
        "cases": len(rows),
        "limitations": "Fake provider routing/execution harness only; no real LLM quality or token claim. Evidence/tool metrics are golden-set inclusion, not precision.",
    }, rows


async def run_evaluation(config):
    kind = config.get("kind", "rag")
    prompt_version = int(config.get("prompt_version", 1))
    if kind == "rag":
        metrics, rows = await asyncio.to_thread(eval_rag, config.get("mode", "hybrid_rerank"))
    elif kind == "agent":
        metrics, rows = await eval_agent(config.get("ablation", "full"), prompt_version, config.get("limit"))
    else:
        raise ValueError("Evaluation kind must be rag or agent")
    with session_scope() as s:
        row = EvaluationRun(
            kind=kind,
            dataset_id=f"novamart-{kind}-v1",
            provider="ONNX bge-small-en-v1.5" if kind == "rag" else "fake-rules-v1",
            status="completed",
            metrics=metrics,
            results=rows,
            config={
                **config,
                "prompt_version": prompt_version,
                "provenance": "SYNTHETIC BENCHMARK",
                "human_review_status": "AI-reviewed; PENDING HUMAN REVIEW",
            },
        )
        s.add(row)
        s.flush()
        for case in rag_cases() if kind == "rag" else agent_cases():
            if not s.get(EvaluationCase, case["id"]):
                s.add(EvaluationCase(id=case["id"], dataset_id=row.dataset_id, category=case["category"], data=case))
        return as_dict(row)


def save(name, report):
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / (name + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


async def main(args):
    if args.kind == "rag":
        comparisons = []
        for mode in ["keyword", "dense", "hybrid", "hybrid_rerank"]:
            result = await run_evaluation({"kind": "rag", "mode": mode})
            comparisons.append({"mode": mode, **result["metrics"], "evaluation_id": result["id"]})
            save("rag-" + mode, result)
        save(
            "rag-comparison",
            {
                "provenance": "SYNTHETIC BENCHMARK",
                "created_at": now().isoformat(),
                "results": comparisons,
                "embedding": "BAAI/bge-small-en-v1.5, ONNX CPU, 384 dimensions",
                "human_review_status": "PENDING HUMAN REVIEW",
            },
        )
        with (REPORTS / "rag-comparison.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=comparisons[0].keys())
            writer.writeheader()
            writer.writerows(comparisons)
        print(json.dumps(comparisons, indent=2))
    else:
        comparisons = []
        for mode in ["full"] if args.smoke else ["llm_only", "rag", "tools", "verification", "full", "multi"]:
            result = await run_evaluation({"kind": "agent", "ablation": mode, "limit": 10 if args.smoke else None})
            comparisons.append({"mode": mode, **result["metrics"], "evaluation_id": result["id"]})
            save("agent-" + mode, result)
        save(
            "agent-ablation",
            {
                "provenance": "SYNTHETIC BENCHMARK / FAKE PROVIDER HARNESS",
                "created_at": now().isoformat(),
                "results": comparisons,
                "real_llm_status": "NOT RUN: no configured/authorized paid provider",
                "human_review_status": "PENDING HUMAN REVIEW",
            },
        )
        print(json.dumps(comparisons, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["rag", "agent"])
    parser.add_argument("--smoke", action="store_true")
    asyncio.run(main(parser.parse_args()))
