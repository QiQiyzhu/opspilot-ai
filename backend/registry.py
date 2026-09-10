import difflib
import json
from fastapi import HTTPException
from sqlalchemy import select
from backend.db import session_scope
from backend.models import Registry, EvaluationRun, as_dict, now

TYPES = {"Input", "Retrieve", "LLM", "Tool", "Condition", "Approval", "Output"}
ALLOWED_TOOLS = {
    "get_customer",
    "get_order",
    "get_inventory",
    "search_knowledge",
    "get_active_policy",
    "create_ticket_note",
    "check_refund_eligibility",
    "check_replacement_eligibility",
    "propose_refund",
    "propose_replacement",
    "cancel_order",
    "escalate_ticket",
}


def validate_workflow(definition):
    if not isinstance(definition, dict) or not isinstance(definition.get("nodes"), list):
        raise HTTPException(422, "Workflow definition must contain a nodes array")
    nodes = definition.get("nodes", [])
    if any(not isinstance(n, dict) or not isinstance(n.get("config", {}), dict) for n in nodes):
        raise HTTPException(422, "Each node and node config must be an object")
    if not 2 <= len(nodes) <= 20 or nodes[0].get("type") != "Input" or nodes[-1].get("type") != "Output":
        raise HTTPException(422, "Workflow must have 2..20 ordered nodes, Input first and Output last")
    ids = [n.get("id") for n in nodes]
    if len(set(ids)) != len(ids) or any(not v for v in ids):
        raise HTTPException(422, "Node IDs must be unique and nonempty")
    if sum(n["type"] == "LLM" for n in nodes) != 1:
        raise HTTPException(422, "Exactly one structured-intent LLM node is required")
    intent_index = next(i for i, n in enumerate(nodes) if n["type"] == "LLM")
    if any(n["type"] == "Tool" for n in nodes[:intent_index]):
        raise HTTPException(422, "Business tool nodes must follow structured intent and its clarification gate")
    if not any(n["type"] == "Approval" for n in nodes):
        raise HTTPException(422, "Approval gate cannot be removed from operations workflows")
    for n in nodes:
        if n.get("type") not in TYPES:
            raise HTTPException(422, "Unknown node type")
        cfg = n.get("config", {})
        if n["type"] == "Approval" and not {"refund", "replacement", "cancel"}.issubset(set(cfg.get("actions", []))):
            raise HTTPException(422, "Approval must cover refund, replacement and cancellation")
        if n["type"] == "Tool" and cfg.get("name") not in ALLOWED_TOOLS:
            raise HTTPException(422, "Unknown or unauthorized workflow tool")
        if n["type"] == "Condition" and (
            cfg.get("field") != "category"
            or cfg.get("operator") not in {"equals", "not_equals"}
            or cfg.get("on_false") not in {"escalate", "stop"}
        ):
            raise HTTPException(422, "Condition supports category equals/not_equals, on_false escalate/stop")
        if n["type"] == "Retrieve" and (
            cfg.get("mode", "hybrid_rerank") not in {"keyword", "dense", "hybrid", "hybrid_rerank"}
            or not 1 <= cfg.get("top_k", 5) <= 20
        ):
            raise HTTPException(422, "Invalid retrieval config")
    return definition


def snapshot(registry_id, version=None):
    with session_scope() as s:
        row = s.get(Registry, registry_id)
        if not row:
            raise HTTPException(404, "Registry entry not found")
        selected = version or row.active_version
        item = next((v for v in row.versions if v["version"] == selected), None)
        if item is None:
            raise HTTPException(404, "Version not found")
        return item


def add_version(registry_id, data):
    with session_scope() as s:
        row = s.scalar(select(Registry).where(Registry.id == registry_id).with_for_update())
        if not row:
            raise HTTPException(404, "Registry entry not found")
        field = "content" if row.kind == "prompt" else "definition"
        if field not in data:
            raise HTTPException(422, f"Missing {field}")
        if row.kind == "workflow":
            validate_workflow(data[field])
        elif not isinstance(data[field], str) or not 10 <= len(data[field]) <= 12000:
            raise HTTPException(422, "Prompt must contain 10..12000 characters")
        row.versions = row.versions + [
            {
                "version": max(v["version"] for v in row.versions) + 1,
                field: data[field],
                "created_at": now().isoformat(),
            }
        ]
        return as_dict(row)


def diff(registry_id, from_version, to_version):
    a, b = snapshot(registry_id, from_version), snapshot(registry_id, to_version)

    def render(v):
        return v.get("content", json.dumps(v.get("definition"), indent=2, ensure_ascii=False))

    return {
        "diff": "\n".join(
            difflib.unified_diff(
                render(a).splitlines(),
                render(b).splitlines(),
                fromfile=f"v{from_version}",
                tofile=f"v{to_version}",
                lineterm="",
            )
        )
    }


def release(registry_id, version, evaluation_id):
    with session_scope() as s:
        row = s.scalar(select(Registry).where(Registry.id == registry_id).with_for_update())
        report = s.get(EvaluationRun, evaluation_id)
        if not row or not any(v["version"] == version for v in row.versions):
            raise HTTPException(404, "Version not found")
        if not report or report.config.get("prompt_version") != version:
            raise HTTPException(409, "Regression report must evaluate this exact prompt version")
        threshold = {"task_success_rate": 0.80, "unsafe_action_rate": 0.0}
        passed = (
            report.status == "completed"
            and report.metrics.get("task_success_rate", 0) >= 0.80
            and report.metrics.get("unsafe_action_rate", 1) == 0
        )
        if not passed:
            raise HTTPException(409, {"gate": "failed", "thresholds": threshold, "metrics": report.metrics})
        row.active_version = version
        return {
            "gate": "passed",
            "registry": as_dict(row),
            "evaluation_id": evaluation_id,
            "scope": "offline fake-provider regression only; real LLM release requires real-provider evaluation",
        }
