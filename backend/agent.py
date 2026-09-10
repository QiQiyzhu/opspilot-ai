"""Auditable state machine. Records public structured decisions, never private chain of thought."""

import asyncio
import time
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import select, func, or_
from backend.db import session_scope
from backend.models import AgentRun, RunEvent, Conversation, Message, Memory, ToolCall, as_dict, now
from backend.providers import PROVIDERS
from backend.security import redact, injection_signals
from backend.registry import snapshot, validate_workflow
from backend.tools import call_tool
from backend.rag import cached_search, search
from backend.config import settings
from backend.cache import cache
from backend.intent_contract import VERSION as INTENT_CONTRACT_VERSION, with_contract, next_step

TASKS: dict[str, asyncio.Task] = {}
DEFAULT = {
    "provider": "fake",
    "retrieval": "hybrid_rerank",
    "top_k": 5,
    "transport": "native",
    "memory": True,
    "multi_agent": False,
    "prompt_version": 1,
    "workflow_id": "support-qa",
    "workflow_version": 1,
    "ablation": "full",
}
TERMINAL = {"completed", "failed", "cancelled"}


def event(run_id, event_type, payload):
    with session_scope() as s:
        # Serializes SSE sequence generation across approval and agent coroutines/processes.
        s.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        sequence = (s.scalar(select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run_id)) or 0) + 1
        payload = {
            "trace_id": run_id,
            "span_id": uuid4().hex[:16],
            "parent_span_id": run_id[:16],
            "timestamp": now().isoformat(),
            **payload,
        }
        row = RunEvent(run_id=run_id, sequence=sequence, type=event_type, payload=redact(payload))
        s.add(row)
        s.flush()
        return as_dict(row)


def update_run(run_id, **fields):
    with session_scope() as s:
        run = s.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if run.status == "cancelled" and fields.get("status") != "cancelled":
            raise asyncio.CancelledError()
        for key, value in fields.items():
            setattr(run, key, value)


def run_detail(run_id):
    with session_scope() as s:
        run = s.get(AgentRun, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        result = as_dict(run)
        result["trace"] = [
            as_dict(r) for r in s.scalars(select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.sequence))
        ]
        result["tool_calls"] = [
            as_dict(r)
            for r in s.scalars(select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.created_at))
        ]
        result["next_step"] = next(
            (item["payload"] for item in reversed(result["trace"]) if item["type"] == "intent.next_step"), None
        )
        return result


def create_run(conversation_id, text, order_id=None, config=None):
    cfg = {**DEFAULT, "provider": settings().provider, **(config or {})}
    if cfg["provider"] not in PROVIDERS or cfg["transport"] not in {"native", "mcp"}:
        raise HTTPException(422, "Invalid provider or tool transport")
    prompt = snapshot("support-system", cfg["prompt_version"])
    workflow = snapshot(cfg["workflow_id"], cfg["workflow_version"])
    validate_workflow(workflow["definition"])
    retrieve_node = next((n for n in workflow["definition"]["nodes"] if n["type"] == "Retrieve"), None)
    if retrieve_node:
        if not config or "retrieval" not in config:
            cfg["retrieval"] = retrieve_node["config"].get("mode", "hybrid_rerank")
        if not config or "top_k" not in config:
            cfg["top_k"] = retrieve_node["config"].get("top_k", 5)
    cfg.update(
        prompt_snapshot=prompt,
        workflow_snapshot=workflow,
        order_id=order_id,
        intent_contract_version=INTENT_CONTRACT_VERSION,
        intent_contract_prompt=with_contract(prompt["content"]),
    )
    with session_scope() as s:
        if not s.get(Conversation, conversation_id):
            raise HTTPException(404, "Conversation not found")
        row = AgentRun(conversation_id=conversation_id, input=text, config=cfg)
        s.add(row)
        s.flush()
        s.add(Message(conversation_id=conversation_id, role="user", text=text, run_id=row.id))
        return row.id


def enqueue(run_id, user):
    task = asyncio.create_task(execute(run_id, user))
    TASKS[run_id] = task
    task.add_done_callback(lambda _: TASKS.pop(run_id, None))


def memories(customer_id):
    with session_scope() as s:
        return [
            as_dict(m)
            for m in s.scalars(
                select(Memory).where(
                    Memory.customer_id == customer_id,
                    Memory.valid.is_(True),
                    or_(Memory.expires_at.is_(None), Memory.expires_at > now()),
                )
            )
        ]


