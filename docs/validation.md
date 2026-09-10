# Validation evidence

Local backend: **67 passed**, failures=0, errors=0, skipped=0, runtime 8.634s. [JUnit](../evals/reports/backend-junit.xml). One upstream Starlette/AnyIO deprecation warning was observed. Tests include actual PostgreSQL, ONNX, TCP MCP, SSE and transaction concurrency.

Frontend actual result: **7 unit tests passed; 8 browser scenarios passed, 0 skipped, 0 flaky**, runtime 53.86s. [Runner evidence](assets/frontend-validation.json) also records build/typecheck/lint success and npm audit 0. The continuous actual browser recording is 33.36s with 0 page errors, bound to run `c968d69b029641c9b9d635f0e411e564`. This is local Edge evidence, not a remote CI claim.

After the cancellation/ledger verifier fixes, the existing cancellation and refund/idempotency browser scenarios were rerun against the actual backend: **2 passed, 0 failed, 0 skipped**, in 41.41s. [Separate regression report](../evals/reports/browser-approval-regression.json). The earlier eight-scenario report, screenshots and continuous recording remain preserved; this narrower rerun is not presented as a new eight-scenario run. [Actual gate command results](../evals/reports/gate-validation.json) include an accepted full harness and an intentionally rejected 27/60 baseline.

RAG: 30 synthetic questions × 4 baselines; 36 rechunking/mode/top-K configurations × 30 questions. Agent: 60 synthetic tasks × 6 actual **FakeModelProvider harness** configurations. Full result 59/60; no real LLM provider was called. Human review pending. Four live API demos and one actual browser recording are saved with run IDs. No report claims real user research.

| Concurrent local Fake sessions | Errors | Client run P50 ms | P95 ms | P99 ms |
| --- | --- | --- | --- | --- |
| 10 | 0.0% | 635.7 | 952.8 | 966.0 |
| 25 | 0.0% | 2052.9 | 2254.9 | 2259.1 |
| 50 | 0.0% | 4297.0 | 5682.4 | 6237.4 |

85 total local simulated sessions; real LLM latency is NOT RUN. The values above come directly from the saved JSON.

Local environment: Python3.12.14; PostgreSQL17.11; pgvector0.8.6; real BGE-small English ONNX384. PostgreSQL binaries, database, venv, pip/model caches and process temporary files are on a dedicated data drive. Docker was unavailable during initial setup. OpsPilot Docker build and GitHub Actions status at initial delivery: **NOT RUN**. Do not write “CI passed” before an actual remote run is inspected.
