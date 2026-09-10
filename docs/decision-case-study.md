# 决策案例：检索命中，不等于可以自动退款

这里展示的是一次工程决策：**把检索、业务资格、操作权限、事务执行和结果验证分别作为证据门槛。** 不因为总体检索分数较好，就让模型获得退款执行权。NovaMart 全部为模拟业务；BGE ONNX 检索和 PostgreSQL 事务真实执行；审批人为脚本化 QA 角色；本案例没有调用 LLM，也没有真实支付。

[逐 case 数据与实测链路](../evals/reports/decision-case.json) · [可复现脚本](../evals/decision_case.py) · [面试深挖](interview-deep-dive.md)

## 1. 为什么没有只展示 MRR 的上升

固定的 30 条开发问题中，26 条有答案、4 条无答案。Gold 来自自有模拟政策，经过 AI 审阅，独立人工审阅仍待完成。检索真实运行 BM25、BAAI/bge-small-en-v1.5 ONNX CPU 和 pgvector；rerank 是词汇特征评分器，不是 cross encoder。

| 历史实测 | hybrid | hybrid + 词汇 rerank | 决策含义 |
| --- | ---: | ---: | --- |
| 26 条有答案的 MRR | 0.826923 | 0.903846 | 首个正确段落的平均顺序改善 |
| Recall@3 | 26/26 | 24/26 | 更高 MRR 不保证每个问题受益 |
| Recall@5 | 26/26 | 26/26 | 当前 top K=5 保留了覆盖，但这只是开发集 |
| 4 条无答案的正确拒答 | 1/4 | 1/4 | 排序优化没有解决拒答 |

原始来源：[hybrid](../evals/reports/rag-hybrid.json)、[rerank](../evals/reports/rag-hybrid_rerank.json)。报告中的 `answer_success_proxy` 只是 gold 覆盖/正确拒答，不是生成答案正确率。JSON 导出保留全部 30×4 行，展示选例不隐藏总体失败。

## 2. 两个保留的失败，与一个反例

**口语退款问题 `rag_02`**：“Can I get my money back a month after the parcel arrived?” 正确段落是 `policy_refund_v2 / Eligibility`。keyword 未找中，dense 和 hybrid 排第 1，rerank 排第 4。词汇重排把 Settlement、Cancellation、Tracking 放到了前面。因此保留 top K=5 供审阅，而不是把总体 MRR 的改善解释为所有问题改善。它并不证明 K=5 对新语料最优。

**税务问题 `rag_29`**：“How do I file a tax return in another country?” Gold 明确无答案；四种模式全部拒答失败。rerank 第一项是 `policy_return_v2 / Return packaging`，第二项甚至是退款 Eligibility。真实实现的低置信过滤条件是 `lexical_score > 0 OR vector_score >= 0.65`；有词汇重叠就可能进入上下文。这里可观察到税务 return 与退货 return 的混淆，不能把“返回了政策片段”当成有权回答、更不能当成执行授权。

**不要过度概括**：`rag_30` 的月球飞船保险问题四种模式均返回空结果，正确拒答。已有过滤有作用，但覆盖不足。修改阈值前应建立新的近领域无答案集，不能为了这四题调参后再宣称泛化。

## 3. 从命中到动作：真实数据库里发生了什么

[执行报告的 `boundary_execution`](../evals/reports/decision-case.json) 记录实际环境、时间、政策版本、参数、订单 ID、拒绝细节、账本和独立验证结果。每次运行只创建 `test_decision_*` 独立订单，不重置工作区，不消耗普通库存。