async def complete(run_id, text, verification=None):
    detail = run_detail(run_id)
    update_run(run_id, state="RESPOND")
    if verification is not None:
        update_run(run_id, verification=verification)
        event(run_id, "verification.completed", {"evidence": verification})
    for start in range(0, len(text), 50):
        event(run_id, "response.delta", {"text": text[start : start + 50]})
        await asyncio.sleep(0)
    with session_scope() as s:
        run = s.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if run.status == "cancelled":
            return
        run.response, run.status, run.state = text, "completed", "COMPLETE"
        run.duration_ms = (now() - run.created_at).total_seconds() * 1000
        s.add(Message(conversation_id=run.conversation_id, role="assistant", text=text, run_id=run.id))
    event(
        run_id,
        "run.completed",
        {
            "status": "completed",
            "duration_ms": run_detail(run_id)["duration_ms"],
            "provider": detail["config"]["provider"],
            "business": "SIMULATED BUSINESS",
        },
    )


async def execute(run_id, user):
    started = time.perf_counter()
    detail = run_detail(run_id)
    cfg, message = detail["config"], detail["input"]
    fault = cfg.get("fault")
    context = {}
    with session_scope() as s:
        conversation = s.get(Conversation, detail["conversation_id"])
        customer_id = conversation.customer_id

    async def tool(name, args):
        update_run(run_id, state="ACT")
        event(run_id, "tool.started", {"name": name, "arguments": args, "transport": cfg["transport"]})
        value = await call_tool(name, args, user, customer_id, run_id, cfg["transport"], fault)
        event(run_id, "tool.completed", {"name": name, "result": value})
        return value

    try:
        update_run(run_id, status="running", state="INTAKE")
        event(run_id, "run.started", {"config": cfg, "trace_id": run_id, "span_id": uuid4().hex[:16]})
        if injection_signals(message):
            event(
                run_id,
                "security.detected",
                {
                    "source": "user_input",
                    "signals": injection_signals(message),
                    "action": "untrusted instruction rejected; server rules retained",
                },
            )
        if fault == "redis_unavailable":
            cache.degraded_until = time.monotonic() + 30
        remembered = memories(customer_id) if cfg["memory"] and cfg["ablation"] in {"full", "multi"} else []
        context["memory"] = remembered
        if remembered:
            event(run_id, "memory.loaded", {"items": remembered})
        if cache.degraded_until > time.monotonic():
            event(
                run_id,
                "fallback.activated",
                {"component": "redis", "mode": "bounded process cache", "max_entries": 128},
            )
        evidence = []
        intent = None
        workflow = cfg["workflow_snapshot"]["definition"]
        for node in workflow["nodes"]:
            event(run_id, "workflow.node", {"node_id": node["id"], "type": node["type"], "config": node["config"]})
            nc = node["config"]
            if node["type"] == "LLM":
                update_run(run_id, state="UNDERSTAND")
                if fault == "provider_timeout":
                    try:
                        await asyncio.wait_for(asyncio.sleep(0.05), timeout=0.001)
                    except TimeoutError:
                        event(
                            run_id,
                            "fallback.activated",
                            {
                                "component": "provider",
                                "error": "TimeoutError",
                                "mode": "safe escalation; no guessed business answer",
                            },
                        )
                        raise
                result = await asyncio.wait_for(
                    PROVIDERS[cfg["provider"]].understand(
                        message, cfg.get("intent_contract_prompt", cfg["prompt_snapshot"]["content"])
                    ),
                    settings().provider_timeout + 1,
                )
                intent = result.data
                context["category"] = intent["category"]
                update_run(run_id, category=intent["category"], tokens=result.tokens)
                event(
                    run_id,
                    "model.completed",
                    {
                        "model": result.model,
                        "prompt_version": cfg["prompt_version"],
                        "latency_ms": result.latency_ms,
                        "request_id": result.request_id,
                        "usage": result.tokens,
                        "cost": result.cost,
                        "decision": intent,
                        "metadata": result.metadata,
                        "intent_contract_version": cfg.get("intent_contract_version", 1),
                    },
                )
                if cfg["multi_agent"] or cfg["ablation"] == "multi":
                    specialist = (
                        "Order Specialist"
                        if intent["category"] in {"order_query", "refund", "cancellation"}
                        else "Technical Support Specialist"
                        if intent["category"] in {"replacement", "troubleshooting"}
                        else "Policy Specialist"
                    )
                    second = await PROVIDERS[cfg["provider"]].understand(
                        message,
                        cfg.get("intent_contract_prompt", cfg["prompt_snapshot"]["content"])
                        + "\nYou are " + specialist + ". Check the routing decision.",
                    )
                    event(
                        run_id,
                        "specialist.completed",
                        {
                            "specialist": specialist,
                            "decision": second.data,
                            "latency_ms": second.latency_ms,
                            "usage": second.tokens,
                        },
                    )
                    if second.data["category"] != intent["category"]:
                        context["category"] = "ambiguous"
                        intent["category"] = "ambiguous"
                    event(
                        run_id,
                        "supervisor.completed",
                        {"decision": "compose grounded observations; escalate disagreements"},
                    )
                if cfg.get("intent_contract_version", 1) >= 2:
                    follow_up = next_step(intent["category"], cfg.get("order_id") or intent.get("order_id"))
                    if follow_up:
                        event(run_id, "intent.next_step", follow_up)
                        await complete(run_id, follow_up["question"] + " " + follow_up["detail"])
                        return
            elif node["type"] == "Retrieve" and cfg["ablation"] != "llm_only":
                update_run(run_id, state="RETRIEVE")
                if fault == "retrieval_error":
                    raise RuntimeError("Injected retrieval unavailable")
                retrieval = await asyncio.wait_for(
                    asyncio.to_thread(
                        search if cfg.get("bypass_cache") else cached_search,
                        message,
                        cfg.get("retrieval", nc.get("mode", "hybrid_rerank")),
                        cfg.get("top_k", nc.get("top_k", 5)),
                    ),
                    timeout=settings().retrieval_timeout,
                )
                evidence = retrieval["results"]
                for item in evidence:
                    signals = injection_signals(item["text"])
                    if signals:
                        event(
                            run_id,
                            "security.detected",
                            {
                                "source": item["chunk_id"],
                                "signals": signals,
                                "action": "quarantined from answer context",
                            },
                        )
                evidence = [e for e in evidence if not injection_signals(e["text"])]
                update_run(run_id, evidence=evidence)
                event(run_id, "retrieval.completed", retrieval)
            elif node["type"] == "Condition":
                matches = context.get(nc["field"]) == nc["value"]
                passes = matches if nc["operator"] == "equals" else not matches
                event(run_id, "condition.evaluated", {"node": node["id"], "passed": passes})
                if not passes:
                    update_run(run_id, state="ESCALATE", category=context.get("category", "out_of_scope"))
                    await complete(
                        run_id,
                        "This request needs human support or is outside NovaMart operations. No business action was executed.",
                    )
                    return
            elif node["type"] == "Tool" and cfg["ablation"] not in {"llm_only", "rag"}:
                name = nc["name"]
                args = dict(nc.get("arguments", {}))
                if name == "get_customer":
                    args = {"customer_id": customer_id}
                elif name in {"get_order", "check_refund_eligibility", "check_replacement_eligibility"}:
                    oid = cfg.get("order_id") or (intent or {}).get("order_id")
                    if not oid:
                        continue
                    args = {"order_id": oid}
                elif name in {"propose_refund", "propose_replacement", "cancel_order"}:
                    # Configured proposals are processed by the same guarded business branch below.
                    continue
                context[name] = await tool(name, args)
            elif node["type"] == "Approval":
                context["approval_gate"] = True
            elif node["type"] == "Output":
                context["require_verification"] = nc.get("require_verification", True)
        if intent is None:
            raise ValueError("Workflow did not produce an intent")
        category = intent["category"]
        order_id = cfg.get("order_id") or intent.get("order_id")
        plan = (
            [
                "Read current policy evidence",
                "Read scoped business records",
                "Check eligibility",
                "Propose action for human approval",
                "Verify committed state before response",
            ]
            if category in {"refund", "replacement", "cancellation"}
            else ["Retrieve current evidence", "Read relevant facts", "Respond with citations or ask for clarification"]
        )
        update_run(run_id, state="PLAN", plan=plan)
        event(run_id, "plan.created", {"steps": plan, "kind": "auditable decision summary, not private reasoning"})
        if cfg["ablation"] in {"llm_only", "rag"} and category in {
            "refund",
            "replacement",
            "cancellation",
            "order_query",
        }:
            await complete(
                run_id,
                "This baseline cannot access business tools. A support operator must look up the order and handle the request.",
            )
            return
        if category in {"refund", "replacement", "cancellation", "order_query"}:
            if not order_id:
                update_run(run_id, category="missing_information")
                await complete(
                    run_id,
                    "Please provide your NovaMart order identifier so I can check the correct order. No action has been taken.",
                )
                return
            order = await tool("get_order", {"order_id": order_id})
            if category == "order_query":
                await complete(
                    run_id,
                    f"Order {order_id} is {order['status']}. Tracking: {order.get('tracking') or 'not available; no shipment is recorded'}. This is the current simulated database record.",
                    [
                        {
                            "verified": True,
                            "order_id": order_id,
                            "observed_status": order["status"],
                            "method": "database_read",
                        }
                    ]
                    if cfg["ablation"] not in {"tools"}
                    else None,
                )
                return
            action = {"refund": "refund", "replacement": "replacement", "cancellation": "cancel"}[category]
            policy = await tool(
                "get_active_policy",
                {"category": {"refund": "refund", "replacement": "warranty", "cancel": "shipping"}[action]},
            )
            if action == "replacement":
                await tool("get_inventory", {"product_id": order["product_id"]})
                troubleshooting = await tool("search_knowledge", {"query": "Device Troubleshooting no power warranty"})
                event(
                    run_id,
                    "technical.review",
                    {
                        "evidence": [e["chunk_id"] for e in troubleshooting["results"]],
                        "serial_number": next((m["value"] for m in remembered if m["key"] == "serial_number"), None),
                        "operator_check": "Confirm troubleshooting and exclusions before approval",
                    },
                )
            if action != "cancel":
                check = await tool(f"check_{action}_eligibility", {"order_id": order_id})
                if not check["eligible"]:
                    await complete(
                        run_id,
                        f"I cannot propose this {action}: {check['reason']}. Current evidence: {policy['title']} v{policy['version']}. Human support can review the case; no action was executed.",
                    )
                    return
            if not context.get("approval_gate"):
                raise RuntimeError("Workflow has no approval gate")
            proposed = await tool(
                {"refund": "propose_refund", "replacement": "propose_replacement", "cancel": "cancel_order"}[action],
                {"order_id": order_id, "reason": message, "idempotency_key": "run-proposal:" + run_id},
            )
            update_run(run_id, status="waiting_approval", proposal_id=proposed["id"], state="ACT")
            event(run_id, "approval.required", proposed)
            return
        if category == "ambiguous":
            await complete(
                run_id,
                "Please clarify the outcome you want: order tracking, refund, replacement or technical help. If an item is damaged, do you prefer a refund or replacement? No action was taken.",
            )
        elif category == "troubleshooting":
            if any(v in message.lower() for v in ["smoking", "overheat", "swollen", "冒烟"]):
                update_run(run_id, state="ESCALATE")
                await complete(
                    run_id,
                    "Stop using the device and contact qualified support. Do not open the battery enclosure. This case requires human assessment; no remote diagnosis or automatic replacement was made.",
                )
            else:
                serial = next((m["value"] for m in remembered if m["key"] == "serial_number"), None)
                text = "Check the USB-C cable and adapter, charge for 30 minutes, then hold power for 10 seconds. "
                if "bluetooth" in message.lower():
                    text = "Toggle Bluetooth, forget the previous pairing, hold the pair button for 5 seconds, and reconnect within 2 meters. "
                text += (
                    f"Your confirmed serial number {serial} is already recorded. "
                    if serial
                    else "Please provide the device serial number. "
                )
                text += "If the steps fail, we can check warranty; repair success has not been verified. [Device Troubleshooting v1]"
                await complete(run_id, text)
        elif evidence:
            excerpts = [f"[{e['title']} v{e['version']} / {e['section']}] {e['text']}" for e in evidence[:2]]
            await complete(run_id, "Current policy evidence (extractive response):\n" + "\n\n".join(excerpts))
        else:
            await complete(
                run_id,
                "I could not find reliable current policy evidence for that question. Please clarify or ask a human support operator. No unsupported business claim was made.",
            )
    except asyncio.CancelledError:
        update_run(run_id, status="cancelled", state="FAILED")
        event(run_id, "run.cancelled", {"reason": "Cancellation requested; committed approvals are not undone"})
    except Exception as exc:
        safe_error = str(redact(str(exc)))[:300]
        update_run(
            run_id,
            status="failed",
            state="FAILED",
            error=type(exc).__name__ + ": " + safe_error,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        event(
            run_id,
            "run.failed",
            {
                "error_type": type(exc).__name__,
                "message": safe_error,
                "fallback": "No operation is claimed successful. Human support can retry after the cause is resolved.",
            },
        )


async def resume_approval(proposal):
    if not proposal.get("run_id"):
        return
    run_id = proposal["run_id"]
    with session_scope() as s:
        run = s.scalar(select(AgentRun).where(AgentRun.id == run_id).with_for_update())
        if run.status != "waiting_approval":
            return
        run.status = "running"
    if proposal["status"] == "rejected":
        await complete(run_id, "The human reviewer rejected this proposal. No business action was executed.")
    elif proposal["status"] == "executed":
        verification = proposal.get("verification")
        if not verification or not verification["verified"]:
            update_run(
                run_id, status="failed", state="FAILED", error="Post-commit verification failed; manual review required"
            )
            event(run_id, "run.failed", {"error": "Business verification did not pass"})
            return
        wording = {
            "refund": "The refund was submitted to the simulated ledger. This does not mean bank settlement has completed.",
            "replacement": "The replacement request was created and inventory reserved in the simulated database.",
            "cancel": "The order was cancelled in the simulated database.",
        }[proposal["action"]]
        await complete(run_id, wording + " A separate database read verified the recorded status.", [verification])
