# Product upgrade: the next step matters more than valid JSON

## Research and scope, 2026-09-10

The [NeurIPS 2026 competition reviewer guidance](https://neurips.cc/Conferences/2026/CompetitionReviewerGuidelines) asks for clear success criteria, credible baselines, leakage safeguards, appropriate resources and agent-action risks. We use this as an evaluation design standard; this repository is not claiming an accepted entry or meeting a specific current submission deadline.

The [original τ-bench repository](https://github.com/sierra-research/tau-bench) evaluates conversations with tools and domain policy, and now points users to its newer successor for corrected tasks. We borrow the distinction between language output and operational result, not its datasets or leaderboard score. The [Ragas context precision definition](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_precision/) measures relevant evidence ordering; it is not an authorization or intent-quality metric.

The observed DeepSeek failure chose `policy_conflict` for a customer's unresolved refund/replacement choice. The existing agent only handled `ambiguous` explicitly; `policy_conflict` fell through to policy excerpts. A staff user therefore had no clear next action even though the model returned valid JSON. This upgrade gives unresolved goals and policy conflicts explicit, distinct next steps. Existing refund authorization remains independent.

## Freeze before inference

`evals/datasets/intent-contract-v1.json` contains eight development cases and sixteen new prospective test cases, including negation, missing order identifiers, policy questions, contradictory guidance, partial refunds and simultaneous incompatible remedies. It is AI-authored synthetic data and has not received independent human label review. Its author sees the test cases, so "test" does not mean a blinded independent benchmark. Cases and label definitions are frozen before the candidate prompt and paid calls; SHA-256 and a separate dataset commit bind the experiment.

Compare the existing general system prompt against the same prompt plus a versioned taxonomy. Evaluate exact category and the deterministic next-step disposition separately. Score missed clarification/review and unnecessary clarification separately from ordinary accuracy; a valid JSON response is not semantic success. No model judge can silently change the expected labels. Preserve every returned response, usage, latency and failed contract. Frozen test results will not be used to retune this version.

This round does not claim to fix the preserved RAG ranking regression (`rag_02`, hybrid rank 1 versus lexical rerank rank 4) or its weak no-answer behavior. Those require a separately frozen retrieval experiment.
