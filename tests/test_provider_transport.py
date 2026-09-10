"""Transport contracts: actual HTTP parser/retry logic with authored bytes, zero cloud-model claims."""

import asyncio
import json

import httpx
import pytest

from backend.config import Settings
from backend.providers import DeepSeekProvider, OpenAICompatibleProvider, QwenProvider, ProviderError, provider_readiness
from evals.real_model_probe import run_probe

KEY = "transport-only-private-credential"
INTENT = {"category": "refund", "order_id": "ord_synthetic_probe", "decision_summary": "Requested a refund."}


def config(**updates):
    return Settings(
        _env_file=None,
        provider="qwen",
        provider_url="https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        provider_key=KEY,
        provider_model="qwen-plus",
        **updates,
    )


def response(*, intent=None, **updates):
    return {
        "id": "chatcmpl-transport-1",
        "model": "qwen-plus-snapshot",
        "choices": [
            {"finish_reason": "stop", "message": {"content": json.dumps(INTENT if intent is None else intent)}}
        ],
        "usage": {"prompt_tokens": 91, "completion_tokens": 27},
        **updates,
    }


async def test_qwen_request_bounds_and_actual_usage_are_preserved():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=response())

    result = await QwenProvider(config(), httpx.MockTransport(handle)).understand("Please refund", "Route support")
    payload = json.loads(requests[0].content)
    assert payload["enable_thinking"] is False and payload["max_tokens"] == 512
    assert "max_completion_tokens" not in payload and "temperature" not in payload
    assert "tools" not in payload and "JSON" in payload["messages"][0]["content"]
    assert requests[0].headers["Authorization"] == "Bearer " + KEY
    assert str(requests[0].url).endswith("/compatible-mode/v1/chat/completions")
    assert result.model == "qwen-plus-snapshot" and result.request_id == "chatcmpl-transport-1"
    assert result.tokens == {"input": 91, "output": 27} and result.cost is None


async def test_generic_adapter_does_not_send_qwen_flags_or_assume_temperature_support():
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response(usage={"prompt_tokens": True, "completion_tokens": -2}))

    result = await OpenAICompatibleProvider(config(), httpx.MockTransport(handle)).understand("Hello", "Route")
    assert seen[0]["max_completion_tokens"] == 512
    assert not {"enable_thinking", "temperature", "max_tokens"}.intersection(seen[0])
    assert result.tokens == {"input": None, "output": None}


async def test_deepseek_uses_its_own_budget_and_non_thinking_schema():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=response(model="deepseek-flash"))

    cfg = config().model_copy(update={
        "provider": "deepseek", "provider_url": "https://api.deepseek.com", "provider_model": "deepseek-flash",
    })
    result = await DeepSeekProvider(cfg, httpx.MockTransport(handle)).understand("Please refund", "Route support")
    body = json.loads(calls[0].content)
    assert str(calls[0].url) == "https://api.deepseek.com/chat/completions"
    assert body["model"] == result.model == "deepseek-flash"
    assert body["thinking"] == {"type": "disabled"} and body["max_tokens"] == 512
    assert not {"enable_thinking", "max_completion_tokens", "tools"}.intersection(body)
    assert body["response_format"] == {"type": "json_object"}
    assert "Example JSON" in body["messages"][0]["content"]


async def test_provider_never_returns_a_secret_echo_in_valid_json_or_identifiers():
    body = response(intent={**INTENT, "decision_summary": "echo " + KEY}, model="echo-" + KEY, id="echo-" + KEY)
    result = await DeepSeekProvider(config(), httpx.MockTransport(lambda r: httpx.Response(200, json=body))).understand("x", "y")
    assert KEY not in result.data["decision_summary"] and "REDACTED" in result.data["decision_summary"]
    assert KEY not in result.model and KEY not in result.request_id


async def test_missing_configuration_and_url_secrets_never_reach_transport():
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(r))
    invalid = [
        config().model_copy(update={"provider_key": ""}),
        config().model_copy(update={"provider_model": ""}),
        config().model_copy(update={"provider_url": "http://example.test/v1"}),
        config().model_copy(update={"provider_url": "https://key:secret@example.test/v1"}),
        config().model_copy(update={"provider_url": "https://example.test/v1?key=private"}),
        config().model_copy(update={"provider_url": "https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/v1"}),
    ]
    for cfg in invalid:
        assert provider_readiness(cfg)["configured"] is False
        assert KEY not in json.dumps(provider_readiness(cfg)) and KEY not in repr(cfg)
        with pytest.raises(ValueError, match="not configured"):
            await QwenProvider(cfg, transport).understand("x", "y")
    assert calls == []


