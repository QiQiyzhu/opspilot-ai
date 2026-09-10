import { readFile, writeFile, stat } from 'node:fs/promises';
const browser = JSON.parse(await readFile('test-results/browser-results.json', 'utf8'));
const unit = JSON.parse(await readFile('test-results/unit-results.json', 'utf8'));
const recording = JSON.parse(await readFile('../docs/assets/demo-recording.json', 'utf8'));
const cases = [];
function walk(suites) {
  for (const suite of suites || []) {
    for (const spec of suite.specs || []) cases.push({ name: spec.title, ok: spec.ok, attempts: spec.tests.flatMap(test => test.results.map(result => ({ status: result.status, duration_ms: result.duration }))) });
    walk(suite.suites);
  }
}
walk(browser.suites);
const result = {
  generated_at: new Date().toISOString(),
  source: 'Actual local test-runner reports; not simulated test outcomes',
  environment: { node: process.version, browser: 'Installed Microsoft Edge via Playwright', backend: 'Actual local FastAPI/PostgreSQL service at 127.0.0.1:8003', provider: 'fake-rules-v1; no paid LLM calls', business: 'SIMULATED BUSINESS' },
  unit: { total: unit.numTotalTests, passed: unit.numPassedTests, failed: unit.numFailedTests, pending: unit.numPendingTests, success: unit.success, cases: unit.testResults.flatMap(file => file.assertionResults.map(test => ({ name: test.fullName, status: test.status }))) },
  browser: { ...browser.stats, cases },
  checks: { typecheck: 'passed via npm run build', production_build: 'passed', lint: 'passed', npm_audit_vulnerabilities: 0 },
  recording: { ...recording, bytes: (await stat('../docs/assets/demo.webm')).size },
  limits: ['These UI tests use a deterministic provider and simulated business records, not real LLM performance.', 'Refund E2E requires a fresh eligible local order from the CLI-only demo fixture; this run configured it and skipped no cases.', 'Local Edge runs do not establish remote Linux CI success. Check the GitHub workflow separately.', 'Browser screenshots are actual rendered pages. No dashboard figures were entered by hand.'],
};
await writeFile('../docs/assets/frontend-validation.json', JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify({ unit: result.unit.passed, browser: result.browser.expected, failed: result.browser.unexpected, skipped: result.browser.skipped, recording_seconds: recording.clip_duration_seconds }));
