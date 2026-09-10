import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4
from urllib.parse import urlsplit
import httpx
from backend.config import Settings, settings

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
    """Structured intent only. A successful model response never authorizes a business action."""

    def __init__(self, config: Settings | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.config = config
        self.transport = transport
        self.failures = 0
        self.open_until = 0.0
        self.requests_started = 0

    def request_body(self, cfg, message, prompt):
        return {
            "model": cfg.provider_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            cfg.provider_token_parameter: cfg.provider_max_output_tokens,
            "response_format": {"type": "json_object"},
        }

    async def understand(self, message, prompt):
        cfg = self.config or settings()
        readiness = provider_readiness(cfg)
        if not readiness["configured"]:
            raise ValueError("Real provider is not configured: " + ", ".join(readiness["issues"]))
        if not isinstance(message, str) or not isinstance(prompt, str) or len(message) + len(prompt) > 16000:
            raise ValueError("Provider input exceeds the 16000 character limit or has an invalid type")
        if time.monotonic() < self.open_until:
            raise ProviderError("circuit_open")
        started = time.perf_counter()
        request_id = uuid4().hex
        schema_prompt = (
            prompt
            + "\nReturn JSON only: category (one of "
            + ",".join(sorted(CATEGORIES))
            + "), order_id (ord_ identifier or null), decision_summary (at most 500 characters, "
            + "short auditable decision, never private reasoning). Exactly these three keys. "
            + "Classify the request only; authorization, policy eligibility and execution belong to the server."
            + '\nExample JSON: {"category":"refund","order_id":"ord_example",'
            + '"decision_summary":"The customer requests a refund; eligibility is not determined."}'
        )
        attempts = 0
        try:
            # This deadline includes connection, response body, retry and backoff time.
            async with asyncio.timeout(cfg.provider_timeout):
                async with httpx.AsyncClient(
                    timeout=cfg.provider_timeout, transport=self.transport, follow_redirects=False
                ) as client:
                    for attempt in range(cfg.provider_max_attempts):
                        attempts += 1
                        self.requests_started += 1
                        try:
                            async with client.stream(
                                "POST",
                                cfg.provider_url.rstrip("/") + "/chat/completions",
                                headers={"Authorization": "Bearer " + cfg.provider_key, "X-Request-ID": request_id},
                                json=self.request_body(cfg, message, schema_prompt),
                            ) as response:
                                if response.status_code != 200:
                                    raise ProviderError(
                                        "http_error",
                                        status_code=response.status_code,
                                        retryable=response.status_code in {429, 502, 503, 504},
                                    )
                                payload = bytearray()
                                async for chunk in response.aiter_bytes():
                                    payload.extend(chunk)
                                    if len(payload) > 131072:
                                        raise ProviderError("response_too_large")
                            body = json.loads(payload)
                            data = parse_intent(body)
                            # Do not persist a credential even if a malicious provider echoes it in valid JSON.
                            data = {
                                key: value.replace(cfg.provider_key, "[REDACTED_KEY]")
                                if isinstance(value, str)
                                else value
                                for key, value in data.items()
                            }
                            self.failures = 0
                            return ModelResult(
                                data,
                                safe_identifier(body.get("model"), cfg.provider_model, cfg.provider_key),
                                (time.perf_counter() - started) * 1000,
                                safe_identifier(body.get("id"), request_id, cfg.provider_key),
                                tokens=parse_usage(body.get("usage")),
                                metadata={
                                    "synthetic_provider": False,
                                    "requested_model": cfg.provider_model,
                                    "attempts": attempts,
                                    "max_output_tokens": cfg.provider_max_output_tokens,
                                    "usage_scope": "last successful response only; failed attempts may be billable",
                                    "role": "structured intent; no business execution authority",
                                },
                            )
                        except httpx.TransportError:
                            failure = ProviderError("transport_error", retryable=True)
                        except ProviderError as exc:
                            failure = exc
                        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                            failure = ProviderError("invalid_response")
                        if attempt + 1 < cfg.provider_max_attempts and failure.retryable:
                            await asyncio.sleep(0.1)
                        else:
                            raise failure from None
        except TimeoutError:
            failure = ProviderError("deadline_exceeded", attempts=attempts)
        except ProviderError as exc:
            failure = exc
            failure.attempts = attempts
        self.failures += 1
        if self.failures >= 3:
            self.open_until = time.monotonic() + 30
        raise failure from None


class QwenProvider(OpenAICompatibleProvider):
    """Qwen non-thinking JSON intent, for a compatible model such as qwen-plus."""

    def request_body(self, cfg, message, prompt):
        body = super().request_body(cfg, message, prompt)
        body.pop(cfg.provider_token_parameter)
        body.update(max_tokens=cfg.provider_max_output_tokens, enable_thinking=False)
        return body


class DeepSeekProvider(OpenAICompatibleProvider):
    """DeepSeek JSON intent; explicitly disable thinking for this bounded routing task."""

    def request_body(self, cfg, message, prompt):
        body = super().request_body(cfg, message, prompt)
        body.pop(cfg.provider_token_parameter)
        body.update(max_tokens=cfg.provider_max_output_tokens, thinking={"type": "disabled"})
        return body


class ProviderError(RuntimeError):
    """Only fixed codes/status cross the trace boundary; HTTP bodies/URLs/headers never do."""

    def __init__(self, code, *, status_code=None, retryable=False, attempts=0):
        self.code = code
        self.status_code = status_code
        self.retryable = retryable
        self.attempts = attempts
        super().__init__("Model provider failed: " + code + (f" (HTTP {status_code})" if status_code else ""))


def provider_readiness(cfg=None):
    cfg = cfg or settings()
    issues = []
    for field_name in ("provider_key", "provider_url", "provider_model"):
        value = getattr(cfg, field_name)
        if not value.strip() or any(marker in value for marker in ("YOUR_", "{WorkspaceId}", "<")):
            issues.append("OPSPILOT_" + field_name.upper())
    try:
        url = urlsplit(cfg.provider_url)
        valid_url = (
            url.scheme == "https"
            and bool(url.hostname)
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and url.port in (None, 443)
            and not cfg.provider_url.endswith("/chat/completions")
        )
    except ValueError:
        valid_url = False
    if cfg.provider_url and not valid_url:
        issues.append("HTTPS_BASE_URL_WITHOUT_CREDENTIALS_QUERY_OR_COMPLETION_SUFFIX")
    if cfg.provider_model and not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", cfg.provider_model):
        issues.append("VALID_MODEL_ID")
    return {
        "configured": not issues,
        "issues": issues,
        "connectivity_verified": False,
        "max_output_tokens": cfg.provider_max_output_tokens,
        "timeout_seconds": cfg.provider_timeout,
        "max_attempts": cfg.provider_max_attempts,
        "scope": "local configuration check only; no network request",
    }


def safe_identifier(value, fallback, secret):
    return (
        value
        if isinstance(value, str) and secret not in value and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,160}", value)
        else fallback
    )


