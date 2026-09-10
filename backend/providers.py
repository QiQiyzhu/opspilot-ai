import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4
import httpx
from backend.config import settings

CATEGORIES = {
    "knowledge_qa",
    "order_query",
    "refund",
    "replacement",
    "cancellation",
    "troubleshooting",
    "ambiguous",
    "out_of_scope",
    "missing_information",
    "policy_conflict",
}


@dataclass
class ModelResult:
    data: dict
    model: str
    latency_ms: float
    request_id: str
    tokens: dict | None = None
    error: str | None = None
    cost: float | None = None
    metadata: dict = field(default_factory=dict)


class ModelProvider(Protocol):
    async def understand(self, message: str, prompt: str) -> ModelResult: ...


def classify(message):
    text = message.lower()
    category = "ambiguous"
    terms = [
        (
            "out_of_scope",
            ["weather", "股票", "天气", "write code", "recipe", "politic", "bitcoin", "another customer", "别人的"],
        ),
        ("replacement", ["replace", "换货", "换一个"]),
        ("refund", ["refund", "退款", "money back", "get my money"]),
        ("cancellation", ["cancel", "取消"]),
        (
            "troubleshooting",
            ["bluetooth", "power", "charge", "won't turn", "故障", "开机", "冒烟", "smoking", "overheat"],
        ),
        ("order_query", ["tracking", "where is", "什么时候到", "发货", "shipment", "order status", "package"]),
        (
            "knowledge_qa",
            [
                "policy",
                "coupon",
                "优惠券",
                "membership",
                "会员",
                "gold",
                "warranty",
                "保修",
                "return",
                "shipping",
                "规则",
            ],
        ),
    ]
    for label, words in terms:
        if any(word in text for word in words):
            category = label
            break
    if (
        ("refund" in text or "退款" in text)
        and ("replace" in text or "换货" in text)
        and any(v in text for v in ["or", "还是", "either"])
    ):
        category = "ambiguous"
    if "policy" in text and not any(v in text for v in ["my order", "ord_", "refund me"]):
        category = "knowledge_qa"
    matches = re.findall(r"\bord_[a-z0-9_]+\b", text)
    return {
        "category": category,
        "order_id": matches[0] if matches else None,
        "decision_summary": f"Request routed to {category}; authorization remains a server responsibility",
    }


class FakeModelProvider:
    """Deterministic fixture router, explicitly not a language model."""

    async def understand(self, message, prompt):
        started = time.perf_counter()
        await asyncio.sleep(0)
        return ModelResult(
            classify(message),
            "fake-rules-v1",
            (time.perf_counter() - started) * 1000,
            uuid4().hex,
            metadata={"synthetic_provider": True, "prompt_effect": "recorded but not semantically interpreted"},
        )


class OpenAICompatibleProvider:
    def __init__(self):
        self.failures = 0
        self.open_until = 0.0

    async def understand(self, message, prompt):
        cfg = settings()
        if not cfg.provider_key or not cfg.provider_url or not cfg.provider_model:
            raise ValueError("Real provider is not configured; no paid call was attempted")
        if time.monotonic() < self.open_until:
            raise RuntimeError("Provider circuit is open after consecutive failures")
        started = time.perf_counter()
        request_id = uuid4().hex
        schema_prompt = (
            prompt
            + "\nReturn JSON only: category (one of "
            + ",".join(sorted(CATEGORIES))
            + "), order_id (string or null), decision_summary (short auditable decision, never private reasoning)."
        )
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=cfg.provider_timeout) as client:
                    response = await client.post(
                        cfg.provider_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": "Bearer " + cfg.provider_key, "X-Request-ID": request_id},
                        json={
                            "model": cfg.provider_model,
                            "messages": [
                                {"role": "system", "content": schema_prompt},
                                {"role": "user", "content": message},
                            ],
                            "temperature": 0,
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()
                    body = response.json()
                data = json.loads(body["choices"][0]["message"]["content"])
                if data.get("category") not in CATEGORIES:
                    raise ValueError("Provider returned invalid intent schema")
                self.failures = 0
                usage = body.get("usage")
                return ModelResult(
                    data,
                    cfg.provider_model,
                    (time.perf_counter() - started) * 1000,
                    body.get("id", request_id),
                    tokens={"input": usage.get("prompt_tokens"), "output": usage.get("completion_tokens")}
                    if usage
                    else None,
                )
            except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                retryable = isinstance(exc, httpx.TimeoutException) or exc.response.status_code in {429, 502, 503, 504}
                if attempt == 0 and retryable:
                    await asyncio.sleep(0.1)
                    continue
                self.failures += 1
                if self.failures >= 3:
                    self.open_until = time.monotonic() + 30
                raise


class QwenProvider(OpenAICompatibleProvider):
    """Uses Qwen's configured OpenAI-compatible endpoint; model/key supplied by the operator."""


PROVIDERS = {"fake": FakeModelProvider(), "openai-compatible": OpenAICompatibleProvider(), "qwen": QwenProvider()}
