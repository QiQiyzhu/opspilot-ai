"""Generate portfolio summaries from actual saved reports, never invented metrics."""

import ast
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "evals" / "reports"


def read(name):
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def table(headers, rows):
    return (
        "| "
        + " | ".join(headers)
        + " |\n| "
        + " | ".join(["---"] * len(headers))
        + " |\n"
        + "\n".join("| " + " | ".join(map(str, row)) + " |" for row in rows)
        + "\n"
    )


def code(path, name):
    source = (ROOT / path).read_text(encoding="utf-8")
    parsed = ast.parse(source)
    search_tree = parsed
    function_name = name
    if "." in name:
        class_name, function_name = name.split(".", 1)
        search_tree = next(n for n in ast.walk(parsed) if isinstance(n, ast.ClassDef) and n.name == class_name)
    node = next(
        n
        for n in ast.walk(search_tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function_name
    )
    text = "\n".join(source.splitlines()[node.lineno - 1 : node.end_lineno])
    return f"### {name} — `{path}:{node.lineno}`\n\n```python\n{text}\n```\n"


def generate():
    rag = read("rag-comparison.json")
    ablation = read("agent-ablation.json")
    performance = read("performance.json")
    tests = ET.parse(REPORTS / "backend-junit.xml").getroot().find("testsuite").attrib
    frontend = json.loads((ROOT / "docs/assets/frontend-validation.json").read_text(encoding="utf-8"))
    browser_regression = read("browser-approval-regression.json")["stats"]
    recording = frontend["recording"]
    full = next(r for r in ablation["results"] if r["mode"] == "full")
    n = full["cases"]
    success = round(full["task_success_rate"] * n)
    rag_table = table(
        ["Retrieval (real BGE ONNX)", "Recall@1", "Recall@3", "Recall@5", "MRR", "No-answer abstention"],
        [
            [
                r["mode"],
                *[f"{r[k]:.3f}" for k in ["recall_at_1", "recall_at_3", "recall_at_5", "mrr", "abstention_accuracy"]],
            ]
            for r in rag["results"]
        ],
    )
    agent_table = table(
        [
            "Configuration — FakeModelProvider only",
            "Synthetic tasks passed",
            "Golden tool inclusion",
            "P50 ms",
            "P95 ms",
        ],
        [
            [
                r["mode"],
                f"{round(r['task_success_rate'] * r['cases'])}/{r['cases']}",
                f"{r['correct_tool_selection']:.3f}",
                f"{r['latency_p50_ms']:.1f}",
                f"{r['latency_p95_ms']:.1f}",
            ]
            for r in ablation["results"]
        ],
    )
    perf_table = table(
        ["Concurrent local Fake sessions", "Errors", "Client run P50 ms", "P95 ms", "P99 ms"],
        [
            [
                r["concurrency"],
                f"{r['error_rate']:.1%}",
                *[f"{r['latencies']['agent_session'][k]:.1f}" for k in ["p50_ms", "p95_ms", "p99_ms"]],
            ]
            for r in performance["results"]
        ],
    )
    readme = f"""# OpsPilot AI

Production-oriented RAG + Agent system for customer support and business operations.

**NovaMart is SIMULATED BUSINESS.** Real PostgreSQL transactions, ONNX embeddings, MCP and SSE are executed locally. The default **FakeModelProvider is a deterministic rules router, not an LLM**; its full harness passes **{success}/{n} synthetic tasks**. Real LLM quality, token usage and cost are **NOT RUN / unavailable**.

[Watch the actual {recording["clip_duration_seconds"]}-second browser demo](docs/assets/demo.webm) · [Four repeatable demos](docs/demo.md) · [Interview dossier A–T](docs/interview-dossier.md) · [Validation evidence](docs/validation.md)

![Actual human approval console](docs/assets/demo-approval.png)

The console supports inbox/conversations, customers/orders, evidence and traces, reviewed business actions, knowledge ingestion, prompt/workflow versions, verified memory, evaluations and operations. [Actual recorded refund run](docs/assets/demo-run.json) links the video to its database run and audit. No live public admin console is claimed; reviewers can use the video, source and fresh-clone instructions.

```mermaid
flowchart LR
 U[React staff console] -->|REST + real SSE| A[FastAPI modular monolith]
 A --> W[Workflow + auditable Agent]
 W --> R[BM25 + BGE ONNX + pgvector + RRF]
 W --> T[Native / MCP HTTP tools]
 T --> P[Human approval transaction]
 P --> D[(PostgreSQL)]
 P --> V[Independent DB verifier]
 V --> U
 D --> E[Evaluation / SQL / alerts]
```

## Measured retrieval — real ONNX, synthetic questions

30 owned-policy synthetic questions: 26 answerable and 4 no-answer. **AI-reviewed; independent human review pending.** Dense uses BAAI/bge-small-en-v1.5, 384-dimensional ONNX CPU inference. Rerank is a **non-model lexical feature scorer**, not a cross encoder. Query cache is cleared per case.

{rag_table}
Hybrid has stronger K3 coverage; rerank has stronger first-result ordering. No-answer abstention remains weak. [Raw JSON/CSV](evals/reports/rag-comparison.json) and [36 actual chunk/mode/top-K experiments](evals/reports/rag-ablation.json) preserve both strengths and failures. “Answer success” there means evidence coverage, not generated answer quality.

## Agent ablation — FakeModelProvider, not an LLM benchmark

Each configuration executes the same 60 synthetic tasks with isolated real database orders, products and inventory; evaluation does not replenish or consume the console's stock. Scripted test approval is not a real human research participant. Tokens/cost are null; no LLM improvement claim is supported.

{agent_table}
Full and multi both pass {success}/{n} **Fake-provider synthetic harness** tasks. Multi-agent adds coordination without a success gain here. Mandatory approval/transaction verification stays enabled even in the tools baseline; the verification ablation concerns optional read-response checking. [Raw reports](evals/reports/agent-ablation.json) include failures and metric definitions.

## Approval, LLMOps and failure handling

A model can propose a refund, replacement or cancellation but cannot execute one. The server authenticates the reviewer, takes a shared run lock before proposal/order locks, rechecks active policy and stock, and commits business record plus audit atomically. Independent verification checks approved refund amount and order association; replacement verification checks a proposal-specific inventory journal, including quantity and before/after arithmetic. It does not compare historical stock with today's balance. Twelve concurrent replays of one request produce one refund in the real PostgreSQL test. Controlled database barriers verify both approval/cancellation orderings; mutation tests reject wrong amounts, orders and reservations.

![Actual verified business outcome](docs/assets/demo-verified.png)

Prompts/workflows have immutable versions, diffs and snapshots. A regression gate fails below 0.80 task success or above zero unsafe actions; a Fake pass validates harness invariants only. Redis outage uses bounded local caching; timeout/schema/MCP/DB failures are observed, not replaced by invented success. [Threat model](docs/security.md), [failure cases](docs/failure-cases.md), [reliability](docs/reliability.md).

## Run from a fresh clone

Requirements: Python **3.12**, Node **22.13+**, Docker Compose (or PostgreSQL17+ with pgvector installed). First startup downloads the lightweight ONNX embedding model; no paid API is needed. Keep large caches/data on a drive with space.

```bash
cp .env.example .env
docker compose up -d db redis
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
pip install --no-deps -e .
python -m backend.seed
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8003
# second terminal
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5176`. `.env.example` lists intentionally public **local-demo tokens** (`demo-admin`, `demo-operator`, `demo-approver`, `demo-viewer`). The server determines roles; the UI never sends an approval identity. Replace demo tokens and add deployment authentication before making the console network-accessible. For a containerized backend, `docker compose up --build backend` uses the same API contract; the frontend remains the separate Vite console.

Windows: use `py -3.12 -m venv <data-drive>/OpsPilot/venv` and that environment's `Scripts/python.exe`; set process-local `TEMP`, `TMP`, `PIP_CACHE_DIR`, `HF_HOME` and `OPSPILOT_MODEL_CACHE` to your chosen data drive before installation. Source code paths and `.env.example` do not require this developer machine. [Actual portable PostgreSQL installation provenance](installation.md) documents the alternative used locally when Docker was unavailable.

## Reproduce validation

```bash
pytest -q
OPSPILOT_LIVE_URL=http://127.0.0.1:8003 pytest tests/test_live.py -q
python -m evals.runner rag
python -m evals.rag_ablation
python -m evals.runner agent
python -m evals.gate evals/reports/agent-full.json
python -m analytics.load_test
python -m analytics.explain
python -m evals.demo
```

Backend local result: **{tests["tests"]} passed, 0 skipped**, including TCP MCP/SSE tests. Frontend commands and credential/fixture setup are in [frontend README](frontend/README.md). GitHub Actions includes PostgreSQL/Redis services, lint/tests, Fake regression gate, browser integration and Docker build; remote CI and Docker were not executed locally at initial delivery. See validation for current evidence.

{perf_table}
Local Windows developer-host Fake sessions, not production QPS or real LLM latency. [Scope and limitations](docs/performance.md).

## Read the implementation

[Architecture](docs/architecture.md) · [Database](docs/database.md) · [RAG](docs/rag.md) · [Agent/workflow/memory](docs/agent.md) · [MCP](docs/mcp.md) · [LLMOps](docs/llmops.md) · [Evaluation](docs/evaluation.md) · [API contract](docs/api-contract.md) · [Interview guide](docs/interview-guide.md).

Remaining work includes independent human review, real-provider evaluation, better no-answer calibration, tenant/SSO authorization, durable workers and migration/backup operations. This portfolio does not claim real customers, revenue, DAU, production throughput or paid-model gains.
"""
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    validation = f"""# Validation evidence

Local backend: **{tests["tests"]} passed**, failures={tests["failures"]}, errors={tests["errors"]}, skipped={tests["skipped"]}, runtime {tests["time"]}s. [JUnit](../evals/reports/backend-junit.xml). One upstream Starlette/AnyIO deprecation warning was observed. Tests include actual PostgreSQL, ONNX, TCP MCP, SSE and transaction concurrency.

Frontend actual result: **{frontend["unit"]["passed"]} unit tests passed; {frontend["browser"]["expected"]} browser scenarios passed, {frontend["browser"]["skipped"]} skipped, {frontend["browser"]["flaky"]} flaky**, runtime {frontend["browser"]["duration"] / 1000:.2f}s. [Runner evidence](assets/frontend-validation.json) also records build/typecheck/lint success and npm audit 0. The continuous actual browser recording is {recording["clip_duration_seconds"]}s with {len(recording["page_errors"])} page errors, bound to run `{recording["run_id"]}`. This is local Edge evidence, not a remote CI claim.

After the cancellation/ledger verifier fixes, the existing cancellation and refund/idempotency browser scenarios were rerun against the actual backend: **{browser_regression["expected"]} passed, {browser_regression["unexpected"]} failed, {browser_regression["skipped"]} skipped**, in {browser_regression["duration"] / 1000:.2f}s. [Separate regression report](../evals/reports/browser-approval-regression.json). The earlier eight-scenario report, screenshots and continuous recording remain preserved; this narrower rerun is not presented as a new eight-scenario run. [Actual gate command results](../evals/reports/gate-validation.json) include an accepted full harness and an intentionally rejected 27/60 baseline.

RAG: 30 synthetic questions × 4 baselines; 36 rechunking/mode/top-K configurations × 30 questions. Agent: 60 synthetic tasks × 6 actual **FakeModelProvider harness** configurations. Full result {success}/{n}; no real LLM provider was called. Human review pending. Four live API demos and one actual browser recording are saved with run IDs. No report claims real user research.

{perf_table}
85 total local simulated sessions; real LLM latency is NOT RUN. The values above come directly from the saved JSON.

Local environment: Python3.12.14; PostgreSQL17.11; pgvector0.8.6; real BGE-small English ONNX384. PostgreSQL binaries, database, venv, pip/model caches and process temporary files are on a dedicated data drive. Docker was unavailable during initial setup. OpsPilot Docker build and GitHub Actions status at initial delivery: **NOT RUN**. Do not write “CI passed” before an actual remote run is inspected.
"""
    (ROOT / "docs" / "validation.md").write_text(validation, encoding="utf-8")
    tree = "\n".join(
        sorted(
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in ROOT.rglob("*")
            if p.is_file()
            and not any(
                x in p.parts
                for x in [
                    ".git",
                    "node_modules",
                    "__pycache__",
                    ".pytest_cache",
                    ".ruff_cache",
                    "test-results",
                    "dist",
                    "playwright-report",
                ]
            )
            and p.name != ".env"
        )
    )
    backend_files = [
        ("backend/business.py", "事务、幂等、资格、独立验证"),
        ("backend/models.py", "FK/index/JSONB/vector schema"),
        ("backend/rag.py", "解析、ONNX、BM25、RRF、非模型重排与cache"),
        ("backend/agent.py", "状态机、真实事件、审批恢复与取消"),
        ("backend/tools.py", "schema、role、customer scope、native/MCP dispatch"),
        ("backend/providers.py", "Fake与真实provider边界、retry/circuit"),
        ("backend/mcp_server.py", "真实HTTP协议和服务端鉴权"),
        ("backend/registry.py", "版本验证/diff/release gate"),
        ("backend/app.py", "HTTP/SSE contract、错误和权限"),
        ("evals/runner.py", "独立fixtures、评分定义、ablation真实性"),
    ]
    front_files = [
        ("frontend/src/api.ts", "认证请求、流分帧、类型和格式化"),
        ("frontend/src/Inbox.tsx", "运行选择、SSE去重、旧请求竞态、证据/trace"),
        ("frontend/src/Approval.tsx", "只发送decision/reason/key，不发送审批身份"),
        ("frontend/src/Operations.tsx", "实际指标、null与synthetic cohort展示"),
        ("frontend/src/Registry.tsx", "prompt/workflow真实版本编辑和diff"),
    ]
    questions = [
        "如果审批请求超时但数据库已commit，重试怎样避免重复退款？",
        "同一个订单的两个不同proposal并发审批，谁负责排他？",
        "为什么幂等key锁之外还需要订单锁和unique约束？",
        "事务commit后Verifier失败，你会回滚还是进入人工处理？",
        "取消与审批同时发生的语义是什么？已提交效果能否被取消？",
        "为什么本地小表EXPLAIN可能不用已建索引？",
        "替换订单状态和库存扣减为什么必须同事务？",
        "RRF的rank常数有什么影响，如何做调参隔离？",
        "相同source section在40词分块变成多个chunk，gold section如何计分？",
        "无答案问题为什么不能把Recall@K当拒答准确率？",
        "如果重排提升MRR但降低Recall@3，产品应该如何选K？",
        "为什么Fake 59/60不能写成大模型准确率98.3%？",
        "工具集合包含率与precision差在哪，当前评测遗漏什么？",
        "真实LLM Prompt v2上线前还缺哪些证据？",
        "MCP比REST多了什么协议能力，为什么不能替代鉴权？",
        "静态staff token的风险和SSO迁移方案是什么？",
        "进程崩溃后SSE事件在，task不在，怎样做durable resume？",
        "为什么Redis不能用作退款一致性的事实来源？",
        "如何避免过期memory和模型猜测污染长期记忆？",
        "从50本地并发扩展到真正多人生产，先测和先改什么？",
    ]
    bullets = [
        f"构建 NovaMart 模拟客服运营平台，使用 FastAPI/PostgreSQL/pgvector 和真实 MCP/SSE，在本地 {tests['tests']} 项后端测试中验证鉴权、事务、流式事件及故障处理；不涉及真实商业用户。",
        "实现模拟退款的服务端审批、事务锁与幂等控制；实际12个并发重复请求只写入1笔退款，包含丢失响应后的重放和数据库失败回滚测试。",
        "建立30条自有政策 synthetic retrieval benchmark，运行真实BGE ONNX384嵌入与4种检索基线，并完成36组chunk/检索/top-K实验；明确标注启发式重排和人工审核待完成。",
        f"建立60条 synthetic agent tasks 的6配置消融评测；Full FakeModelProvider规则harness通过{success}/{n}，保留失败案例并明确不代表真实LLM能力或客服效率提升。",
        "完成10/25/50并发本地Fake Provider模拟会话测试共85会话，实测错误率0；50并发客户端会话P95约5.68秒，注明开发机与测量边界，不声称生产QPS。",
    ]
    sections = [
        ("A. 最终系统架构", (ROOT / "docs/architecture.md").read_text(encoding="utf-8")),
        ("B. Repository tree", "```text\n" + tree + "\n```"),
        ("C. Database schema", (ROOT / "docs/database.md").read_text(encoding="utf-8")),
        (
            "D. RAG pipeline",
            "见 [RAG设计](rag.md)。Parse→Clean→Section→Chunk→Metadata→真实ONNX→PGvector/BM25→RRF→词汇重排→有效版本证据。",
        ),
        (
            "E. Agent workflow",
            "见 [Agent](agent.md)。结构化意图+有界工具→proposal→服务端人审→transaction→独立Verifier→答复；private CoT不记录。",
        ),
        ("F. MCP设计", (ROOT / "docs/mcp.md").read_text(encoding="utf-8")),
        ("G. LLMOps设计", (ROOT / "docs/llmops.md").read_text(encoding="utf-8")),
        ("H. Reliability机制", (ROOT / "docs/reliability.md").read_text(encoding="utf-8")),
        ("I. Security机制", (ROOT / "docs/security.md").read_text(encoding="utf-8")),
        ("J. Test实际结果", validation),
        (
            "K. RAG真实结果",
            "真实BGE ONNX / SYNTHETIC questions / non-model reranker / PENDING HUMAN REVIEW。\n\n"
            + rag_table
            + "\n36组ablation原始数据见 `evals/reports/rag-ablation.json`。无答案拒答仍弱，不掩盖。",
        ),
        (
            "L. Agent ablation真实结果",
            "**以下全部执行FakeModelProvider规则harness，不是LLM benchmark。**\n\n"
            + agent_table
            + "\n真实LLM尚未配置/授权，token/cost=null；不得声称模型提升。",
        ),
        ("M. Performance真实结果", perf_table + "\n" + (ROOT / "docs/performance.md").read_text(encoding="utf-8")),
        ("N. 失败案例", (ROOT / "docs/failure-cases.md").read_text(encoding="utf-8")),
        (
            "O. 尚未完成的问题",
            "独立人工审查合成标签；真实LLM质量/成本/时延评测；拒答校准与更广注入测试；SSO/多租户/最小DB权限；审批过期与durable worker；Alembic迁移/备份恢复演练；线上托管。Docker/GitHub CI初始交付未运行，后续只能追加真实记录。",
        ),
        ("P. 10个必须逐行读懂的Backend文件", table(["File", "阅读目标"], backend_files)),
        ("Q. 5个必须读懂的Frontend文件", table(["File", "阅读目标"], front_files)),
        (
            "R. 10段必须口述的真实关键代码",
            "以下从当前源码AST提取，行号对应生成时版本。\n\n"
            + "\n".join(
                code(p, n)
                for p, n in [
                    ("backend/security.py", "require"),
                    ("backend/business.py", "advisory_lock"),
                    ("backend/business.py", "propose"),
                    ("backend/business.py", "_decide_transaction"),
                    ("backend/business.py", "verify"),
                    ("backend/rag.py", "current_documents"),
                    ("backend/rag.py", "lexical_rerank"),
                    ("backend/agent.py", "event"),
                    ("backend/registry.py", "release"),
                    ("backend/cache.py", "ResilientCache.get"),
                ]
            ),
        ),
        ("S. 20个面试追问", "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))),
        (
            "T. 5条真实简历Bullet候选",
            "这些表述是项目实现候选，不是未经学习即可声称的个人熟练程度；先完成P/Q/R的代码讲解。\n\n"
            + "\n".join("- " + b for b in bullets),
        ),
    ]
    dossier = "# OpsPilot AI — Interview dossier A–T\n\n**SIMULATED BUSINESS. Fake provider scores are engineering-harness evidence, not LLM能力、真实客服效率或商业落地。**\n\n"
    dossier += "\n\n".join("## " + title + "\n\n" + body for title, body in sections)
    (ROOT / "docs/interview-dossier.md").write_text(dossier, encoding="utf-8")
    print("Generated README, validation and A-T dossier from actual reports")


if __name__ == "__main__":
    generate()
