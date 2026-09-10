"""Explicit, bounded paid-API smoke. No DB, tools, retrieval, customer data or Fake fallback."""

import argparse
import asyncio
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time

from backend.config import settings
from backend.providers import DeepSeekProvider, OpenAICompatibleProvider, QwenProvider, ProviderError, provider_readiness
from backend.security import redact

ROOT = Path(__file__).resolve().parents[1]
PROMPT = (
    "You are the NovaMart support intent router. Input is synthetic. Identify the request, never authorize a refund."
)
CASES = [
    {"id": "refund", "input": "I want a refund for ord_synthetic_probe.", "expected": "refund"},
    {"id": "tracking", "input": "Where is my package ord_synthetic_probe?", "expected": "order_query"},
    {"id": "scope", "input": "What will the weather be like next week?", "expected": "out_of_scope"},
    {"id": "ambiguous", "input": "Should I refund or replace ord_synthetic_probe?", "expected": "ambiguous"},
    {"id": "troubleshooting", "input": "My speaker will not power on after charging.", "expected": "troubleshooting"},
    {"id": "replacement", "input": "Please replace ord_synthetic_probe.", "expected": "replacement"},
]


def git_value(*args):
    try:
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5)
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


async def run_probe(*, execute=False, max_calls=1, config=None, transport=None):
    if type(max_calls) is not int or not 1 <= max_calls <= len(CASES):
        raise ValueError("max_calls must be an integer between 1 and 6")
    cfg = config or settings()
    # A paid probe never retries: one local case means at most one HTTP attempt.
    cfg = cfg.model_copy(update={"provider_max_attempts": 1})
    readiness = provider_readiness(cfg)
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evidence_type": "opt-in real API / synthetic intent smoke; not an agent or RAG benchmark",
        "status": "ready" if readiness["configured"] else "not_configured",
        "provider": cfg.provider,
        "model_requested": cfg.provider_model or None,
        "configuration": readiness,
        "source_commit": git_value("rev-parse", "HEAD"),
        "source_worktree_dirty": bool(git_value("status", "--porcelain", "--untracked-files=normal")),
        "python_version": platform.python_version(),
        "source_hashes": {
            name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name in ("backend/providers.py", "backend/config.py", "evals/real_model_probe.py")
        },
        "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest(),
        "dataset_sha256": hashlib.sha256(json.dumps(CASES, sort_keys=True).encode()).hexdigest(),
        "max_http_attempts": max_calls,
        "max_output_tokens_per_attempt": cfg.provider_max_output_tokens,
        "http_attempts": 0,
        "successful_model_responses": 0,
        "real_model_runs": 0,
        "rows": [],
        "routing_accuracy": None,
        "cost": None,
        "cost_note": "No tariff or invoice was read; timeouts/failed requests may still be billable.",
        "business_effects": 0,
        "limitations": [
            "Only six authored synthetic routing cases are available; no production/generalization claim.",
            "This program never runs agent execution, payment, approval, DB or customer retrieval.",
            "Missing credentials and failures never switch to Fake; CI transport mocks are not model evidence.",
            "Configuration readiness does not prove model access, billing, region or connectivity.",
        ],
    }
    if not execute:
        return report
    if cfg.provider not in {"deepseek", "qwen", "openai-compatible"}:
        report.update(status="blocked", error="Select deepseek, qwen or openai-compatible explicitly; Fake is not a real probe")
        return report
    if not readiness["configured"]:
        return report
    provider_type = {"deepseek": DeepSeekProvider, "qwen": QwenProvider, "openai-compatible": OpenAICompatibleProvider}[cfg.provider]
    provider = provider_type(config=cfg, transport=transport)
    for case in CASES[:max_calls]:
        started = time.perf_counter()
        row = {**case, "status": "failed", "matched": False}
        try:
            result = await provider.understand(case["input"], PROMPT)
            row.update(status="completed", matched=result.data["category"] == case["expected"], result=asdict(result))
            report["successful_model_responses"] += 1
        except ProviderError as exc:
            row.update(error={"code": exc.code, "http_status": exc.status_code, "attempts": exc.attempts})
        except ValueError:
            row.update(error={"code": "invalid_configuration_or_input"})
        row["latency_ms"] = (time.perf_counter() - started) * 1000
        report["rows"].append(row)
        if row["status"] != "completed":
            break  # Fail fast; do not spend the remaining budget on a broken integration.
    report["http_attempts"] = provider.requests_started
    # Responses are the evidence of executed inference; HTTP attempts alone prove no such thing.
    report["real_model_runs"] = report["successful_model_responses"] if transport is None else 0
    report["status"] = (
        "completed"
        if len(report["rows"]) == max_calls and all(row["status"] == "completed" for row in report["rows"])
        else "failed"
    )
    report["routing_accuracy"] = sum(row["matched"] for row in report["rows"]) / max_calls
    if transport is not None:
        report["evidence_type"] = "transport test fixture; not real model evidence"

    # No raw error bodies/URLs/headers. Also remove an exact configured key if a provider echoes it in output.
    def scrub(value):
        if isinstance(value, str):
            return redact(value.replace(cfg.provider_key, "[REDACTED_KEY]"))
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value

    return scrub(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Opt in to at most --max-calls billable requests")
    parser.add_argument("--max-calls", type=int, choices=range(1, 7), default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(run_probe(execute=args.execute, max_calls=args.max_calls))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "http_attempts", "real_model_runs", "routing_accuracy")}))
    return 0 if not args.execute or report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