def parse_usage(usage):
    if not isinstance(usage, dict):
        return None

    def token(key):
        value = usage.get(key)
        return value if type(value) is int and value >= 0 else None

    return {"input": token("prompt_tokens"), "output": token("completion_tokens")}


def parse_intent(body):
    if not isinstance(body, dict):
        raise ProviderError("invalid_response")
    choice = body["choices"][0]
    message = choice["message"]
    if choice.get("finish_reason") != "stop" or message.get("refusal") or message.get("tool_calls"):
        raise ProviderError("incomplete_or_refused")
    data = json.loads(message["content"])
    if not isinstance(data, dict) or set(data) != {"category", "order_id", "decision_summary"}:
        raise ProviderError("invalid_intent_schema")
    order = data["order_id"]
    summary = data["decision_summary"]
    if (
        not isinstance(data["category"], str)
        or data["category"] not in CATEGORIES
        or (order is not None and (not isinstance(order, str) or not re.fullmatch(r"ord_[a-z0-9_]{1,76}", order)))
        or not isinstance(summary, str)
        or not summary.strip()
        or len(summary) > 500
    ):
        raise ProviderError("invalid_intent_schema")
    return data


PROVIDERS = {
    "fake": FakeModelProvider(),
    "openai-compatible": OpenAICompatibleProvider(),
    "qwen": QwenProvider(),
    "deepseek": DeepSeekProvider(),
}
