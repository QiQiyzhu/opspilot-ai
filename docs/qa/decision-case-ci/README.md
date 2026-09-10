# Decision-case Linux evidence

Source `86be0d259d53a9ca111339bac5c78a68ceb6de5c`; [run 34463700870](https://github.com/QiQiyzhu/opspilot-ai/actions/runs/34463700870), completed successfully on 2026-09-10.

- `run.json`: actual GitHub run/job metadata; quality and compose-runtime succeeded.
- `backend-junit.xml`: downloaded `opspilot-validation/evals/reports/backend-junit.xml`; 70 tests, zero errors/failures/skips.
- `browser-results.json`: downloaded `opspilot-validation/frontend/test-results/browser-results.json`; 8 expected, zero unexpected/skipped/flaky; 22.678 seconds.
- `decision-case-ci.json`: exact downloaded report; its boundary ran actual Linux PostgreSQL and BGE inference. Scripted review and simulated ledger are not a human study or real payment.

These are fixed first-implementation-run artifacts, not a claim that this SHA contains subsequent documentation changes. The main export additionally records LF-normalized source hashes and original working-tree hashes, so Windows CRLF conversion can be distinguished from a content change; this original CI artifact remains untouched.