async def test_valid_json_is_insufficient_for_schema_and_finish_boundary():
    bad = [
        response(intent=[]),
        response(intent={**INTENT, "execute_refund": True}),
        response(intent={**INTENT, "order_id": 12}),
        response(intent={**INTENT, "category": "execute"}),
        response(intent={**INTENT, "decision_summary": "x" * 501}),
        response(choices=[{"finish_reason": "length", "message": {"content": json.dumps(INTENT)}}]),
        response(choices=[{"finish_reason": "stop", "message": {"content": json.dumps(INTENT), "refusal": "no"}}]),
        response(choices=[{"finish_reason": "stop", "message": {"content": json.dumps(INTENT), "tool_calls": [{}]}}]),
        response(choices=[[]]),
        response(choices=[]),
    ]
    for body in bad:
        provider = QwenProvider(config(), httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
        with pytest.raises(ProviderError):
            await provider.understand("x", "y")
        assert provider.requests_started == 1  # no costly schema-repair loop


async def test_transient_retry_is_bounded_but_auth_error_body_never_escapes():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(503, text=KEY) if len(calls) == 1 else httpx.Response(200, json=response())

    result = await QwenProvider(config(), httpx.MockTransport(handle)).understand("x", "y")
    assert len(calls) == 2 and result.metadata["attempts"] == 2
    provider = QwenProvider(config(), httpx.MockTransport(lambda r: httpx.Response(401, text=KEY)))
    with pytest.raises(ProviderError) as error:
        await provider.understand("x", "y")
    assert provider.requests_started == 1 and error.value.status_code == 401
    assert KEY not in str(error.value) and KEY not in repr(error.value)
    assert error.value.__cause__ is None and error.value.__suppress_context__


async def test_redirect_is_not_followed_and_oversized_response_is_rejected():
    calls = []

    def redirect(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://other-host.test/steal"})

    provider = QwenProvider(config(), httpx.MockTransport(redirect))
    with pytest.raises(ProviderError, match="http_error"):
        await provider.understand("x", "y")
    assert len(calls) == 1
    provider = QwenProvider(config(), httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 131073)))
    with pytest.raises(ProviderError, match="response_too_large"):
        await provider.understand("x", "y")


async def test_total_deadline_and_circuit_do_not_claim_transport_success():
    async def delayed(request):
        await asyncio.sleep(0.2)
        return httpx.Response(200, json=response())

    cfg = config().model_copy(update={"provider_timeout": 0.01})
    provider = QwenProvider(cfg, httpx.MockTransport(delayed))
    for _ in range(3):
        with pytest.raises(ProviderError, match="deadline_exceeded"):
            await provider.understand("x", "y")
    assert provider.requests_started == 3
    with pytest.raises(ProviderError, match="circuit_open"):
        await provider.understand("x", "y")
    assert provider.requests_started == 3


async def test_probe_requires_opt_in_and_records_real_tokens_without_faking_model_runs():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(200, json=response(intent={**INTENT, "decision_summary": KEY}))

    transport = httpx.MockTransport(handle)
    ready = await run_probe(config=config(), transport=transport)
    assert ready["status"] == "ready" and ready["http_attempts"] == 0 and calls == []
    report = await run_probe(execute=True, config=config(), transport=transport)
    assert len(calls) == report["http_attempts"] == report["successful_model_responses"] == 1
    assert report["real_model_runs"] == 0 and "fixture" in report["evidence_type"]
    assert report["rows"][0]["result"]["tokens"] == {"input": 91, "output": 27}
    assert report["max_output_tokens_per_attempt"] == 512 and report["business_effects"] == 0
    assert KEY not in json.dumps(report) and report["routing_accuracy"] == 1

    ds_cfg = config().model_copy(update={"provider": "deepseek", "provider_model": "deepseek-flash"})
    ds_report = await run_probe(execute=True, config=ds_cfg, transport=transport)
    assert ds_report["successful_model_responses"] == 1 and ds_report["real_model_runs"] == 0
    assert json.loads(calls[-1].content)["thinking"] == {"type": "disabled"}


async def test_probe_fails_fast_without_retry_or_fake_fallback():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(429, text=KEY)

    report = await run_probe(execute=True, max_calls=6, config=config(), transport=httpx.MockTransport(handle))
    assert len(calls) == report["http_attempts"] == 1 and report["status"] == "failed"
    assert report["successful_model_responses"] == report["real_model_runs"] == 0
    assert report["rows"][0]["error"]["http_status"] == 429 and KEY not in json.dumps(report)
    with pytest.raises(ValueError):
        await run_probe(execute=True, max_calls=7, config=config())


def test_application_default_uses_server_selection_but_explicit_fake_is_preserved(monkeypatch):
    from backend import agent
    from backend.db import session_scope
    from backend.models import Conversation

    monkeypatch.setattr(agent.settings(), "provider", "deepseek")
    with session_scope() as session:
        conversation = Conversation(customer_id="cus_ava", title="Provider selection contract")
        session.add(conversation)
        session.flush()
        conversation_id = conversation.id
    default_id = agent.create_run(conversation_id, "Synthetic request")
    fake_id = agent.create_run(conversation_id, "Synthetic request", config={"provider": "fake"})
    assert agent.run_detail(default_id)["config"]["provider"] == "deepseek"
    assert agent.run_detail(fake_id)["config"]["provider"] == "fake"
    # Creating/snapshotting a run performs no model call; execution is a separate action.
    assert agent.run_detail(default_id)["tool_calls"] == []
