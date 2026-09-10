# Interview explanation guide

Use the trace, code and reports while rehearsing. State “simulated business” and “Fake-provider harness” before quoting agent numbers. Never convert a test score into customer impact.

| Question | Answer grounded in this implementation |
| --- | --- |
| RAG完整流程是什么？ | 格式解析、去脚本/清洗、识别标题、按章节分块、保存来源版本、ONNX嵌入、pgvector存储、BM25/向量召回、RRF、可选词汇重排、引用有效证据。 |
| Embedding是什么？ | 将文本映射为可比较的数值向量；此项目真实运行BGE 384维ONNX，而不是随机/hash向量。相似不等于事实正确。 |
| 为什么Chunk？ | 限制证据粒度和上下文长度。过小丢条件，过大混入无关规则；本项目按章节，40/100/240词实验有真实结果。 |
| Dense与BM25区别？ | BM25依赖词匹配和文档频率；dense用模型向量相似度，可捕捉同义表达，也可能匹配无关主题。 |
| 为什么Hybrid？ | 互补召回再RRF融合；本集合K3更好，但top1不一定更好，不能只给一个“提升”数字。 |
| Reranker做什么？ | 对候选二次排序；这里是公开可复现词汇特征打分，明确不是crossencoder。 |
| Recall@K和MRR？ | K个结果是否含gold section；MRR是第一个正确结果排名倒数的均值。无答案问题单独算拒答。 |
| RAG仍会幻觉？ | 召回错、引用过时、截断条件、模型曲解或把数据当指令都可能；当前拒答实验仍是弱项。 |
| Agent和Workflow？ | Workflow定义固定顺序和约束；Agent根据结构化意图和业务观察选择分支与工具，执行必须受workflow/server边界约束。 |
| Function calling和Agent？ | Function calling是模型输出工具参数的接口；Agent还要维护状态、调工具、处理错误、审批和验证。 |
| MCP和REST？ | MCP标准化工具发现/schema/transport；REST是业务产品API。退款审批仍通过有鉴权的REST业务入口。 |
| 为什么Human Approval？ | 退款改变业务状态，不能把文本预测当授权。服务端绑定审批人、参数、证据和前后状态。 |
| 为什么Tool还要鉴权？ | prompt和前端可被绕过；真实边界在后端Principal、工具风险级别、订单归属和业务事务。 |
| 幂等与Transaction？ | 幂等防重复业务效果，事务防半成功；同一请求并发12次只一笔退款，另有事务失败回滚实测。 |
| Retry为什么会重复退款？ | 请求可能已commit但响应丢失；如果生成新业务操作重试会重复。要复用key、读已有结果并验证。 |
| Redis挂了怎么办？ | 检索退到有容量/TTL的本地缓存，安全与钱的状态仍在PG。分布式ratelimit尚未实现，不应宣称有。 |
| SSE还是WebSocket？ | 此处服务端单向推送进度，用SSE简单且有事件cursor重放；双向高频交互才考虑WebSocket。 |
| P95是什么？ | 95%的观测不超过的延迟；要注明测量边界、并发、硬件、样本。50并发约5.68s是Fake端到端客户端会话P95。 |
| Multi-Agent为什么不一定好？ | 额外调用/协调可能不改变答案；这里single/full和multi同为59/60 Fake任务成功，不能推断真实LLM收益。 |
| Memory保存什么？ | 可验证的序列号/偏好/操作事实，带source/expiry/scope；模型猜测不能自动进入长期记忆。 |
| LLMOps解决什么？ | prompt/model/config可追溯、数据集和评测记录、版本diff、低于阈值拒绝release。Fake gate只能验证harness。 |
| 如何知道Prompt v2更好？ | 同模型/数据/检索条件跑冻结评测，盲审差异；本项目未跑收费模型，所以没有声称v2语义提升。 |
| 怎么防Prompt Injection？ | 证据是data、检测/隔离可疑chunk，工具allowlist、后端鉴权/审批/规则；不是只加一句system prompt。 |
| LLM timeout如何处理？ | 有界重试、backoff和circuit；失败显示可恢复状态，不伪造成功，高风险不能自动补执行。 |
| Trace如何做？ | PG存run事件sequence、trace/span标识、工具参数/结果、检索分数、模型版本/时延、验证；SSE重放同一记录。 |
| 为什么Verifier？ | 工具返回值不证明事务已提交；另开session重新读order/refund/replacement后才能宣称执行结果。 |
| 百万用户下一步？ | 先租户/SSO/最小权限和合规，再durable worker lease、配额、shared rate limit、分区/索引/缓存和压测；不先拆十几个服务。 |

练习顺序：先用5分钟讲一次退款demo，再逐行解释 `business.py` 的锁与事务；然后用失败case解释实验可信度，最后讲尚未实现的生产条件。不要背技术名词清单。
