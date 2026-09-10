# Performance protocol

`python -m analytics.load_test` opens 10, 25 and 50 concurrent support sessions against the actual API and PostgreSQL. Each session reads an order, performs a bound SQL count, retrieves evidence through the API, creates a conversation/run and polls until terminal completion. It uses **FakeModelProvider**, not an online model. Raw per-session timings, errors, P50/P95/P99 and wall duration are in [performance.json](../evals/reports/performance.json).

The local measurement recorded zero session errors at all three concurrency levels. At 50 concurrent sessions, API P95 was 340.42ms, direct database-query phase P95 75.09ms, retrieval-request P95 1727.08ms, active run P95 3665.21ms, and client-observed end-to-end run phase P95 5682.41ms. Those scopes differ: client session timing includes request queueing and polling; the server duration starts when its run row is created. The database phase also includes Python thread scheduling and connection acquisition, not just PostgreSQL executor time.

Environment: one Windows developer host, PostgreSQL17.11/pgvector0.8.6, Python3.12.14, ONNX CPU embedding with two threads; another UE build may share machine resources. Document model/cache is warm, requests include distinct retrieval queries, and pool limits/one process constrain throughput. Run three rounds on an idle dedicated host before choosing a capacity target. This run is a reproducibility demonstration, not a statistically robust production benchmark.

Bottlenecks visible from the design are synchronous database work inside event emission, a single embedding lock to bound CPU inference, repeated event polling, and JSON trace growth. Improvements should start with measuring these components, batching event writes, task admission control and cache hit analysis. Add HNSW only once corpus scale makes exact distance a measured problem; introducing distributed workers needs durable leasing and shared rate limits first.

Real LLM latency, production QPS, external payment latency and Redis-backed multi-instance performance are **NOT RUN**. Fake tokens are null. Do not extrapolate this local 50-session test into a million-user claim.
