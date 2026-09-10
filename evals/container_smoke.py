"""Actual TCP API/MCP/approval smoke. Uses only fresh simulated fixture orders."""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import uuid4
import httpx
import httpx2
import redis
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from backend.config import settings
from backend.demo_fixture import create_order
from backend.models import now


async def run(url, output, require_redis=False):
    order_id = create_order()
    token = "demo-admin"
    async with httpx.AsyncClient(base_url=url, headers={"Authorization": "Bearer " + token}, timeout=30) as client:
        health = await client.get("/api/health")
        health.raise_for_status()
        health_data = health.json()
        assert "PostgreSQL" in health_data["database"] and health_data["pgvector"]
        assert health_data["provider"] == "fake", "This smoke is explicitly scoped to FakeModelProvider"
        unauthorized = await client.get("/api/orders", headers={"Authorization": "Bearer invalid-token"})
        assert unauthorized.status_code == 401

        async with httpx2.AsyncClient(headers={"Authorization": "Bearer demo-operator"}) as http:
            async with Client(streamable_http_client(url + "/mcp/", http_client=http)) as mcp:
                listing = await mcp.list_tools()
                assert "orders.get" in {tool.name for tool in listing.tools}
                response = await mcp.call_tool("orders.get", {"order_id": order_id})
                assert not response.is_error
                result = response.structured_content
                if result is None:
                    result = json.loads(next(block.text for block in response.content if hasattr(block, "text")))
                assert result["id"] == order_id and result["status"] == "delivered"
                protocol = mcp.protocol_version

        conversation = await client.post(
            "/api/conversations", json={"customer_id": "cus_ava", "title": "Container approval smoke"}
        )
        conversation.raise_for_status()
        response = await client.post(
            "/api/messages",
            json={
                "conversation_id": conversation.json()["id"],
                "text": "Please refund my order",
                "order_id": order_id,
                "config": {"transport": "mcp"},
            },
        )
        response.raise_for_status()
        run_id = response.json()["run_id"]
        frames = []
        async with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
            stream.raise_for_status()
            async for line in stream.aiter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    frames.append(event)
                    if event["type"] in {"approval.required", "run.failed"}:
                        break
        assert any(event["type"] == "approval.required" for event in frames), [event["type"] for event in frames]
        detail = (await client.get(f"/api/runs/{run_id}")).json()
        assert detail["status"] == "waiting_approval", detail.get("error")
        proposal_id = detail["proposal_id"]
        assert (await client.get("/api/orders/" + order_id)).json()["status"] == "delivered"
        body = {
            "decision": "approve",
            "reason": "Scripted container QA review of fresh SIMULATED BUSINESS fixture",
            "idempotency_key": uuid4().hex,
        }
        denied = await client.post(
            f"/api/approvals/{proposal_id}/decision",
            json=body,
            headers={"Authorization": "Bearer demo-operator"},
        )
        assert denied.status_code == 403
        approval = await client.post(f"/api/approvals/{proposal_id}/decision", json=body)
        approval.raise_for_status()
        proposal = approval.json()
        assert proposal["status"] == "executed" and proposal["verification"]["verified"]
        assert all(proposal["verification"]["checks"].values())
        repeated = await client.post(f"/api/approvals/{proposal_id}/decision", json=body)
        repeated.raise_for_status()
        refunds = (await client.get("/api/refunds", params={"order_id": order_id})).json()["items"]
        assert len(refunds) == 1
        assert refunds[0]["amount_cents"] == proposal["parameters"]["amount_cents"]
        assert (await client.get("/api/orders/" + order_id)).json()["status"] == "refunded"
        detail = (await client.get(f"/api/runs/{run_id}")).json()
        assert detail["status"] == "completed"
    redis_ok = False
    try:
        redis_ok = redis.Redis.from_url(settings().redis_url, socket_timeout=2, socket_connect_timeout=2).ping()
    except redis.RedisError:
        if require_redis:
            raise
    if require_redis:
        assert redis_ok
    report = {
        "created_at": now().isoformat(),
        "provenance": "Actual TCP smoke / SIMULATED BUSINESS / FakeModelProvider / scripted review",
        "health": health_data,
        "mcp_protocol": protocol,
        "mcp_transport": "Streamable HTTP over actual TCP",
        "sse_events_observed": len(frames),
        "checks": {
            "authenticated_api": True,
            "mcp_order_fact": True,
            "sse_human_gate": True,
            "operator_approval_denied": True,
            "admin_approval_verified": True,
            "idempotent_refund_count": len(refunds),
            "approved_amount_matches": True,
            "redis_ping": redis_ok,
        },
        "run_id": run_id,
        "order_id": order_id,
        "proposal_id": proposal_id,
        "verification": proposal["verification"],
    }
    Path(output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"result": "passed", "run_id": run_id, "mcp_protocol": protocol, "redis": redis_ok}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8003")
    parser.add_argument("--output", default="/tmp/container-smoke.json")
    parser.add_argument("--require-redis", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.output, args.require_redis))
