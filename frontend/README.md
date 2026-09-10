# OpsPilot operations console

The console reads the real local backend on port 8003. NovaMart is **SIMULATED BUSINESS**. The default deterministic provider is not an LLM. There are no invented dashboard metrics or client-side approval bypasses.

```powershell
npm ci
npm run dev
```

Open http://127.0.0.1:5176 and enter the locally configured access token. Tokens stay in sessionStorage; identity and permissions are returned by the server. The Vite proxy preserves `/api`.

```powershell
npm run typecheck
npm run lint
npm run test
npm run build
```

For actual browser tests, start a seeded backend first. Create a fresh refundable order from the project root with its Python environment: `python -m backend.demo_fixture`. This creates one new simulated order and does not reset existing data. Pass that ID to the browser tests:

```powershell
$env:OPSPILOT_E2E_TOKEN = '<local-admin-token>'
$env:OPSPILOT_E2E_VIEWER_TOKEN = '<local-viewer-token>'
$env:OPSPILOT_E2E_REFUND_ORDER = '<fresh-order-id>'
npm run test:e2e
```

The refund case executes one simulated refund, then replays the same decision and checks that exactly one ledger entry exists. Other cases cover MCP policy QA, persisted conversations, replacement rejection, late approval after cancellation, viewer denial, real retrieval, version diff, actual evaluation and mobile layout. Credentials and the fresh order ID come from environment variables. Tests explicitly skip missing required local credentials/fixtures; CI should configure them.

To produce a continuous actual browser recording, provision another fresh order and run:

```powershell
$env:OPSPILOT_RECORD_ORDER = '<another-fresh-order-id>'
node record-demo.mjs
```

This also approves one simulated refund. Output is `docs/assets/demo.webm` with the corresponding real run and approval JSON. Playwright must have its ffmpeg recording dependency available. The test configuration uses an existing Edge installation locally and selects installed Chromium automatically when `CI` is set. On a machine with a nearly full system disk, set process-local TEMP/TMP and OPSPILOT_RECORD_DIR to a dedicated data drive before starting Playwright.

Frontend architecture: `api.ts` handles authenticated REST and streaming frame boundaries; `Inbox.tsx` observes live runs with cursor deduplication and stale-run guards; `Approval.tsx` sends only the decision, reason and idempotency key; the server assigns identity and executes/validates the transaction. `Operations.tsx` distinguishes real recorded completion from labeled evaluation success. `Knowledge.tsx`, `Registry.tsx` and `Memory.tsx` expose versioned source material and verified facts. All source text is rendered through React text nodes.
