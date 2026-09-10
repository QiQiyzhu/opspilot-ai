## Recorded Linux CI and container runtime

The first publication run completed successfully on **2026-09-10**: [GitHub Actions 34447225959](https://github.com/QiQiyzhu/opspilot-ai/actions/runs/34447225959), source commit [`9c1ce3318c4ed5dd59e509364156b280224436cb`](https://github.com/QiQiyzhu/opspilot-ai/commit/9c1ce3318c4ed5dd59e509364156b280224436cb), branch `codex/opspilot-v1`. Both jobs passed. No failed run occurred in this publication attempt; there is no invented failure link. Later documentation commits do not change the source SHA covered by this evidence snapshot. Current runs remain visible in the repository's Actions history.

| Actual Linux check | Recorded result | Evidence |
| --- | --- | --- |
| Backend pytest against PostgreSQL and live API/MCP/SSE | 67 passed; 0 failed/errors/skipped; 4.687 seconds | [Downloaded JUnit](../evals/reports/linux-backend-junit.xml) |
| Frontend lint, 7 unit tests, typecheck, Vite production build | Passed; npm ci reported 0 vulnerabilities | [Quality job log](https://github.com/QiQiyzhu/opspilot-ai/actions/runs/34447225959/job/102774571251) |
| Chromium browser integration | 8 passed; 0 skipped/failed/flaky; 23.52 seconds | [Downloaded Playwright report](../evals/reports/linux-browser-results.json) |
| CI agent smoke — **FakeModelProvider rules harness** | 10/10 synthetic tasks; offline gate passed; not an LLM score | [CI smoke output](../evals/reports/linux-agent-smoke.json) |
| Compose runtime, beyond image build | Backend, PostgreSQL17.11/pgvector0.8.6 and Redis actually started; TCP smoke passed | [Container job](https://github.com/QiQiyzhu/opspilot-ai/actions/runs/34447225959/job/102774571048) |

The container smoke exercised authenticated API rejection, actual MCP Streamable HTTP with protocol `2026-07-28`, a real order read, **24 observed SSE events**, a human approval pause, rejected operator approval, approved admin execution and independent database verification. Replaying the same decision left **one simulated refund of 12,900 cents**, matching approved parameters and order association. Redis `PING` returned true. [Raw container observations](../evals/reports/container-smoke.json) and [actual image IDs](../evals/reports/container-images.json) were downloaded from the completed job; this is not a Dockerfile-only claim or a local Windows Docker claim.

[Structured evidence summary](../evals/reports/ci-validation.json) and [raw run/job metadata](../evals/reports/linux-ci-run.json) bind these reports to the source commit. Only designated fresh CI outputs were imported. Existing source-bundled 60-task ablation, full retrieval experiments and load-test files retain their original local timestamps and are not presented as newly executed in CI.

Observed non-failing warnings: one upstream Starlette/AnyIO deprecation in pytest, and GitHub's action-runtime warning that older action revisions targeting Node20 were forced to Node24. The application frontend used Node22. All business data is simulated, all agent calls use the deterministic Fake provider, and this run provides no real LLM quality, cost or customer-impact evidence.
