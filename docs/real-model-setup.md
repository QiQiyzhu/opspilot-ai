# DeepSeek: real intent API with an explicit execution boundary

The supported primary setup is `deepseek` with base URL `https://api.deepseek.com` and model `deepseek-flash`. This follows the [official first-call guide](https://api-docs.deepseek.com/zh-cn/) checked on 2026-09-10. The provider sends Chat Completions JSON with `max_tokens`, `thinking: {"type": "disabled"}` and `response_format: {"type": "json_object"}`. It does not send Qwen's `enable_thinking` flag. Model names can change; the requested and returned IDs are recorded separately.

The paid model has one narrow responsibility: classify a support request into a validated intent. The existing BGE ONNX embedding model, retrieval, scoped tools, human approval transaction and independent database verification remain responsible for their own outcomes. A valid JSON refund intent cannot authorize a refund. The existing 60-task Fake-provider ablation and retrieval experiments retain their historical scope; they are not relabelled as DeepSeek measurements.

## Configure the server only

Use the existing Python 3.12 environment from the README. Keep API keys in the server process environment, never in Vite variables, frontend storage, Git, screenshots or report files. The checked-in `.env.example` contains no key and keeps `OPSPILOT_PROVIDER=fake`, so cloning or starting the project does not spend API credit.

PowerShell, from the repository root:

```powershell
$env:OPSPILOT_PROVIDER = 'deepseek'
$env:OPSPILOT_PROVIDER_URL = 'https://api.deepseek.com'
$env:OPSPILOT_PROVIDER_MODEL = 'deepseek-flash'
$env:OPSPILOT_PROVIDER_TIMEOUT = '30'
$env:OPSPILOT_PROVIDER_MAX_ATTEMPTS = '1'
$env:OPSPILOT_PROVIDER_MAX_OUTPUT_TOKENS = '512'
$env:OPSPILOT_PROVIDER_TOKEN_PARAMETER = 'max_tokens'
# Type the key into the local hidden prompt; it is not placed in command history.
$credential = Read-Host 'DeepSeek API key' -AsSecureString
$env:OPSPILOT_PROVIDER_KEY = [System.Net.NetworkCredential]::new('', $credential).Password
python -m evals.real_model_probe --output evals/reports/real-model-readiness.json
```

The readiness command makes **zero HTTP calls**. It reports missing fields, invalid HTTPS base URLs and configured budgets without echoing endpoint credentials. `configured=true` does not prove account access, balance, model availability or connectivity.

Explicitly make one potentially billable synthetic routing request:

```powershell
python -m evals.real_model_probe --execute --max-calls 1 --output evals/reports/deepseek-smoke.json
# Only after inspecting the first result, optionally run all six authored cases.
python -m evals.real_model_probe --execute --max-calls 6 --output evals/reports/deepseek-routing-six.json
```

The probe overrides retries to one HTTP attempt per case, stops at the first provider failure and never falls back to Fake. It sends only the six authored synthetic inputs in `evals/real_model_probe.py`; no database, customer records, tools, approvals or payments are involved. At most `max_calls × 512` generated tokens are requested with this configuration. Input tokens and provider billing rules still apply, and a timed-out request can be billable. The report records observed token usage and latency, but cost remains null without a tariff or invoice. Six easy routing cases are integration smoke, not a production model benchmark or an agent/RAG ablation.

## Use the real adapter in the application

In the same configured terminal, start `python -m uvicorn backend.app:app --host 127.0.0.1 --port 8003`. Restart an existing server after changing environment variables. Reconnect the console; Inbox initializes its provider from the server configuration. `Run settings → Provider → DeepSeek` also selects it explicitly per run. The backend's default for a run without a provider override follows `OPSPILOT_PROVIDER`; an explicit Fake run remains labelled Fake.

The application can create a reviewed action proposal against the simulated database, so inspect the intent and trace before approving. Independent verification, role checks, order ownership, policy rechecks, idempotency and atomic audit remain mandatory. The real-model probe above deliberately does not exercise those business effects. Existing transaction integration tests exercise them separately against simulated business records.

After the session, remove the process key:

```powershell
Remove-Item Env:OPSPILOT_PROVIDER_KEY
Remove-Variable credential
```

This clears this terminal's variables; it does not remove a variable inherited by an already-running child. Stop the local API when finished.

## Failure and evidence contracts

- At most 16,000 input characters, 128 KiB decoded response body, 512 default output tokens, and one total deadline including connection, body reading, retry and backoff. Settings have finite bounds.
- Only HTTP 429/502/503/504 or transport errors can retry, with at most two application attempts. The probe always uses one. Auth errors, invalid JSON, unexpected keys, refusals, tool calls and truncated output fail immediately.
- A 30-second circuit opens after three failed application calls. There is no schema-repair loop and no automatic model upgrade.
- Exactly `category`, `order_id` and `decision_summary` are accepted. Categories and order IDs are allowlisted; decision summaries are short public explanations, not private reasoning. No returned `reasoning_content` is read or stored.
- Redirects are disabled. HTTPS configuration rejects URL credentials, queries, fragments and a duplicated completion suffix. Error bodies, headers and URLs do not cross the trace boundary. Exact configured-key echoes are redacted even inside otherwise valid model JSON or identifiers.
- CI exercises authored transport fixtures and actual simulated transactions. A `MockTransport` response always reports `real_model_runs=0`. Only a successfully parsed response from an actual network call increments real-model runs; sending a request alone does not prove successful inference.

The cloud request discloses the submitted support message and system prompt to DeepSeek. Only owned synthetic fixtures should be used for the portfolio smoke. Real customer use requires a separate data-governance decision.

## Primary references

[First API call and current model names](https://api-docs.deepseek.com/zh-cn/) · [Chat Completions fields](https://api-docs.deepseek.com/api/create-chat-completion/) · [JSON mode and empty/truncated response caveats](https://api-docs.deepseek.com/guides/json_mode/) · [Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/).
