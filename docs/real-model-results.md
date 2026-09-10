# A real model passed JSON validation and still chose the wrong intent

On **2026-09-10 11:14 UTC**, DeepSeek `deepseek-flash` completed **6 real network calls** against six authored synthetic support messages. Five returned the expected category; one did not. **5/6 (83.33%) is a development routing smoke**, not a held-out benchmark, model comparison, RAG score or complete business-agent evaluation. [Unmodified raw report](../evals/reports/deepseek-smoke.json).

| Case | Expected category | Actual category | Outcome |
| --- | --- | --- | --- |
| refund | refund | refund | Match |
| tracking | order_query | order_query | Match |
| scope | out_of_scope | out_of_scope | Match |
| ambiguous | ambiguous | policy_conflict | Mismatch |
| troubleshooting | troubleshooting | troubleshooting | Match |
| replacement | replacement | replacement | Match |

The failing input was “Should I refund or replace ord_synthetic_probe?” The public decision summary described an ambiguous choice, but the category was `policy_conflict`. That category is allowed, so schema validation correctly accepted the response while the independent label check marked it wrong. We preserved the failure and did not change the prompt or relabel the expectation to manufacture 6/6.

The engineering lesson is to separate **transport success**, **schema validity**, **semantic correctness** and **business authorization**. All responses parsed. One category was wrong. No tools, approvals, database actions or payments were run by this probe, so it does not measure business success or prove the whole agent is safe. Existing transaction tests exercise those boundaries separately.

## Observed usage and scope

- Six HTTP attempts, one per case; six successfully parsed responses; zero retries and zero Fake calls.
- **1,108 input tokens, 247 output tokens**, as returned by the provider. Each call requested at most 512 output tokens with thinking disabled. Returned model IDs were `deepseek-flash`; no hidden provider snapshot is attested.
- Provider latency was **636.9–1,027.8 ms** across six serial requests on this developer connection. These are individual observations, not production P95 or throughput.
- Cost remains **null**: no billing statement or contemporaneous tariff was read. Token usage is not a payment receipt.
- All messages are authored synthetic NovaMart fixtures. There are **no real customer outcomes or research participants**.

The CLI defaults to a zero-call readiness check. `--execute` opts into paid requests, `--max-calls` is bounded to 1–6, and the probe stops at a failed provider response. [Reproduction and failure contracts](real-model-setup.md).

## Provenance

The report records parent commit `84f275b865631b88bddec5a9c9c5545c441816bb` with `source_worktree_dirty=true`: the adapter ran before its new commit. Normalized LF SHA-256 values identify the actual provider, config and probe bytes. The current provider and probe still match those hashes. After the run, the default MCP URL in `backend/config.py` gained a trailing slash to fix a separately observed local `/mcp` HTTP 405. The exact earlier config is preserved in [the source snapshot](../evals/reports/deepseek-source/config.py.txt), matching the report's config hash. The model probe does not use this URL.

The smoke is separate from [the 60-task Fake ablation](../evals/reports/agent-ablation.json), [real BGE retrieval](../evals/reports/rag-comparison.json) and [historical approval-boundary case](decision-case-study.md). None was relabelled as DeepSeek evidence.

## Next experiment before a quality claim

Freeze a reviewed distinction between `ambiguous` and `policy_conflict`, write new held-out paraphrases and adversarial mixed intents, then compare prompt versions on that frozen set. Keep these six development examples outside the final test set. Next run the real provider through the full agent with synthetic isolated orders, measuring category accuracy, appropriate abstention, proposal correctness and independent committed-state checks separately. Add budget and latency ceilings before scaling. A paid model is a replaceable interpretation component; authorization is a deterministic server contract.

## Interview explanation

“I connected DeepSeek after verifying the transaction system independently. The six-call smoke did not pass perfectly: it confused an unresolved choice with a policy conflict, despite valid JSON. I kept that failure because schema checks cannot replace semantic evaluation. The model interprets the request; the server owns authorization and money. Next comes a frozen taxonomy and held-out set, followed by the full agent path with independent database verification.”
