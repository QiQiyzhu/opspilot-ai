# Observed failures, not hypothetical success

| Case | Actual observation | Mitigation / remaining work |
| --- | --- | --- |
| Agent task agent_34: “My speaker needs charging help” | Fake keyword router misses the inflected word `charging`; full harness task assertion fails | preserve failed case; this is a deterministic-router limitation, not a real LLM result |
| No-answer RAG questions | hybrid rerank abstains correctly on only 1/4 no-answer cases in current development set | threshold calibration, broader negatives and human relevance review needed; never advertise universal answer accuracy |
| Hybrid vs rerank | hybrid has stronger Recall@3, lexical rerank improves MRR/top1 in this set | select K5 with documented tradeoff; no claim that reranking always wins |
| Multi-agent | same 59/60 Fake harness success as full single, additional provider coordination | retain single as default; real model utility untested |
| Initial retrieval timing | query cache made a later baseline artificially cheaper | final RAG comparisons clear query memoization for every case; agent comparisons also bypass retrieval cache |
| Concurrent approvals | replay can arrive after commit before original verification | retry explicitly verifies existing committed record; 12 concurrent calls produce one refund |
| Cancellation vs approval race found during review | an unlocked run-status check could race approval commit | repaired with shared run advisory lock and two controlled barrier tests that observe actual PostgreSQL lock waiters |
| Narrow verifier found during review | correct status alone could hide wrong refund cents or wrong reservation quantity | added approved amount/order matching and transaction-specific inventory journal checks; real DB mutation cases fail verification, later legitimate reservations remain valid |
| Database write failure injection | exception before commit rolls back ledger/order/audit | retry same key succeeds once; no partial update claimed |
| Provider timeout / circuit | two transient read attempts fail; repeated calls open circuit | no invented answer, trace failure and allow human handling |
| MCP unavailable / invalid schema | tool failure recorded with actual transport and error type | run fails; no false action confirmation |
| Redis unavailable | fallback is bounded local TTL cache | security/transactions remain in PostgreSQL; Redis multi-instance operation not locally measured |
| Worker restart | in-flight tasks cannot resume safely in current process worker | explicit failed state and replay; durable queue/lease is future work |

An adversarial vendor document is intentionally retained as test data. Pattern quarantine is a defense layer, not proof of complete injection prevention. Independently of model text, high-risk execution still requires authenticated server approval and valid policy/order state.

Failure rates in JSON come from scoped assertions on owned synthetic cases. Unsupported-claim detection currently focuses on operation-success phrases without verification. It does not measure nuanced unsupported factual claims. No raw report is relabeled as a human judgment.
