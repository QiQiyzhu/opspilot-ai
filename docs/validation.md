# Validation evidence

Local backend: **69 passed**, failures=0, errors=0, skipped=0, runtime 9.088s. [JUnit](../evals/reports/backend-junit.xml). One upstream Starlette/AnyIO deprecation warning was observed. Tests include actual PostgreSQL, ONNX, TCP MCP, SSE and transaction concurrency.

Frontend actual result: **7 unit tests passed; 8 browser scenarios passed, 0 skipped, 0 flaky**, runtime 53.86s. [Runner evidence](assets/frontend-validation.json) also records build/typecheck/lint success and npm audit 0. The continuous actual browser recording is 33.36s with 0 page errors, bound to run `c968d69b029641c9b9d635f0e411e564`. This is local Edge evidence, not a remote CI claim.

After the cancellation/ledger verifier fixes, the existing cancellation and refund/idempotency browser scenarios were rerun against the actual backend: **2 passed, 0 failed, 0 skipped**, in 41.41s. [Separate regression report](../evals/reports/browser-approval-regression.json). The earlier eight-scenario report, screenshots and continuous recording remain preserved; this narrower rerun is not presented as a new eight-scenario run. [Actual gate command results](../evals/reports/gate-validation.json) include an accepted full harness and an intentionally rejected 27/60 baseline.

RAG: 30 synthetic questions × 4 baselines; 36 rechunking/mode/top-K configurations × 30 questions. Agent: 60 synthetic tasks × 6 actual **FakeModelProvider harness** configurations. Full result 59/60; no real LLM provider was called. Human review pending. Four live API demos and one actual browser recording are saved with run IDs. No report claims real user research.

| Concurrent local Fake sessions | Errors | Client run P50 ms | P95 ms | P99 ms |
| --- | --- | --- | --- | --- |
| 10 | 0.0% | 635.7 | 952.8 | 966.0 |
| 25 | 0.0% | 2052.9 | 2254.9 | 2259.1 |
| 50 | 0.0% | 4297.0 | 5682.4 | 6237.4 |

85 total local simulated sessions; real LLM latency is NOT RUN. The values above come directly from the saved JSON.

Local environment: Python3.12.14; PostgreSQL17.11; pgvector0.8.6; real BGE-small English ONNX384. PostgreSQL binaries, database, venv, pip/model caches and process temporary files are on a dedicated data drive. Docker was unavailable during initial local setup. Remote verification is recorded separately below when actually executed.

## Recorded Linux CI and container runtime

The verified implementation snapshot completed successfully on **2026-09-10**: [GitHub Actions 34448358067](https://github.com/QiQiyzhu/opspilot-ai/actions/runs/34448358067), source commit [`5ae5267953a272c9a690fc9bb83a62df7a8beb60`](https://github.com/QiQiyzhu/opspilot-ai/commit/5ae5267953a272c9a690fc9bb83a62df7a8beb60), branch `codex/opspilot-v1`. Both jobs passed. Later documentation commits do not alter the source SHA tested by this snapshot; current runs remain visible in Actions history.

| Actual Linux check | Recorded result | Evidence |
| --- | --- | --- |
| Backend pytest against PostgreSQL and live API/MCP/SSE | 69 passed; 0 failed/errors/skipped; 4.761 seconds | [Downloaded JUnit](../evals/reports/linux-backend-junit.xml) |
| Frontend lint, 7 unit tests, typecheck, Vite production build | Passed; npm ci reported 0 vulnerabilities | [Quality job log](https://github.com/QiQiyzhu/opspilot-ai/actions/runs/34448358067/job/102778086478) |
| Chromium browser integration | 8 passed; 0 skipped/failed/flaky; 21.29 seconds | [Downloaded Playwright report](../evals/reports/linux-browser-results.json) |
| CI agent smoke — **FakeModelProvider rules harness** | 10/10 synthetic tasks; offline gate passed; not an LLM score | [CI smoke output](../evals/reports/linux-agent-smoke.json) |
| Compose runtime, beyond image build | Backend, PostgreSQL17.11/pgvector0.8.6 and Redis actually started; TCP smoke passed | [Container job](https://github.com/QiQiyzhu/opspilot-ai/actions/runs/34448358067/job/102778086246) |

The container smoke exercised authenticated API rejection, actual MCP Streamable HTTP with protocol `2026-07-28`, a real order read, **24 observed SSE events**, a human approval pause, rejected operator approval, approved admin execution and independent database verification. Replaying the same decision left **one simulated refund of 12,900 cents**, matching approved parameters and order association. Redis `PING` returned true. [Raw container observations](../evals/reports/container-smoke.json) and [actual image IDs](../evals/reports/container-images.json) were downloaded from the completed job; this is not a Dockerfile-only claim or a local Windows Docker claim.

The publication history preserves a genuine failure:

| Run | Exact source | Outcome |
| --- | --- | --- |
| [34447225959](https://github.com/QiQiyzhu/opspilot-ai/actions/runs/34447225959) | `9c1ce3318c4ed5dd59e509364156b280224436cb` | Initial implementation passed both jobs; [original metadata](../evals/reports/linux-ci-initial-run.json) |
| [34447822439](https://github.com/QiQiyzhu/opspilot-ai/actions/runs/34447822439) | `b7d1312bb061bef4280fd018c7b9a3b9527f8298` | Report-import commit: backend/container passed, one of eight browser cases failed |
| [34448358067](https://github.com/QiQiyzhu/opspilot-ai/actions/runs/34448358067) | `5ae5267953a272c9a690fc9bb83a62df7a8beb60` | Report-catalog fix: both jobs and all eight browser cases passed |

The failed report catalog assumed every JSON root was an object; Docker's image-list array caused HTTP500 and hid evaluation comparisons. The fix wraps arrays/scalars in a `data` envelope and reports individual malformed files without failing the catalog. Two new API regression tests cover actual shipped arrays and malformed/scalar files. [Failed job metadata](../evals/reports/linux-ci-failure.json) and [failed browser report](../evals/reports/linux-browser-failure.json) remain preserved. This was an application defect found by CI, not dismissed as a flaky test.

[Structured evidence summary](../evals/reports/ci-validation.json) and [raw successful run/job metadata](../evals/reports/linux-ci-run.json) bind current reports to the source commit. Only designated fresh CI outputs were imported. Existing source-bundled 60-task ablation, full retrieval experiments and load-test files retain their original local timestamps and are not presented as newly executed in CI.

Observed non-failing warnings: one upstream Starlette/AnyIO deprecation in pytest, and GitHub's action-runtime warning that older action revisions targeting Node20 were forced to Node24. The application frontend used Node22. All business data is simulated, all agent calls use the deterministic Fake provider, and this run provides no real LLM quality, cost or customer-impact evidence.