| 步骤 | 实际观察 | 阻止的错误推断 |
| --- | --- | --- |
| 当前 BGE + rerank 检索退款窗口 | top 5 中实际包含 Eligibility | 命中是事实证据，不是动作批准 |
| 对签收 31 天订单提退款 | 服务层 409；退款记录 0 | 模型建议不能越过 30 天政策 |
| 对合格订单创建提案 | `pending`，订单仍 `delivered`，退款 0 | 工具“提案成功”不等于“退款成功” |
| 操作员尝试批准 | 服务层 403；退款仍 0 | UI 按钮与模型身份不能授予审阅权 |
| 审阅员批准，再用同一 key 重放 | 退款 1、审计 1；金额 12900 分 | 响应丢失后的重试不能二次退款 |
| 合格时创建提案，随后资格过期再批准 | 409；提案仍 pending，退款与审计均 0 | 人审不能使用过期快照直接写账 |

最后一项新增为[数据库回归](../tests/test_decision_boundary.py)：显式把测试订单的 `delivered_at` 改成 31 天前，**不改 `order.version`**，模拟等待期间跨过期限，验证执行时确实重新检查资格，而不是仅靠版本不一致偶然拒绝。它不是等了 31 天的测试。当前提案保持待审，需要重新处理；本轮不添加自动失效队列。

独立 verifier 核对金额、订单关联、提案关联、订单和账本状态。记录的 `submitted` 代表模拟退款已提交，不代表银行到账。该新增演示是顺序执行；并发正确性另由现有[12 次重放测试](../tests/test_business.py)、[取消/批准 barrier 测试](../tests/test_cancellation_race.py)和[账本变异测试](../tests/test_verifier_mutation.py)支撑，不能用这次顺序演示冒充并发压测。

## 4. 方案取舍与没有解决的问题

选择保留有来源的 top K=5 上下文、独立可执行政策，以及服务端批准事务。代价是操作员必须处理不确定请求，审批增加等待，多个政策表示需要保持版本一致。拒绝了“检索分数高就自动退款”和“多 Agent 再检查一遍就等于授权”的方案：前者没有资格证明，后者依然不能替代身份与数据库不变量。

本轮没有为故事增加新产品功能；新增的是可重跑导出与一个有业务含义的时效边界回归。它不修复错误答案本身，也不证明所有退款逻辑、账号隔离、生产恢复或真实 LLM 都安全。现有应用仍为本地模拟原型。

## 5. 复现与下一次能推翻本决策的实验

按 [README](../README.md) 启动 PostgreSQL/pgvector 并初始化模拟数据，然后运行：

```bash
python -m evals.decision_case --output evals/reports/decision-case.json
pytest tests/test_decision_boundary.py tests/test_business.py tests/test_cancellation_race.py tests/test_verifier_mutation.py -q
# 完整历史 RAG 需要重新计算时才执行；会覆盖报告，先保留原版本
python -m evals.runner rag
```

导出中的历史 30×4 行直接来自已提交报告；只有 `boundary_execution` 是本次重新执行。检索分数是不同评分函数的原值，不能跨模式直接比较大小。源文件 SHA256、历史报告 ID/时间与当前执行环境分开记录。重新导出会有新的订单 ID、时间和时延，不要求逐字节相同。

**下一实验尚未执行**：在调阈值前冻结 40 条新问题，20 条可答、20 条无答案或近领域歧义；按意图分组划成各 20 条校准/留出集，由独立审阅者检查标签。比较现有 OR 过滤与候选证据门槛，同时报告可答覆盖、拒答正确数、误拒答及人工处理量，保留每个反例。任一越权执行都阻止发布；检索更好也不会取消退款人审。没有独立审阅者时保持 AI-reviewed，不填写“人工已标注”。

AI-assisted 实现与分析；面试时只陈述本人实际读懂、复现并能解释的部分。

## 本轮验证记录

2026-09-10 本机：完整后端 **70 passed，0 skipped**，包含实际 TCP MCP/SSE；[JUnit 原始记录](../evals/reports/decision-case-tests.xml)。Ruff 检查通过。新增案例脚本真实执行通过；未重新录制视频或在本机跑浏览器。历史 A–T 手册的 69 指本轮新增测试之前的冻结结果。本轮 Linux CI 待推送执行，不能把旧版成功链接当作本轮验收。
