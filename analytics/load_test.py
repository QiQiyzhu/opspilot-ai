"""Bounded local sessions. Tests real API/SQL/vector and fake-provider agent, never real LLM latency."""

import asyncio
import json
import time
import argparse
from pathlib import Path
import httpx
import numpy as np
from sqlalchemy import text
from backend.db import engine
from backend.models import now


def quantiles(values):
    return {f"p{p}_ms": float(np.percentile(values, p)) for p in [50, 95, 99]} if values else {}


async def benchmark(url, token):
    results = []
    for concurrent in [10, 25, 50]:
        async with httpx.AsyncClient(base_url=url, headers={"Authorization": "Bearer " + token}, timeout=60) as client:

            async def session(index):
                timings = {}
                try:
                    start = time.perf_counter()
                    response = await client.get("/orders/ord_old")
                    response.raise_for_status()
                    timings["api"] = (time.perf_counter() - start) * 1000
                    start = time.perf_counter()

                    def query():
                        with engine.connect() as conn:
                            return conn.scalar(
                                text("SELECT count(*) FROM orders WHERE customer_id=:id"), {"id": "cus_ava"}
                            )

                    await asyncio.to_thread(query)
                    timings["db"] = (time.perf_counter() - start) * 1000
                    start = time.perf_counter()
                    response = await client.post(
                        "/retrieval/search",
                        json={"query": f"refund eligibility after {index + 1} days", "mode": "hybrid"},
                    )
                    response.raise_for_status()
                    timings["retrieval"] = (time.perf_counter() - start) * 1000
                    c = await client.post(
                        "/conversations", json={"customer_id": "cus_ava", "title": f"LOAD TEST {concurrent}/{index}"}
                    )
                    c.raise_for_status()
                    start = time.perf_counter()
                    r = await client.post(
                        "/messages",
                        json={
                            "conversation_id": c.json()["id"],
                            "text": "What is the refund policy?",
                            "config": {"provider": "fake"},
                        },
                    )
                    r.raise_for_status()
                    rid = r.json()["run_id"]
                    for _ in range(300):
                        record = await client.get("/runs/" + rid)
                        record.raise_for_status()
                        data = record.json()
                        if data["status"] in {"completed", "failed", "cancelled"}:
                            break
                        await asyncio.sleep(0.05)
                    if data["status"] != "completed":
                        raise RuntimeError(data.get("error") or "run did not complete")
                    timings["agent_session"] = (time.perf_counter() - start) * 1000
                    timings["agent_active"] = data["duration_ms"]
                    return {"index": index, "success": True, "timings": timings}
                except Exception as exc:
                    return {"index": index, "success": False, "timings": timings, "error": str(exc)[:200]}

            start = time.perf_counter()
            sessions = await asyncio.gather(*(session(i) for i in range(concurrent)))
            duration = time.perf_counter() - start
            results.append(
                {
                    "concurrency": concurrent,
                    "sessions": len(sessions),
                    "wall_seconds": duration,
                    "error_rate": sum(not r["success"] for r in sessions) / len(sessions),
                    "latencies": {
                        metric: quantiles([r["timings"][metric] for r in sessions if metric in r["timings"]])
                        for metric in ["api", "db", "retrieval", "agent_session", "agent_active"]
                    },
                    "raw": sessions,
                }
            )
    report = {
        "created_at": now().isoformat(),
        "provenance": "LOCAL SIMULATED SESSIONS / FAKE PROVIDER",
        "results": results,
        "real_llm_latency": "NOT RUN",
        "limitations": "One process on developer Windows host, concurrent UE build may share CPU. Warm document model/cache, session polling overhead included. Not production QPS.",
    }
    path = Path(__file__).parents[1] / "evals" / "reports" / "performance.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps([{k: v for k, v in r.items() if k != "raw"} for r in results], indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://127.0.0.1:8003/api")
    p.add_argument("--token", default="demo-admin")
    args = p.parse_args()
    asyncio.run(benchmark(args.url, args.token))
