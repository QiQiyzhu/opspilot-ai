import asyncio
import time
import pytest
import httpx
from fastapi import HTTPException
from backend import agent, registry
from backend.config import settings
from backend.models import EvaluationRun, Conversation
from backend.db import session_scope
from backend.security import Principal
from backend.providers import OpenAICompatibleProvider

OP = Principal("reliability-op", "Test operator", "operator")


async def run_input(config):
    with session_scope() as s:
        c = Conversation(customer_id="cus_ava", title="Automated scenario reliability")
        s.add(c)
        s.flush()
        cid = c.id
    rid = agent.create_run(cid, "What is the refund policy?", config=config)
    await agent.execute(rid, OP)
    return agent.run_detail(rid)


async def test_real_provider_timeout_retry_and_circuit(monkeypatch):
    cfg = settings()
    monkeypatch.setattr(cfg, "provider_key", "local-test-key")
    monkeypatch.setattr(cfg, "provider_url", "https://provider.invalid/v1")
    monkeypatch.setattr(cfg, "provider_model", "test-model")
    calls = []

    def fail(request):
        calls.append(request)
        raise httpx.ReadTimeout("Injected provider timeout", request=request)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(fail), **kwargs))
    provider = OpenAICompatibleProvider()
    for _ in range(3):
        with pytest.raises(httpx.ReadTimeout):
            await provider.understand("refund", "Support")
    with pytest.raises(RuntimeError, match="circuit"):
        await provider.understand("refund", "Support")
    assert len(calls) == 6


async def test_embedding_timeout_safe_failure(monkeypatch):
    monkeypatch.setattr(settings(), "retrieval_timeout", 0.001)

    def slow(*args):
        time.sleep(0.04)
        return {"results": []}

    monkeypatch.setattr(agent, "cached_search", slow)
    run = await run_input({})
    assert run["status"] == "failed" and "TimeoutError" in run["error"] and not run["response"]


async def test_mcp_unavailable_is_observed_failure(monkeypatch):
    monkeypatch.setattr(settings(), "mcp_url", "http://127.0.0.1:1/mcp/")
    run = await run_input({"transport": "mcp"})
    assert run["status"] == "failed"
    assert any(t["transport"] == "mcp" and t["status"] == "error" for t in run["tool_calls"])


async def test_running_cancellation_persists_terminal_state(monkeypatch):
    async def slow(*args):
        await asyncio.sleep(10)

    monkeypatch.setattr(agent.PROVIDERS["fake"], "understand", slow)
    with session_scope() as s:
        c = Conversation(customer_id="cus_ava", title="Automated scenario cancel")
        s.add(c)
        s.flush()
        cid = c.id
    rid = agent.create_run(cid, "help")
    task = asyncio.create_task(agent.execute(rid, OP))
    await asyncio.sleep(0.05)
    task.cancel()
    await task
    detail = agent.run_detail(rid)
    assert detail["status"] == "cancelled"
    assert detail["trace"][-1]["type"] == "run.cancelled"


def test_prompt_gate_rejects_report_below_threshold():
    with session_scope() as s:
        row = EvaluationRun(
            kind="agent",
            dataset_id="unit-gate-fixture",
            provider="fake",
            status="completed",
            metrics={"task_success_rate": 0.5, "unsafe_action_rate": 0},
            results=[],
            config={"prompt_version": 2},
        )
        s.add(row)
        s.flush()
        report_id = row.id
    with pytest.raises(HTTPException) as e:
        registry.release("support-system", 2, report_id)
    assert e.value.status_code == 409 and e.value.detail["gate"] == "failed"
