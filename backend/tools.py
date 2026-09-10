import asyncio
import json
import time
from pydantic import BaseModel, ConfigDict, Field
from fastapi import HTTPException
from sqlalchemy import select
from backend import business, rag
from backend.db import session_scope
from backend.models import Customer, Order, Inventory, SupportTicket, ToolCall, as_dict
from backend.security import Principal, require, redact
from backend.config import settings


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: str | None = Field(None, max_length=64)
    order_id: str | None = Field(None, max_length=64)
    product_id: str | None = Field(None, max_length=64)
    ticket_id: str | None = Field(None, max_length=64)
    query: str | None = Field(None, max_length=2000)
    category: str | None = Field(None, max_length=64)
    text: str | None = Field(None, max_length=3000)
    reason: str | None = Field(None, max_length=3000)
    idempotency_key: str | None = Field(None, max_length=160)


SPECS = {
    "get_customer": ("READ_ONLY", ["customer_id"]),
    "get_order": ("READ_ONLY", ["order_id"]),
    "get_inventory": ("READ_ONLY", ["product_id"]),
    "search_knowledge": ("READ_ONLY", ["query"]),
    "get_active_policy": ("READ_ONLY", ["category"]),
    "create_ticket_note": ("LOW_RISK_WRITE", ["ticket_id", "text", "idempotency_key"]),
    "check_refund_eligibility": ("READ_ONLY", ["order_id"]),
    "check_replacement_eligibility": ("READ_ONLY", ["order_id"]),
    "propose_refund": ("HIGH_RISK_ACTION", ["order_id", "reason", "idempotency_key"]),
    "propose_replacement": ("HIGH_RISK_ACTION", ["order_id", "reason", "idempotency_key"]),
    "cancel_order": ("HIGH_RISK_ACTION", ["order_id", "reason", "idempotency_key"]),
    "escalate_ticket": ("LOW_RISK_WRITE", ["ticket_id", "reason", "idempotency_key"]),
}


def catalog():
    return {
        "items": [
            {
                "name": name,
                "risk": risk,
                "permission": "read" if risk == "READ_ONLY" else "operator",
                "timeout_seconds": 5,
                "idempotency": "required for writes" if risk != "READ_ONLY" else "read only",
                "input_schema": {**Arguments.model_json_schema(), "required": required},
                "output_schema": {"type": "object"},
                "execution": "proposal only; server approval required"
                if risk == "HIGH_RISK_ACTION"
                else "native or MCP",
            }
            for name, (risk, required) in SPECS.items()
        ]
    }


def native_tool(name, arguments, user: Principal, customer_scope=None, run_id=None):
    if name not in SPECS:
        raise ValueError("Tool not allowlisted")
    args = Arguments.model_validate(arguments).model_dump(exclude_none=True)
    risk, required = SPECS[name]
    if any(key not in args for key in required):
        raise ValueError("Missing required tool arguments")
    if risk != "READ_ONLY":
        require(user, "operator", "admin")
    # Scope is server-derived conversation identity, not model-supplied customer_id.
    if customer_scope:
        if args.get("customer_id") and args["customer_id"] != customer_scope:
            raise HTTPException(403, "Cross-customer tool access denied")
        for key, model in [("order_id", Order), ("ticket_id", SupportTicket)]:
            if args.get(key):
                target = business.get_entity(model, args[key])
                if target["customer_id"] != customer_scope:
                    raise HTTPException(403, "Cross-customer tool access denied")
    if name == "get_customer":
        return business.get_entity(Customer, args["customer_id"])
    if name == "get_order":
        return business.get_entity(Order, args["order_id"])
    if name == "get_inventory":
        with session_scope() as s:
            row = s.scalar(select(Inventory).where(Inventory.product_id == args["product_id"]))
            return as_dict(row) or {"available": 0}
    if name == "search_knowledge":
        return rag.search(args["query"])
    if name == "get_active_policy":
        return rag.active_policy(args["category"]) or {"error": "No active policy"}
    if name in {"check_refund_eligibility", "check_replacement_eligibility"}:
        return business.eligibility(args["order_id"], "refund" if "refund" in name else "replacement")
    if name in {"propose_refund", "propose_replacement", "cancel_order"}:
        action = {"propose_refund": "refund", "propose_replacement": "replacement", "cancel_order": "cancel"}[name]
        return business.propose(args["order_id"], action, args["reason"], args["idempotency_key"], user, run_id)
    if name == "create_ticket_note":
        return business.add_note(args["ticket_id"], args["text"], args["idempotency_key"], user)
    if name == "escalate_ticket":
        result = business.add_note(args["ticket_id"], "Escalation: " + args["reason"], args["idempotency_key"], user)
        with session_scope() as s:
            ticket = s.get(SupportTicket, args["ticket_id"])
            ticket.status, ticket.priority = "escalated", "high"
            result["status"] = ticket.status
        return result
    raise ValueError("Tool is not implemented")


MCP_NAMES = {
    "get_customer": "customers.get",
    "get_order": "orders.get",
    "search_knowledge": "knowledge.search",
    "create_ticket_note": "tickets.add_note",
}


async def call_tool(name, args, user, customer_scope, run_id, transport="native", fault=None):
    started = time.perf_counter()
    result, status = {}, "success"
    actual_transport = "mcp" if transport == "mcp" and name in MCP_NAMES else "native"
    try:
        if fault == "tool_timeout":
            await asyncio.wait_for(asyncio.sleep(0.05), timeout=0.001)
        if fault == "invalid_tool_schema":
            Arguments.model_validate({"unknown_key": "bad"})
        if actual_transport == "mcp":
            # Validate scope before leaving the process. The remote server authenticates independently.
            if args.get("order_id"):
                order = await asyncio.to_thread(business.get_entity, Order, args["order_id"])
                if order["customer_id"] != customer_scope:
                    raise HTTPException(403, "Cross-customer tool access denied")
            from mcp import Client
            from mcp.client.streamable_http import streamable_http_client
            import httpx2

            async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + settings().mcp_token}) as http:
                async with Client(
                    streamable_http_client(settings().mcp_url, http_client=http), read_timeout_seconds=5
                ) as client:
                    response = await client.call_tool(MCP_NAMES[name], args)
                    if response.is_error:
                        raise RuntimeError("MCP tool returned an error")
                    result = response.structured_content
                    if result is None:
                        result = json.loads(response.content[0].text)
        else:
            result = await asyncio.wait_for(
                asyncio.to_thread(native_tool, name, args, user, customer_scope, run_id), timeout=5
            )
        if not isinstance(result, dict):
            raise ValueError("Tool output is not an object")
        return result
    except Exception as exc:
        status, result = "error", {"error_type": type(exc).__name__, "message": str(exc)[:300]}
        raise
    finally:
        with session_scope() as s:
            s.add(
                ToolCall(
                    run_id=run_id,
                    name=name,
                    transport=actual_transport,
                    risk=SPECS.get(name, ("UNKNOWN", []))[0],
                    arguments=redact(args),
                    result=redact(result),
                    status=status,
                    duration_ms=(time.perf_counter() - started) * 1000,
                )
            )
