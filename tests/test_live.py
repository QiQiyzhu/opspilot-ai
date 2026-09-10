"""Run with OPSPILOT_LIVE_URL against a separately running API. Uses real TCP MCP/SSE."""

import asyncio
import json
import os
from uuid import uuid4
import pytest
import httpx
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

URL = os.environ.get("OPSPILOT_LIVE_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="Set OPSPILOT_LIVE_URL for actual network integration")


@pytest.mark.parametrize("token,expected", [("demo-operator", False), ("demo-viewer", True)])
async def test_mcp_real_transport_write_auth(token, expected):
    async with httpx2.AsyncClient(headers={"Authorization": "Bearer " + token}) as http:
        async with Client(streamable_http_client(URL + "/mcp/", http_client=http)) as client:
            listing = await client.list_tools()
            assert {t.name for t in listing.tools} >= {
                "orders.get",
                "customers.get",
                "knowledge.search",
                "tickets.get",
                "tickets.add_note",
            }
            result = await client.call_tool(
                "tickets.add_note",
                {"ticket_id": "tic_refund", "text": "MCP network integration note", "idempotency_key": uuid4().hex},
            )
            assert result.is_error is expected
            assert client.protocol_version


async def test_sse_replay_persisted_sequence_and_real_progress():
    async with httpx.AsyncClient(base_url=URL, headers={"Authorization": "Bearer demo-admin"}, timeout=30) as c:
        response = await c.post("/api/conversations", json={"customer_id": "cus_ava", "title": "Live SSE QA"})
        response.raise_for_status()
        conversation_id = response.json()["id"]
        response = await c.post(
            "/api/messages", json={"conversation_id": conversation_id, "text": "What is the refund policy?"}
        )
        response.raise_for_status()
        rid = response.json()["run_id"]
        events = []
        async with c.stream("GET", f"/api/runs/{rid}/events") as stream:
            async for line in stream.aiter_lines():
                if line.startswith("data: "):
                    events.append(json.loads(line[6:]))
        assert events[0]["type"] == "run.started" and events[-1]["type"] == "run.completed"
        assert any(e["type"] == "response.delta" for e in events)
        after = events[len(events) // 2]["sequence"]
        replay = await c.get(f"/api/runs/{rid}/events?after={after}")
        replayed = [json.loads(line[6:]) for line in replay.text.splitlines() if line.startswith("data: ")]
        assert all(e["sequence"] > after for e in replayed)
        assert replayed[-1]["type"] == "run.completed"


async def test_mcp_agent_matches_native_order_fact():
    async with httpx.AsyncClient(base_url=URL, headers={"Authorization": "Bearer demo-admin"}, timeout=30) as c:
        response = await c.post("/api/conversations", json={"customer_id": "cus_ava", "title": "MCP transport parity"})
        response.raise_for_status()
        response = await c.post(
            "/api/messages",
            json={
                "conversation_id": response.json()["id"],
                "text": "Check order status",
                "order_id": "ord_old",
                "config": {"transport": "mcp"},
            },
        )
        response.raise_for_status()
        rid = response.json()["run_id"]
        for _ in range(100):
            response = await c.get("/api/runs/" + rid)
            data = response.json()
            if data["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.05)
        assert data["status"] == "completed", data.get("error")
        assert any(t["transport"] == "mcp" for t in data["tool_calls"])
        assert "delivered" in data["response"]
