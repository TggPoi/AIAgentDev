# 多 Agent 浏览器真实链路测试报告

## 1. 验收范围与结论

- 执行日期：2026-07-20（Asia/Shanghai）
- 运行批次：`20260720-161404`
- 验收入口：`scripts/phase_15/rag_agent_manual_acceptance.html`
- 后端：本地 FastAPI 单实例；真实 PostgreSQL、Redis、Elasticsearch、Milvus
- 外部服务：真实 Qwen LLM/Embedding、DashScope Reranker、Bocha WebSearch
- 测试账号：使用现有文档工具管理账号；本报告不保存密码、Token 或模型密钥
- 用户列出的三个编号场景中，第一个场景拆分为“创建、检索、修改”三个业务子场景验收。

最终结论：**部分通过**。

| 场景 | 结果 | 结论 |
|---|---|---|
| 文档多 Agent：本地检索 + WebSearch + 创建 | 失败 | Supervisor 和 Deep Agent 已启动，但多次超时，未到达 dry-run、Reviewer 批准和人工确认。目标文件未创建。 |
| 文档多 Agent：检索、修改刚创建的文档 | 未执行 | 创建前置步骤失败，不伪造后续通过结论。 |
| 文档多 Agent：中断后恢复 | 部分通过 | PostgreSQL Checkpoint 保留、同一 `thread_id` 恢复、`resume_count` 递增均有证据；恢复后仍因模型超时失败，未完成最终交付。 |
| 检索多 Agent：本地知识库 + Web fallback | 部分通过 | 并行波次、Evaluator、纠正检索、局部失败隔离和 `completed_with_warnings` 均生效；一个 Worker 超时导致两个依赖任务跳过，最终综合不完整。 |

## 2. 测试产物

本批次产物保留在：

```text
runtime/manual-agent-acceptance/20260720-161404/
├─ task-plans/
│  ├─ 20260720_082341_task_plan_20260720082341_0cee0ff25b1f.json
│  ├─ 20260720_082341_task_plan_20260720082341_0cee0ff25b1f.md
│  ├─ 20260720_083310_task_plan_20260720083310_01ebaf515c68.json
│  ├─ 20260720_083310_task_plan_20260720083310_01ebaf515c68.md
│  ├─ 20260720_083431_task_plan_20260720083431_b5fa75de7bd9.json
│  ├─ 20260720_083431_task_plan_20260720083431_b5fa75de7bd9.md
│  ├─ 20260720_083646_task_plan_20260720083646_4e765cb540e5.json
│  ├─ 20260720_083646_task_plan_20260720083646_4e765cb540e5.md
│  ├─ 20260720_085913_task_plan_20260720085913_c75adfb28a8f.json
│  └─ 20260720_085913_task_plan_20260720085913_c75adfb28a8f.md
└─ uvicorn*.log
```

TaskPlan 的 JSON 是状态、错误、Sources、子问题结果和 Checkpoint 摘要的主要复查证据；Markdown 是人工审查视图。

## 3. 环境检查

实际检查结果：

- FastAPI `/health` 可访问。
- PostgreSQL、Elasticsearch、Milvus、Redis 容器处于可用状态。
- Deep Agent 启动日志显示 PostgreSQL checkpoint/store 已创建。
- 文档工具、认证、真实检索和真实外部模型配置生效。
- 验收时临时关闭 LangSmith tracing，避免追踪网络噪声影响结果；这不改变 Agent、检索或 Checkpoint 业务逻辑。
- 为区分默认超时与外部模型超时，后续一轮仅在验收进程中将 `AGENT_DOCUMENT_WORKER_TIMEOUT_SECONDS` 从默认 180 秒提高到 600 秒；仓库默认配置未被改写。

## 4. 场景一：文档工作链路多 Agent

### 4.1 请求

```text
请创建知识库文档 development/manual-agentic-acceptance-20260720.md。
先检索本地知识库中关于 RAG Agent 多 Agent 编排、Deep Agent 文档工作流和 checkpoint 恢复的内容，
再联网搜索 LangGraph durable execution 与 human-in-the-loop 的公开最佳实践。
请由 Researcher 汇总证据、Writer 编写包含“本地实现、公开资料、风险与验收建议”四部分的 Markdown 草稿，
并由 Reviewer 审查后提交待确认的创建方案；不要在人工确认前写入真实知识库。
```

请求勾选 `allow_web_fallback=true`。

### 4.2 TaskPlan

- TaskPlan ID：`task_plan_20260720082341_0cee0ff25b1f`
- `task_kind`：`knowledge_document_management`
- `execution_mode`：`agentic`
- Supervisor 生成三个交付物：
  1. `research-evidence-summary`
  2. `draft-markdown-content`
  3. `reviewed-creation-proposal`
- 最终状态：`failed`
- 最终错误：`APITimeoutError: Request timed out.`
- 文档阶段：`deep_agent_running`
- 三个 deliverable 在失败快照中仍为 `running`

### 4.3 实际执行

首次执行使用默认 180 秒文档 Worker 超时，`deep_document_agent.py` 外层 `asyncio.wait_for()` 超时。随后通过同一个 TaskPlan 的 `/retry` 恢复：

- Checkpoint 状态：`resumable`
- 持久化模式：`sync`
- 最终 `resume_count=4`
- 最终 `record_version=19`
- 运行日志和快照证明恢复时跳过了已完成的前置节点，并继续未完成的检索节点。

把验收进程超时提高到 600 秒后，任务仍被外部模型客户端的 `APITimeoutError` 中断。因此问题不只是 FastAPI 请求时间不够，还包括外部模型调用缺少适合长任务的超时/重试/降级策略。

### 4.4 文件与写入边界

验收结束时以下文件均不存在：

```text
docs/knowledge-base-acl-test/development/manual-agentic-acceptance-20260720.md
docs/knowledge-base-acl-test/development/manual-agentic-short-20260720.md
```

这说明失败任务没有越过人工确认边界，也没有把虚拟工作区草稿错误发布为真实知识库文件；安全边界通过。但由于没有形成 approved proposal 和 dry-run，创建功能本身不通过，后续“检索刚创建文档、修改刚创建文档”无法执行。

### 4.5 发现的问题

1. 默认 `AGENT_DOCUMENT_WORKER_TIMEOUT_SECONDS=180` 对真实的“本地检索 + Web + Writer + Reviewer”任务偏短。
2. `TimeoutError` / `APITimeoutError` 没有统一转换为稳定业务错误码，浏览器只能看到通用异常或 `Failed to fetch`。
3. `/rag/chat/stream/events` 在 TaskPlan 已创建后发生错误时，错误事件没有稳定携带 `task_plan_id`，人工只能到 runtime 目录反查。
4. 失败后 `resumed_from_checkpoint=false` 会覆盖“本轮确实从 Checkpoint 恢复过”的事实，字段语义容易误导。
5. 任务已失败，但三个 deliverable 仍保持 `running`，失败收尾没有把进度状态归一化。
6. `/retry` 的异常链路可直接中断 fetch，前端无法得到结构化失败响应。

## 5. 场景二：中断与 Checkpoint 恢复

### 5.1 已验证机制

对 `task_plan_20260720082341_0cee0ff25b1f` 执行中断/失败后的重复恢复，验证到：

- TaskPlan JSON 保留 `deep_agent_checkpoint` 摘要。
- PostgreSQL Saver/Store 保留虚拟工作区与图执行状态。
- `/retry` 使用同一个 TaskPlan 和 LangGraph `thread_id`，不是创建一条全新任务。
- `resume_count` 从 0 递增到 4。
- `record_version` 递增到 19，说明任务级持久化记录持续更新。
- `durability=sync`，完成节点的 Checkpoint 在进入下一节点前落库。
- 中断后目标文件仍不存在，未绕过人工确认。

### 5.2 未通过部分

- 恢复后的任务没有最终收敛，仍被外部模型超时终止。
- 未验证“恢复后生成 proposal → dry-run → waiting_confirmation → confirm → 实际写入”的完整闭环。
- 未验证创建成功后的文档再检索和修改。

因此该场景只能判定为“Checkpoint 保存和恢复机制部分通过”，不能判定为端到端恢复通过。

## 6. 场景三：检索链路多 Agent

### 6.1 请求

```text
请分析当前工程距离企业级 Agent 任务可靠性还有哪些差距。
分别研究：一，checkpoint 与中断恢复；二，同一任务并发 retry 和多实例并发安全；
三，本地检索来源、ACL 与答案可追溯性；四，综合前三项给出修复优先级。
必须先从本地知识库提取当前实现证据；如果本地证据不足以完成行业对比，
可以使用本次已授权的 Web fallback 补充公开资料。
```

### 6.2 TaskPlan 与波次

- TaskPlan ID：`task_plan_20260720083646_4e765cb540e5`
- `task_kind`：`question_decomposition`
- `web_policy`：`fallback`
- 子问题：5 个
- 波次 1：`sq_1`、`sq_2`、`sq_3` 同时启动
- `sq_4` 依赖 `sq_1/sq_2/sq_3`
- `sq_5` 依赖 `sq_1/sq_2/sq_3/sq_4`
- 最终状态：`completed_with_warnings`
- Sources：46 条
- Warnings：5 条

### 6.3 子问题结果

| 子问题 | 状态 | 尝试 | 最后工具 | Evaluator / 错误 |
|---|---:|---:|---|---|
| `sq_1` | `partial` | 1 | `knowledge_retrieval` | `insufficient` |
| `sq_2` | `partial` | 2 | `web_search` | `insufficient`；本地不足后触发 Web 纠正 |
| `sq_3` | `failed` | 1 | `none` | `WORKER_TIMEOUT` |
| `sq_4` | `skipped` | 0 | `none` | `DEPENDENCY_FAILED: sq_3` |
| `sq_5` | `skipped` | 0 | `none` | `DEPENDENCY_FAILED: sq_3` |

### 6.4 已通过机制

- 同一波次三个独立 Worker 真实并行派发。
- Evaluator 能输出 `insufficient` 和 `missing_points`。
- `web_policy=fallback` 下，本地证据不足后允许第二次 attempt 使用 WebSearch。
- 一个 Worker 超时没有终止其他独立 Worker。
- 依赖失败 Worker 的下游任务被确定性标记为 `skipped`。
- 有部分证据时整体返回 `completed_with_warnings`，没有伪装成全部成功。
- Sources 保留本地 `source_path`、ACL/部门 metadata 和 Web URL。

### 6.5 内容质量缺口

- 当前本地知识库主要是游戏开发、资产和部署文档，缺少本工程当前代码机制的知识文档，导致本地召回与问题相关性不足。
- Web 纠正结果包含掘金/CSDN 等二手来源，没有稳定优先命中 LangGraph 官方文档。
- `sq_3` 超时后，`sq_4` 和最终综合 `sq_5` 都被跳过，所以无法形成完整的企业级差距排序。
- `agent_task_evidence_evaluated` 事件外层 `status=completed`，内部 verdict 却是 `insufficient`；虽然可解释为“评估动作完成”，但前端容易误解为“证据已充分”。

## 7. 补充探索性缺陷

### 7.1 只读研究被误路由为文档任务

`task_plan_20260720083310_01ebaf515c68` 的请求明确包含“保留来源，不要修改任何文档”，但 Router 仍选择 `knowledge_document_management`。随后 Deep Agent 的 Supervisor 结构化输出把本应为列表的 `depends_on/source_requirements/required_capabilities` 生成成字符串，最终出现：

```text
ValidationError: DocumentWorkflowResult
Input should be a valid dictionary or instance of DocumentWorkflowResult
```

说明 Router 对否定语义和“只读研究”边界仍不稳定，Deep Agent Supervisor 的结构化输出失败也缺少一次安全的格式修复/重试。

### 7.2 同一页面并发请求导致展示串线

测试页原来允许上一条 SSE 未结束时再次点击流式请求，并让所有响应共享：

```text
currentTaskPlanId
currentConfirmEndpoint
streamController
answerBox / logBox
```

因此出现过“当前输入是短文档创建任务，但页面展示了上一条企业可靠性研究 TaskPlan”的现象。该证据同时受到前端并发竞争影响，不能直接断言一定是后端会话污染。

已对测试页做最小修复：

- 聊天、确认、重试共用单请求锁；请求运行时禁用会产生竞争的按钮。
- 保留取消按钮，使运行中的任务仍可人工取消。
- 只去掉连续完全相同的 `agent_task_status` 事件，状态变化仍完整保留。
- 保留手工加载 TaskPlan 和导出快照能力。

遗留的重复研究 TaskPlan `task_plan_20260720085913_c75adfb28a8f` 已通过浏览器取消，最终状态为 `cancelled`。

## 8. 修复优先级建议

### P0：先保证任务能稳定结束

1. 为文档 Deep Agent 的每类外部调用设置分层超时和有限重试，不只扩大整个 Worker 的总超时。
2. 把 `asyncio.TimeoutError`、模型 `APITimeoutError` 和网络异常统一转换为稳定错误码，并让 SSE/HTTP 始终返回 `task_plan_id`。
3. 失败收尾时把仍为 `running` 的 deliverable 标记为 `failed` 或 `partial`，保存最后完成节点和失败节点。
4. 修复 `/retry` 异常逃逸，保证浏览器永远收到结构化响应。

### P1：修复路由和结构化输出可靠性

1. 增加“不要修改、只读研究”等否定语义测试，确保 Router 选择 Research 链路。
2. Supervisor 结构化输出验证失败时做一次受限修复；仍失败则返回明确错误，不进入 Deep Agent 图。
3. 将“本轮是否从 Checkpoint 恢复过”和“当前是否需要从 Checkpoint 恢复”拆成两个字段，避免 `resumed_from_checkpoint` 被失败收尾覆盖。

### P2：改善检索证据质量和前端可观察性

1. 把当前工程机制文档正式导入知识库，否则本地检索无法回答代码实现问题。
2. WebSearch 对框架问题优先官方域名，Evaluator 将来源权威性纳入重试查询。
3. 明确 SSE 中“评估动作完成”和“证据充分”是两个状态字段。
4. 后端减少重复状态心跳，前端仍保留相邻重复事件去重作为显示保护。

## 9. 最终判定依据

本次不是 mock 测试。浏览器调用了真实 FastAPI、真实存储、真实本地检索和真实外部模型。结果证明两条多 Agent 链路的核心编排机制已经存在，但文档链路受超时与错误收尾影响，尚不能完成复杂创建任务；检索链路能带警告完成，却没有完成全部依赖问题和最终综合。

因此最终判定保持为：**部分通过，暂不满足完整企业人工验收通过标准**。

# 关闭VPN，人工测试场景：

建议按“简单调用 → 检索多 Agent → Checkpoint 恢复 → 文档完整链路”的顺序测试。每个场景使用不同的 `session_id`，不要在一个会话中混合测试。

另外，本次验收后端已被我关闭，你需要先重新启动 FastAPI。建议把日志同步保存下来。

## 一、启动并保存后端日志

在项目根目录执行：

```
$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$artifactDir = "runtime\manual-agent-acceptance\vpn-off-$runId"

New-Item -ItemType Directory -Force "$artifactDir\task-plans" | Out-Null

$env:PYTHONPATH = "src"
# 不要在这里把 LANGSMITH_TRACING / LANGCHAIN_TRACING_V2 设为 false。
# 当前 .env 已启用 LangSmith；PowerShell 进程环境变量会覆盖 .env，显式 false
# 会导致启动日志出现 langsmith.config.disabled，且本轮请求不会上传任何 Run。

.\.venv\Scripts\python.exe -m uvicorn fast_app.main:app `
  --host 127.0.0.1 `
  --port 8000 2>&1 |
  Tee-Object "$artifactDir\backend.log"
```

这个终端保持运行。建议通过 `5173` 启动测试页面，避免 CORS 差异：

```
.\.venv\Scripts\python.exe -m http.server 5173 `
  --directory scripts\phase_15
```

访问：

```
http://127.0.0.1:5173/rag_agent_manual_acceptance.html
```

## 二、测试 Query

### 1. Qwen 与本地检索基础测试

`session_id`：

```
vpn-off-simple-rag-20260720
```

Query：

```
为什么不应该在 Anim Notify 中决定最终伤害？请根据本地知识库回答，并返回对应来源。
```

设置：

```
allow_web_fallback = false
```

预期：

- 正常返回答案。
- 能看到本地知识库来源。
- 通常不生成复杂 TaskPlan。
- 记录从点击到完成的耗时。

这个场景用于判断关闭 VPN 后，普通 Qwen 调用是否仍然缓慢。



### ⚠️ 异常：langsmith中未记录执行流程



------

### 2. 检索链路多 Agent    **task_plan_20260722095255_d6dfbf706f38**

为了和上次测试直接对比，建议使用相同 Query。

`session_id`：

```
vpn-off-research-agent-20260720
```

Query：

```
请分析当前工程距离企业级 Agent 任务可靠性还有哪些差距。分别研究：一，checkpoint 与中断恢复；二，同一任务并发 retry 和多实例并发安全；三，本地检索来源、ACL 与答案可追溯性；四，综合前三项给出修复优先级。必须先从本地知识库提取当前实现证据；如果本地证据不足以完成行业对比，可以使用本次已授权的 Web fallback 补充公开资料。
```

设置：

```
allow_web_fallback = true
```

操作：

1. 点击“流式 `/rag/chat/stream/events`”。
2. TaskPlan 出现后记录 `task_plan_id`。
3. 点击“确认并执行 TaskPlan”。
4. 等待最终状态。
5. 点击“导出当前验收快照”。

重点观察：

- 第一波是否同时出现多个 Worker。
- 本地证据不足后是否触发 WebSearch。
- 是否还出现 `WORKER_TIMEOUT`。
- 最终是 `completed` 还是 `completed_with_warnings`。
- `sq_4`、`sq_5` 是否仍被跳过。
- 总耗时是否明显短于开启 VPN 时。

理想结果：

```
所有子问题 completed
TaskPlan = completed
sq_4、sq_5 正常执行
没有 WORKER_TIMEOUT
```

------

### 3. 文档任务中断和 Checkpoint 恢复

`session_id`：

```
vpn-off-checkpoint-resume-20260720
```

Query：

```
请创建知识库文档 development/vpn-off-checkpoint-resume-20260720.md。Researcher 从本地知识库检索一条 RAG Agent 多 Agent 编排证据，并联网搜索一条 LangGraph durable execution 官方资料；Writer 生成不超过 800 字的 Markdown，包含“本地实现、公开资料、风险、验收建议”四部分；Reviewer 审查后提交待确认方案。人工确认前不要写入真实知识库。
```

设置：

```
allow_web_fallback = true
```

操作：

1. 提交 Query，获得 TaskPlan。
2. 点击“确认并执行 TaskPlan”。
3. 等看到以下任意事件后中断：

```
agent_task_document_subagent_started
document-researcher
deep_agent_running
```

1. 点击“停止流式请求”。
2. 立即导出验收快照。
3. 等待约 5 秒。
4. 在“已有 TaskPlan ID”中输入原来的 ID。
5. 点击“加载已有 TaskPlan”。
6. 检查 Checkpoint 是否为：

```
status = resumable
durability = sync
```

1. 点击“重试 TaskPlan”。
2. 等待恢复结果，再导出一次快照。

重点观察：

- `task_plan_id` 是否保持不变。
- `resume_count` 是否增加。
- `record_version` 是否增加。
- 是否出现 `resumed_from_checkpoint=true`。
- 是否跳过中断前已经完成的节点。
- 恢复后能否最终到达待确认状态。
- 是否还出现 `APITimeoutError`。

如果要进行更强的“进程崩溃恢复”测试，可以在出现 `document-researcher` 后直接停止 FastAPI，再重新启动后端，使用相同 TaskPlan ID 点击重试。

------

### 4. 文档多 Agent 正常创建

`session_id`：

```
vpn-off-document-create-20260720
```

Query：

```
请创建知识库文档 development/vpn-off-agentic-create-20260720.md。先从本地知识库检索 RAG Agent 多 Agent 编排和 checkpoint 恢复的实现证据，再联网搜索 LangGraph durable execution 与 human-in-the-loop 的官方资料。Researcher 汇总证据，Writer 编写不超过 1200 字的 Markdown，包含“本地实现、公开资料、风险、验收建议”四部分，Reviewer 审查后提交待确认的创建方案。人工确认前不要执行实际写入。
```

设置：

```
allow_web_fallback = true
```

每次出现 `waiting_confirmation` 时：

1. 点击“导出当前验收快照”。
2. 阅读 TaskPlan Markdown。
3. 确认路径、操作类型和完整正文正确。
4. 再点击确认。

最终预期：

- Researcher、Writer、Reviewer 均完成。
- 产生 approved proposal。
- dry-run 成功。
- 人工确认前文件不存在。
- 最终确认后文件才被创建。
- TaskPlan 最终为 `completed`。
- 文件存在：

```
docs\knowledge-base-acl-test\development\vpn-off-agentic-create-20260720.md
```

------

### 5. 检索刚创建的文档

`session_id`：

```
vpn-off-created-document-retrieval-20260720
```

Query：

```
请从本地知识库检索 vpn-off-agentic-create-20260720.md，并回答：该文档列出的本地实现、主要风险和验收建议分别是什么？请返回准确来源。
```

设置：

```
allow_web_fallback = false
```

预期：

- 命中新创建的文件。
- Source 的 `source_path` 指向该文件。
- 不应使用 WebSearch 填补答案。
- 答案与文件内容一致。

------

### 6. 文档多 Agent 修改

`session_id`：

```
vpn-off-document-update-20260720
```

Query：

```
请修改知识库文档 development/vpn-off-agentic-create-20260720.md。Researcher 先读取并核对现有正文；Writer 在文档末尾新增“## VPN 关闭后的复测结论”章节，写入“VPN_OFF_AGENTIC_ACCEPTANCE_20260720：关闭 VPN 后已重新执行多 Agent、Checkpoint 和人工确认验收。”；Reviewer 确认除新增章节外没有修改其他内容，然后提交待确认的更新方案。人工确认前不要执行实际写入。
```

预期：

- Researcher 读取现有文档。
- Writer 生成完整修改草稿。
- Reviewer 确认只增加一个章节。
- dry-run 显示 `update`，不是 `create`。
- 人工确认前原文件保持不变。
- 确认后新标记可以被检索。
- 原有章节仍然存在。

修改成功后再查询：

```
请从本地知识库查找 VPN_OFF_AGENTIC_ACCEPTANCE_20260720，并返回所在文件、章节和完整结论。
```

## 三、出现异常时如何保存

发生异常后，先不要立即重新测试。

### 1. 导出浏览器快照

点击：

```
导出当前验收快照
```

建议按场景重命名：

```
01-simple-rag.json
02-research-agent.json
03-checkpoint-before-interrupt.json
03-checkpoint-after-retry.json
04-document-create.json
05-created-document-retrieval.json
06-document-update.json
```

全部放到：

```
runtime\manual-agent-acceptance\vpn-off-<run_id>\
```

快照不会保存登录 Token。

### 2. 保存 TaskPlan 文件

记录页面显示的 `task_plan_id`，执行：

```
$taskPlanId = "这里替换为实际 TaskPlan ID"

Copy-Item `
  (Get-ChildItem "runtime\agent-task-plans" -Filter "*$taskPlanId*") `
  "$artifactDir\task-plans\" `
  -Force
```

需要同时保留：

```
.json
.md
```

如果页面报错时没有显示 TaskPlan ID，可以查找最新任务：

```
Get-ChildItem "runtime\agent-task-plans" -Filter "*.json" |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 5 Name, LastWriteTime
```

### 3. 保存页面截图

截图中至少包含：

- TaskPlan 状态。
- 最后一批 SSE 事件。
- 错误信息。
- 当前 Query。
- TaskPlan ID。

不要截图或提供密码、Token、API Key。

### 4. 不要清理 Checkpoint

异常任务先不要：

- 删除 TaskPlan JSON。
- 删除 PostgreSQL Checkpoint。
- 删除 staging/虚拟工作区记录。
- 重复使用相同 session 创建另一条无关任务。

这些内容是判断“从哪里恢复”和“为什么失败”的关键证据。

## 四、提供给我检查时需要的信息

你只需要发送：

```
1. 产物目录：
runtime/manual-agent-acceptance/vpn-off-20260720-xxxxxx

2. 异常场景：
例如“场景 3，中断后第一次 retry”

3. TaskPlan ID：
task_plan_xxx

4. 期望结果：
恢复后继续 Writer

5. 实际结果：
APITimeoutError / failed / 一直 running

6. VPN 状态：
已关闭

7. 开始和结束时间：
例如 19:20:10 ～ 19:22:35
```

我就可以从浏览器快照、TaskPlan JSON/Markdown 和 `backend.log` 还原完整调用链。

## 五、2026-07-22 关闭 VPN 后的缺陷定位、修复与复测

### 1. 本轮环境与产物

- VPN：关闭。
- 浏览器页面：`http://127.0.0.1:5173/rag_agent_manual_acceptance.html`。
- 后端日志与合成探针：`runtime/manual-agent-acceptance/fix-final-20260722/`。
- 用户原始失败日志：`runtime/manual-agent-acceptance/vpn-off-20260722-174543/backend.log`。
- 本轮所有失败、重试和新建 TaskPlan JSON/Markdown 均保留在
  `runtime/agent-task-plans/`，未清理 Checkpoint。
- 测试目标文件始终不存在：
  `docs/knowledge-base-acl-test/development/vpn-off-agentic-create-20260720.md`。
  因此失败任务没有绕过人工确认执行真实写入。

### 2. 检索多 Agent：非法依赖 `sqsq_1`

原始失败 TaskPlan：

```text
task_plan_20260722095255_d6dfbf706f38
ValueError: 子问题 sq_4 依赖不存在的 sqsq_1
```

原因：Planner 的 LLM 结构化输出通过了 Pydantic 字段校验，但缺少“依赖必须引用
真实子问题 ID”的图校验。`sqsq_1` 是模型生成的拼写错误。

修复：

- `agent_task_planner.py` 在保存 LLM 计划前复用 Research 图的依赖校验。
- 缺失依赖、自依赖、重复 ID 或循环依赖时，记录原因并回退规则计划。
- `test_agent_task_plan_decomposition.py` 增加 `sqsq_1` 回归。

真实复测 TaskPlan：

```text
task_plan_20260722102405_5361f0b032c8
```

结果：生成的 `sq_1/sq_2/sq_3/sq_4` 依赖合法，按两个波次执行，不再出现
依赖图异常；任务终态为 `completed_with_warnings`。复测同时发现剩余工具预算为
1 时，模型一次选择两个工具会导致整批拒绝，已改为先按剩余预算截断再执行。

最终状态：

- 非法依赖崩溃：已修复并通过真实调度与离线回归。
- 工具预算截断：已修复并通过离线回归。
- 修复后的完整 Web fallback 再验收：未完成。后续真实 Qwen 调用被阿里云
  `Arrearage` 阻断，不写成通过。

### 3. 文档多 Agent：连续暴露的四个根因

原始失败 TaskPlan：

```text
task_plan_20260722095658_565a1ccc1581
```

关闭 VPN 后重新执行时，按顺序确认了以下问题：

1. Prompt Guard 对多个召回文档逐个串行调用 LLM，放大延迟。
   已改为最多 4 路有界并行，并保持输出顺序。
2. Reviewer 达到 `ModelCallLimitMiddleware` 上限后异常穿透整个 Deep Agent 图。
   已在 Coordinator `task` 边界把专用异常转换成结构化失败 ToolMessage；取消、
   权限、持久化等任务级异常仍向上抛出。
3. Supervisor 把 Researcher、Writer、Reviewer 三个内部阶段误拆成三个最终文档
   deliverable，导致三个 Researcher 重复工作。现在 Schema、Prompt 和确定性规则均
   明确：一个目标文件只形成一个交付物，三个角色是该交付物内部阶段。
4. 文档 Deep Agent 的模型步骤、工具次数和总墙钟时间混用了同一预算。
   现改为：Coordinator 最多 12 个模型决策；每个文档子 Agent 默认最多 12 步；
   Researcher 的本地检索最多 2 次、完整文档读取最多 1 次、WebSearch 最多 2 次；
   用户 `top_k=5` 不能被模型扩大为 10；完整工作流总时限为 300 秒。

关键真实证据：

```text
task_plan_20260722105750_5d86c987e970
resume_count=1
resumed_from_checkpoint=true
```

该任务证明 `/retry` 能重新进入 PostgreSQL Checkpoint。随后：

```text
task_plan_20260722111829_2df49fa7c6bf
```

真实日志中 Researcher、Writer、Reviewer 都已完成；Coordinator 最终汇总时外部
Qwen 返回：

```text
400 Arrearage: Access denied, please make sure your account is in good standing
```

这不是 VPN 超时或本地代码异常。本轮增加了可观测性修复：模型 API 错误、文档
Worker 超时和 Coordinator 模型预算耗尽会返回持久化后的 `failed` TaskPlan，前端
可获得 `task_plan_id` 和具体错误；不再只显示通用服务器 500。

最终状态：部分通过。交付物归一化、子 Agent 完成、Checkpoint 恢复和失败隔离均有
真实证据；由于外部模型账户欠费，尚未得到 `waiting_confirmation`，也没有执行人工
确认后的真实文件写入和检索，不能写成完整通过。

### 4. LangSmith 无上传记录

确认了两个独立原因：

1. 原测试启动命令设置了：

   ```powershell
   $env:LANGSMITH_TRACING = "false"
   $env:LANGCHAIN_TRACING_V2 = "false"
   ```

   PowerShell 进程变量优先于 `.env`，因此应用启动日志明确是
   `langsmith.config.disabled`。报告中的启动命令已删除这两个覆盖项。
2. 当前 LangSmith SDK 自动生成的 UUIDv7 Run ID 无法从配置的服务端读回，返回
   `404 Run not found`；相同 Key、endpoint 和 project 使用 UUIDv4 可正常
   `create/update/read`。工程所有自定义根 Trace 都经过
   `fast_app.core.langsmith.langsmith_trace()`，现已在该集中入口显式生成 UUIDv4。

非敏感真实探针结果：

```text
langsmith_probe_uploaded=True
langsmith_probe_run_id=593385e0-3afe-4c2c-a203-cb8b38c6d480
langsmith_direct_api_uploaded=True
langsmith_direct_api_run_id=c3af8fad-bf0e-4476-910e-5221eacafa99
```

探针只包含 `synthetic-non-sensitive` 和布尔状态，不包含用户 Query、知识库正文、
路径、Token 或 ACL。真实业务 Trace 本轮未上传，因为 Codex 启动的功能验收服务
显式关闭了 tracing；用户自行启动时不要再设置两个 `false` 覆盖项。启用真实业务
tracing 会让 SDK 采集模型 Prompt/输出，应只在确认数据策略后使用。

### 5. 自动回归结果

以下检查通过：

```text
scripts/tests/document_security/test_deep_document_agent_workflow.py
scripts/tests/agent_research/test_agent_task_plan_decomposition.py
scripts/tests/document_security/test_prompt_guard_document_parallelism.py
scripts/tests/agent_research/test_agent_task_tool_loop.py
scripts/tests/agent_research/test_schema_field_descriptions.py
scripts/tests/integrations/test_langsmith_tracing.py
python -m compileall -q src/fast_app scripts/phase_15
git diff --check
```

### 6. 本轮最终结论

| 项目 | 结论 | 说明 |
|---|---|---|
| Q1 简单检索 | 通过 | 用户关闭 VPN 后已人工确认成功 |
| Q2 检索多 Agent 依赖图 | 通过 | 真实 TaskPlan 不再出现 `sqsq_1` |
| Q2 完整 Web fallback 语义 | 部分通过 | 调度已运行；最终补测受 Qwen `Arrearage` 阻断 |
| Q3 文档中断/恢复完整场景 | 未完整执行 | 本轮验证了 `/retry` 读取 Checkpoint，但未完成“中断后继续到成功写入”的全流程 |
| Q4 文档多 Agent 内部编排 | 部分通过 | 三个子 Agent 均完成，但最终汇总被外部账户阻断 |
| 文档待确认和真实写入 | 未通过/未执行 | 未达到 `waiting_confirmation`，目标文件未创建 |
| Checkpoint `/retry` | 通过 | 同一 TaskPlan 的 `resume_count=1`，确认从 Checkpoint 恢复 |
| LangSmith SDK 写入 | 通过 | 修复后的工程入口已用非敏感 Run 完成写入和读回 |

继续验收的前置条件：先恢复 DashScope/Qwen 账户可用额度，再重新执行 Q2 完整
Web fallback 和 Q4 文档创建；在这之前不应把两项外部阻断写成代码测试通过。

# 测试问题修复：

# 1、Prompt Guard 检查文档正文 chunk：

## 调用链结论

Prompt Guard 对召回文档调用 LLM 的核心链路是：

```
RAG 检索并 Rerank
→ 得到多个 RetrievedDoc（实际通常是 Chunk）
→ filter_retrieved_docs()
→ 最多 4 个文档并发执行 classify_retrieved_doc()
→ 每个文档先执行规则扫描
→ 需要时调用 LLM 分类器
→ 移除存在 Prompt Injection 风险的文档
→ 将安全文档交给回答模型
```

需要注意：这里的“4 路并行”不是创建 4 个 Agent，而是同时发送最多 4 个异步 LLM 安全分类请求。

## 一、召回文档在哪里进入 Prompt Guard

以普通非流式 RAG 为例，检索和 Rerank 完成后，会执行：

[rag_pipeline_service.py (line 736)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/rag_pipeline_service.py:736)

```
docs = await self._filter_docs_with_prompt_guard(
    docs,
    source="classic.run.documents",
)
```

`_filter_docs_with_prompt_guard()` 本身只是转发：

[rag_pipeline_service.py (line 522)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/rag_pipeline_service.py:522)

```
async def _filter_docs_with_prompt_guard(
    self,
    docs: list[RetrievedDoc],
    *,
    source: str,
) -> list[RetrievedDoc]:
    if self.prompt_guard is None:
        return docs

    return await self.prompt_guard.filter_retrieved_docs(
        docs,
        source=source,
    )
```

也就是说，真正的安全检查统一进入：

```
PromptGuardService.filter_retrieved_docs()
```

其他调用位置还包括：

- Classic 普通请求：[rag_pipeline_service.py (line 736)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/rag_pipeline_service.py:736)
- Classic 旧流式请求：[rag_pipeline_service.py (line 934)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/rag_pipeline_service.py:934)
- 结构化 SSE 请求：[rag_pipeline_service.py (line 1403)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/rag_pipeline_service.py:1403)
- RAG Agent 请求：[rag_agent_pipeline_service.py (line 1209)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/rag_agent_pipeline_service.py:1209)
- Deep Document Agent 本地知识检索：[deep_document_agent.py (line 1068)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:1068)

所以这次修改是在共享的 `PromptGuardService` 中完成的，上述调用链都会自动获得并发优化。

## 二、原来的串行处理在哪里

修改前，`filter_retrieved_docs()` 的逻辑相当于：

```
for doc in docs:
    result = await self.classify_retrieved_doc(doc, source=source)
```

这里的 `await` 位于循环内部，含义是：

```
等待文档 1 分类完成
→ 再提交文档 2
→ 等待文档 2 完成
→ 再提交文档 3
```

假设召回 10 个 Chunk，每次 LLM 分类需要 8 秒：

```
总时间约为 10 × 8 秒 = 80 秒
```

这些分类任务之间没有依赖，因此串行等待没有必要。

## 三、现在的 4 路有界并行在哪里

并行上限定义在：

[prompt_guard_service.py (line 117)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/prompt_guard_service.py:117)

```
MAX_PARALLEL_DOCUMENT_CLASSIFICATIONS = 4
```

实际并发调度位于：

[prompt_guard_service.py (line 251)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/prompt_guard_service.py:251)

```
semaphore = asyncio.Semaphore(
    MAX_PARALLEL_DOCUMENT_CLASSIFICATIONS
)

async def classify(doc: RetrievedDoc) -> PromptGuardResult:
    async with semaphore:
        return await self.classify_retrieved_doc(
            doc,
            source=source,
        )

results = await asyncio.gather(
    *(classify(doc) for doc in docs)
)
```

这三部分的职责分别是：

### 1. `asyncio.gather()`

```
results = await asyncio.gather(...)
```

把所有文档分类协程交给事件循环，让它们可以重叠执行，而不是逐个等待。

### 2. `asyncio.Semaphore(4)`

```
semaphore = asyncio.Semaphore(4)
```

它相当于只有四张“执行许可证”。

每个分类任务进入前执行：

```
async with semaphore:
```

同一时刻最多只有 4 个任务能够进入 `classify_retrieved_doc()`。其他任务虽然已经创建，但会等待许可证。

如果有 10 个文档，执行效果近似：

```
第一批：doc1、doc2、doc3、doc4
第二批：doc5、doc6、doc7、doc8
第三批：doc9、doc10
```

但只要第一批中任意一个完成，下一个等待任务就可以立即进入，并不需要整批全部完成。

### 3. `gather()` 保持输入顺序

即使完成顺序是：

```
doc3 → doc1 → doc4 → doc2
```

`results` 仍然按照传入顺序返回：

```
result1、result2、result3、result4
```

随后使用：

[prompt_guard_service.py (line 273)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/prompt_guard_service.py:273)

```
for doc, result in zip(docs, results, strict=True):
```

因此并行不会打乱原来的检索排名。

## 四、单个文档在哪里决定是否调用 LLM

单文档入口是：

[prompt_guard_service.py (line 306)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/prompt_guard_service.py:306)

```
async def classify_retrieved_doc(...):
    rule_result = self.scan_retrieved_doc(doc, source=source)

    if not self.enabled:
        return rule_result

    if rule_result.should_block:
        return rule_result

    if not self._should_call_llm_classifier():
        return rule_result

    return await self._classify_with_llm(
        text=doc.content,
        classifier_type="document",
        source=source,
        fallback_result=rule_result,
    )
```

执行顺序是：

1. 先用硬编码安全规则扫描文档。
2. 如果规则已经判定需要阻止，直接返回，不调用 LLM。
3. 检查当前 Prompt Guard 模式是否需要模型。
4. 需要时把当前 `doc.content` 交给 LLM 分类。

因此，不是所有配置都会调用 LLM：

- `mode=rule`：只执行规则，不调用 LLM。
- `mode=hybrid`：先规则，再根据配置调用 LLM。
- `mode=llm`：主要依赖 LLM 分类器。
- Prompt Guard 未启用：直接返回原文档。

## 五、真正发送 LLM 请求的位置

模型实例创建于：

[prompt_guard_service.py (line 530)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/prompt_guard_service.py:530)

```
self._classifier_model = ChatOpenAI(
    model=model_name,
    api_key=self.settings.openai_api_key,
    base_url=self.settings.openai_base_url,
    temperature=self.settings.prompt_guard_llm_temperature,
)
```

这里使用 `ChatOpenAI` 的 OpenAI 兼容接口，具体请求哪个外部模型，由 `base_url` 和 `model_name` 决定。

Prompt 构造于：

[prompt_guard_service.py (line 625)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/prompt_guard_service.py:625)

```
messages = [
    SystemMessage(content=PROMPT_GUARD_CLASSIFIER_SYSTEM_PROMPT),
    HumanMessage(
        content=PROMPT_GUARD_CLASSIFIER_HUMAN_TEMPLATE.format(
            classifier_type=classifier_type,
            source=source,
            text=text,
        )
    ),
]
```

这里的 `text` 就是前面传入的：

```
doc.content
```

真正调用模型有两个位置。

优先使用结构化输出：

[prompt_guard_service.py (line 665)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/prompt_guard_service.py:665)

```
structured_model = (
    self._get_classifier_model()
    .with_structured_output(PromptGuardResult, ...)
)

response = await structured_model.ainvoke(messages)
```

如果结构化输出失败，回退到普通 JSON 输出：

[prompt_guard_service.py (line 654)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/prompt_guard_service.py:654)

```
response = await self._get_classifier_model().ainvoke(messages)
```

所以真正的并发范围是：

```
filter_retrieved_docs()
    ├─ classify_retrieved_doc(doc1)
    │    └─ LLM ainvoke(doc1.content)
    ├─ classify_retrieved_doc(doc2)
    │    └─ LLM ainvoke(doc2.content)
    ├─ classify_retrieved_doc(doc3)
    │    └─ LLM ainvoke(doc3.content)
    └─ classify_retrieved_doc(doc4)
         └─ LLM ainvoke(doc4.content)
```

最多 4 个这样的单文档分类链路同时运行。

## 六、并行后的结果如何处理

所有分类结束后：

```
for doc, result in zip(docs, results, strict=True):
    if result.should_block:
        ...
        continue

    safe_docs.append(doc)
```

结果是：

- 安全文档进入 `safe_docs`。
- 风险文档被过滤并记录审计日志。
- 如果全部文档都被过滤，抛出 `PromptInjectionBlockedError`。
- 后续回答模型只能看到通过 Prompt Guard 的文档。

## 七、对应回归测试

并发行为由以下脚本验证：

[test_prompt_guard_document_parallelism.py (line 20)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/scripts/tests/document_security/test_prompt_guard_document_parallelism.py:20)

测试创建 10 个文档，并记录同时运行的分类任务数量，最终断言：

```
assert [item.id for item in filtered] == [
    item.id for item in docs
]

assert (
    1
    < guard.max_active
    <= MAX_PARALLEL_DOCUMENT_CLASSIFICATIONS
)
```

它验证了两件事：

1. 实际发生了并发，`max_active > 1`。
2. 并发没有超过 4。
3. 输出文档顺序仍与检索顺序一致。

# 2、Supervisor 把 Researcher、Writer、Reviewer 三个内部阶段误拆成三个最终文档
deliverable

## 一、问题为什么会发生

根因不是 Deep Agents 自动重复执行，而是 Supervisor 对 `deliverable` 的理解出现了偏差。

用户的请求中写了：

```
Researcher 汇总证据
→ Writer 编写草稿
→ Reviewer 审查
→ 最终创建一个 Markdown 文档
```

正确理解应该是：

```
一个最终交付物：Markdown 文档
└─ 内部处理阶段
   ├─ Researcher
   ├─ Writer
   └─ Reviewer
```

但原来的 Supervisor 把它理解成了：

```
三个交付物
├─ research-evidence-summary
├─ draft-markdown-content
└─ reviewed-creation-proposal
```

真实失败任务中确实生成了这三个 `deliverable`，记录在：

[多Agent浏览器真实链路测试报告.md (line 69)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/scripts/docs/多Agent浏览器真实链路测试报告.md:69)

### 1. 原来的 Schema 描述不够准确

原来的字段描述是：

```
deliverables: list[DocumentDeliverable] = Field(
    description="agentic 模式下需要完成的独立交付物；direct 模式下应为空。"
)
```

“独立交付物”没有明确说明它必须是一份最终真实文档。

对于 LLM 来说，下面三项都可以被理解为“需要完成的独立产物”：

- 研究结果
- 文档草稿
- 审查结果

因此，Schema 类型虽然正确，但业务语义有歧义。

### 2. 原来的 Supervisor Prompt 没有区分阶段与交付物

Supervisor 只被要求“拆分交付物”，却没有被明确告知：

```
Researcher、Writer、Reviewer 是工作阶段
不是三个最终交付物
```

而用户 Query 又显式列出了这三个角色，模型很自然地把它们拆成了三个有依赖关系的对象：

```
research
→ draft
→ review
```

### 3. 原来的确定性校验只能发现结构错误

原有 `_validate()` 能检查：

- `deliverable_id` 是否重复。
- 依赖是否存在。
- 是否自依赖。
- 是否循环依赖。
- 联网范围是否越权。
- 交付物数量是否超限。

但错误结果：

```
research → draft → review
```

在结构上完全合法：

- ID 不重复。
- 依赖存在。
- 没有循环。
- 都是 `create` 操作。

所以 Pydantic 和依赖校验都会通过，无法判断它们其实是同一个文档的内部阶段。

## 二、为什么会启动三个 Researcher

Deep Document Agent 的设计语义是：

```
每一个 deliverable
→ Researcher
→ Writer
→ Reviewer
→ approved_changes
```

Coordinator Prompt 明确规定“针对每个交付物”执行三个内部 Agent：

[deep_document_agent.py (line 289)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:289)

```
必须先使用 write_todos 规划，再针对每个交付物调用显式 subagent：

1. document-researcher 收集证据；
2. document-writer 生成完整草稿；
3. document-reviewer 独立审查；
```

因此，当 Supervisor 错误地产生三个 `deliverable` 时，Deep Agent 看到的是：

```
Deliverable 1：研究证据
→ 启动 Researcher
→ 启动 Writer
→ 启动 Reviewer

Deliverable 2：文档初稿
→ 启动 Researcher
→ 启动 Writer
→ 启动 Reviewer

Deliverable 3：审查方案
→ 启动 Researcher
→ 启动 Writer
→ 启动 Reviewer
```

理论上会形成三套完整流水线，而不只是三个 Agent 总调用。

`DocumentTaskExecutor` 也会为每个 `deliverable` 初始化一个 Researcher 启动事件：

[document_task_executor.py (line 241)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:241)

```
*[
    {
        "event": "agent_task_document_subagent_started",
        "deliverable_id": item.deliverable_id,
        "subagent_type": "document-researcher",
    }
    for item in decision.deliverables
],
```

所以三个错误的 `deliverable` 会直接产生三个 Researcher 启动记录。这就是重复检索和延迟增加的原因。

## 三、现在采用什么方案修复

当前采用三层修复：

```
Schema 明确语义
→ Prompt 约束模型
→ 确定性代码强制纠正
```

前两层减少模型犯错概率，第三层保证即使模型仍然犯错，也不会把错误规划交给 Deep Agent。

### 第一层：修正 Schema 字段描述

现在的 Schema 明确说明：

[document_workflow.py (line 71)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/domain/document_workflow.py:71)

```
deliverables: list[DocumentDeliverable] = Field(
    description=(
        "agentic 模式下最终要创建、更新或删除的独立文档交付物；"
        "Researcher、Writer、Reviewer 是每个交付物内部的处理阶段，"
        "禁止拆成独立交付物；direct 模式下应为空。"
    )
)
```

这个 Schema 会通过：

[document_supervisor_agent.py (line 61)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_supervisor_agent.py:61)

```
.with_structured_output(
    DocumentWorkflowDecision,
    method="function_calling",
)
```

一起提供给 Supervisor LLM。

模型现在能看到：

```
deliverable = 最终真实文档
Researcher/Writer/Reviewer = 内部阶段
```

### 第二层：强化 Supervisor Prompt

Supervisor Prompt 现在直接写明：

[document_supervisor_agent.py (line 24)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_supervisor_agent.py:24)

```
deliverable 表示最终要创建、更新或删除的一份真实文档，
不表示内部处理步骤。

Researcher、Writer、Reviewer 是每个 deliverable
都会经过的固定阶段。

绝对不能把“研究证据”“文档初稿”“审查方案”
拆成三个 deliverable。

用户只要求一个目标文件时，必须只返回一个 deliverable。
```

因此，对于：

```
请创建 development/example.md，
先研究，再写作，最后审查
```

Supervisor 应当返回：

```
{
  "deliverables": [
    {
      "deliverable_id": "document-output",
      "target_hint": "development/example.md",
      "required_capabilities": [
        "knowledge_base_search",
        "document_writing",
        "document_review"
      ]
    }
  ]
}
```

而不是三个交付物。

### 第三层：确定性规则纠正错误输出

Prompt 和 Schema 只能降低错误率，不能保证 LLM 永远正确。

因此现在增加了：

```
_collapse_internal_stage_split()
```

位置：

[document_supervisor_agent.py (line 151)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_supervisor_agent.py:151)

它在正式依赖校验前执行：

[document_supervisor_agent.py (line 104)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_supervisor_agent.py:104)

```
decision = _collapse_internal_stage_split(
    decision,
    original_query,
)
```

这个函数检查以下条件：

1. 当前是 `agentic` 模式。
2. Supervisor 返回两个或更多交付物。
3. 原始 Query 中只有一个 `.md` 或 `.txt` 目标路径。
4. 所有交付物执行相同操作，例如都是 `create`。
5. 每个交付物最多依赖一个前序交付物，呈现出类似阶段链的结构。

例如：

```
research
→ draft
→ review
```

满足这些条件后，系统不会继续信任这三个交付物，而是将其合并为一个：

```
deliverable_id = "document-output"
target_hint = "development/example.md"
objective = decision.objective
depends_on = []
```

同时把三个错误交付物中的以下信息合并去重：

```
source_requirements
required_capabilities
```

因此原来的：

```
research:
  knowledge_base_search

draft:
  document_writing

review:
  document_review
```

会变成：

```
document-output:
  required_capabilities:
    - knowledge_base_search
    - document_writing
    - document_review
```

最终 `decision.deliverables` 被替换为：

```
"deliverables": [deliverable]
```

也就是只剩一个最终文档。

## 四、为什么还要把原始 Query 传入校验

确定性规则必须知道用户究竟要求创建几个目标文件。

因此新任务执行时，Supervisor 调用会传入原始 Query：

[document_supervisor_agent.py (line 83)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_supervisor_agent.py:83)

```
return self._validate(
    decision,
    allowed_web_policy=web_policy,
    original_query=query,
)
```

任务重试时也会重新传入：

[document_task_executor.py (line 166)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:166)

```
decision = self._supervisor_agent.validate_saved_decision(
    DocumentWorkflowDecision.model_validate(saved_supervisor),
    allowed_web_policy=web_policy,
    original_query=plan.original_query,
)
```

这很重要，因为旧 Checkpoint 或 TaskPlan 里可能已经保存了错误的三个交付物。

重试时不会重新调用 Supervisor LLM，但会使用新的确定性规则重新校验并折叠旧决定。

## 五、修复后的执行结果

现在对于一个目标文档：

```
Supervisor
→ 1 个 document-output deliverable
→ 1 个 Researcher
→ 1 个 Writer
→ 1 个 Reviewer
→ 1 个创建/更新 Proposal
→ dry-run
→ 等待人工确认
```

而对于真正要求创建三份不同文档的请求：

```
development/a.md
development/b.md
development/c.md
```

原始 Query 中存在三个目标路径，不满足“只有一个目标文件”的折叠条件，因此仍然保留三个独立 `deliverable`。

## 六、回归测试

对应测试位于：

[test_deep_document_agent_workflow.py (line 379)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/scripts/tests/document_security/test_deep_document_agent_workflow.py:379)

测试手工构造错误结果：

```
research → draft → review
```

然后使用一个目标文件：

```
development/example.md
```

最后断言：

```
assert len(normalized.deliverables) == 1
assert deliverable.target_hint == "development/example.md"
assert deliverable.depends_on == []
```

并验证三个阶段需要的能力全部保留下来。

因此，现在不是单纯“提醒 LLM 不要拆错”，而是：

```
LLM 尽量正确规划
+
服务端确定性规则保证单文档任务不会形成三套重复流水线
```



# 3、UUIDv7 可能导致langsmith上传错误：

## 问题本质

这不是“UUIDv7 格式非法”，也不能直接断定所有 LangSmith 服务都不支持 UUIDv7。

目前能够确定的是：

```
当前安装的 LangSmith SDK 0.8.6
自动生成 UUIDv7 Run ID
        ↓
向当前工程配置的 LangSmith endpoint 上传
        ↓
使用相同 Run ID 调用 read_run()
        ↓
返回 404 Run not found
```

而把唯一关键变量改成 UUIDv4 后：

```
相同 API Key
相同 endpoint
相同 project
相同 create/update/read 流程
        ↓
可以成功写入并读回
```

所以当前判断是：安装的 SDK 与配置的 LangSmith 服务端之间，在 UUIDv7 Run ID 的写入、索引或读取环节存在兼容性问题。

我们没有 LangSmith 服务端内部日志，因此不能进一步断言是：

- 写入接口拒绝 UUIDv7。
- 后台批处理丢失 UUIDv7。
- 数据已经写入但索引没有识别。
- 读取接口只按照旧 UUID 格式查询。
- SDK 与服务端版本不匹配。

`404 Run not found` 只能证明：使用这个 UUIDv7 无法从服务端读回对应 Run，不能单独证明具体坏在写入端还是读取端。

## 一、UUIDv7 是哪里自动生成的

当前环境安装的是：

```
langsmith==0.8.6
```

这个版本的 `RunTree` 默认使用 UUIDv7：

```
id: UUID = Field(default_factory=uuid7)
```

位于本地依赖：

```
.venv/Lib/site-packages/langsmith/run_trees.py:253
```

工程原来的调用没有传 `run_id`：

```
trace(
    name=name,
    run_type=run_type,
    inputs=inputs,
    ...
)
```

因此执行过程是：

```
fast_app 调用 langsmith.trace()
→ 工程没有提供 run_id
→ LangSmith SDK 创建 RunTree
→ RunTree 使用 uuid7() 生成 ID
```

UUIDv7 和 UUIDv4 的主要区别是：

- UUIDv4：完全随机。
- UUIDv7：包含时间信息，基本按创建时间有序，更适合数据库索引和排序。

两者都是合法 UUID；问题是当前配置组合的兼容行为，而不是 UUIDv7 本身不符合标准。

## 二、为什么确定问题与 Run ID 有关

验收时做了控制变量测试。

首先，确保异步上传真正完成：

```
wait_for_all_tracers()
run.client.flush()
sleep(5)
```

这样排除了以下干扰：

- Run 还在 SDK 后台队列中。
- 批处理还没有发送。
- 服务端存在短暂最终一致性延迟。

然后使用同一套：

```
API Key
endpoint
project
Client
```

只改变 Run ID：

```
direct_run_id = uuid4()
```

依次调用：

```
client.create_run(...)
client.update_run(...)
client.flush()
client.read_run(direct_run_id)
```

UUIDv4 可以正常读回。因此至少可以排除：

- API Key 完全无效。
- endpoint 配置完全错误。
- project 名称错误。
- 客户端没有上传权限。
- 单纯因为没有 flush 导致读取过早。

测试探针位于：

[langsmith_synthetic_probe.py (line 14)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/runtime/manual-agent-acceptance/fix-final-20260722/langsmith_synthetic_probe.py:14)

成功结果是：

```
langsmith_probe_uploaded=True
langsmith_probe_run_id=593385e0-3afe-4c2c-a203-cb8b38c6d480

langsmith_direct_api_uploaded=True
langsmith_direct_api_run_id=c3af8fad-bf0e-4476-910e-5221eacafa99
```

这些都是 UUIDv4。

## 三、当前是如何修复的

工程没有修改第三方 LangSmith SDK，也没有全局 monkeypatch UUID 生成器。

修复放在工程统一的 Trace 入口：

[langsmith.py (line 216)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/core/langsmith.py:216)

现在显式生成 UUIDv4：

```
from uuid import uuid4
```

调用 `trace()` 时传入：

```
return trace(
    name=name,
    run_type=run_type,
    inputs=sanitize_langsmith_payload(settings, inputs),
    project_name=settings.langsmith_project,
    metadata=sanitize_langsmith_payload(settings, metadata),
    tags=tags,
    run_id=uuid4(),
)
```

关键修改在：

[langsmith.py (line 237)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/core/langsmith.py:237)

这样执行过程变成：

```
业务模块
→ fast_app.core.langsmith.langsmith_trace()
→ 工程先生成 UUIDv4
→ 将 UUIDv4 显式传给 langsmith.trace()
→ SDK 不再为该自定义 Run 自动生成 UUIDv7
```

## 四、为什么在统一入口修复

当前工程自定义的 LangSmith Trace 都应该通过：

```
fast_app.core.langsmith.langsmith_trace()
```

因此只需要修改一个公共入口，不需要在下面这些模块分别处理：

- RAG Pipeline。
- Prompt Guard。
- Retriever。
- Research Worker。
- Document Agent。
- Evaluator。
- 最终综合。

这也符合工程中的 LangSmith 规范：

```
集中管理 tracing 策略
业务模块保留具体埋点
```

需要注意：这里保证的是工程显式通过 `langsmith_trace()` 创建的 Run 使用 UUIDv4。LangChain/LangGraph SDK 自动创建的更深层子 Run 仍由对应 SDK 管理；本次真实探针验证的是工程自定义 Trace 的写入与读回，不等于已经完整验证所有自动子 Run。

## 五、如何防止以后被改回 UUIDv7

回归测试在：

[test_langsmith_tracing.py (line 56)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/scripts/tests/integrations/test_langsmith_tracing.py:56)

测试会拦截工程传给 `langsmith.trace()` 的参数，并断言：

```
assert captured["run_id"].version == 4
```

如果以后有人删除：

```
run_id=uuid4()
```

测试会失败。

## 六、当前修复的性质

这是一个集中式兼容方案：

```
SDK 默认 UUIDv7
→ 当前服务端组合读回异常
→ 工程显式使用 UUIDv4
```

它不会改变：

- Trace 名称。
- Project。
- Tags 和 metadata。
- 父子 Trace 业务关系。
- 敏感字段清理策略。
- LangChain/LangGraph 调用方式。

如果未来升级 SDK 或服务端，并验证 UUIDv7 的完整业务 Trace 可以稳定写入、查询和展示，只需要删除统一入口中的：

```
run_id=uuid4()
```

而不需要修改各业务模块。 

# 4、Agent步数配置限制：

## 总体位置

这几类限制不是集中在一个地方，而是分成三层：

```
Settings 配置层
→ Middleware 模型/工具调用计数
→ DeepDocumentAgent 业务范围与总超时
```

对应文件：

- 配置定义：[config.py (line 239)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/core/config.py:239)
- Middleware 实现：[langchain_agent_middlewares.py (line 29)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/agents/runtime/langchain_agent_middlewares.py:29)
- 文档 Agent 装配：[deep_document_agent.py (line 463)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:463)

## 一、当前预算总表

| 限制                     | 当前值       | 配置来源                                | 执行机制                             |
| ------------------------ | ------------ | --------------------------------------- | ------------------------------------ |
| Coordinator 模型调用     | 12           | `AGENT_MAX_TOOL_CALLS`                  | `ModelCallLimitMiddleware`           |
| 每个 Researcher 模型调用 | 12           | `AGENT_DOCUMENT_SUBAGENT_MAX_STEPS`     | `ModelCallLimitMiddleware`           |
| 每个 Writer 模型调用     | 12           | 同上                                    | `ModelCallLimitMiddleware`           |
| 每个 Reviewer 模型调用   | 12           | 同上                                    | `ModelCallLimitMiddleware`           |
| 每个 Agent 总 ToolCall   | 12           | `AGENT_MAX_TOOL_CALLS`                  | `ToolCallLimitMiddleware`            |
| Researcher 本地检索      | 2            | 代码固定                                | 指定工具的 `ToolCallLimitMiddleware` |
| Researcher 原文读取      | 1            | 代码固定                                | 指定工具的 `ToolCallLimitMiddleware` |
| Researcher WebSearch     | 2            | 代码固定                                | 指定工具的 `ToolCallLimitMiddleware` |
| 单次检索 `top_k`         | 不超过用户值 | 请求参数                                | `min(model_top_k, policy_top_k)`     |
| 整个 Deep Agent 墙钟时间 | 300 秒       | `AGENT_DOCUMENT_WORKER_TIMEOUT_SECONDS` | `asyncio.wait_for()`                 |

## 二、Coordinator 最多 12 个模型决策

### 配置在哪里

当前 `.env` 有：

[.env (line 181)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/.env:181)

```
AGENT_MAX_TOOL_CALLS=12
```

对应 Settings：

[config.py (line 241)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/core/config.py:241)

```
agent_max_tool_calls: int = Field(
    default=12,
    ge=0,
    le=50,
    alias="AGENT_MAX_TOOL_CALLS",
)
```

### 如何连接到 Coordinator

Coordinator 的 Middleware 在这里装配：

[deep_document_agent.py (line 468)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:468)

```
main_middleware = [
    *build_document_deep_agent_middlewares(
        self._settings,
        model_run_limit=self._settings.agent_max_tool_calls,
    ),
    ...
]
```

然后传给 Deep Agent：

[deep_document_agent.py (line 597)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:597)

```
graph = create_deep_agent(
    model=model,
    system_prompt=COORDINATOR_PROMPT,
    middleware=main_middleware,
    ...
)
```

### “模型决策”是什么意思

一次模型决策就是一次 Coordinator LLM 调用，例如：

```
第 1 次：分析任务并生成 Todo
第 2 次：决定派发 Researcher
第 3 次：读取 Researcher 结果，决定派发 Writer
第 4 次：读取 Writer 结果，决定派发 Reviewer
第 5 次：读取 Reviewer 结果
第 6 次：生成最终结构化 DocumentWorkflowResult
```

不是：

- 12 个 Token。
- 12 个 LangGraph 节点。
- 12 个子 Agent。
- 12 次工具调用。

真正执行模型计数的是：

[langchain_agent_middlewares.py (line 35)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/agents/runtime/langchain_agent_middlewares.py:35)

```
ModelCallLimitMiddleware(
    run_limit=model_run_limit,
    exit_behavior="error",
)
```

达到第 13 次模型调用时，Middleware 会阻止执行并抛出 `ModelCallLimitExceededError`。

### 当前存在一个命名问题

Coordinator 的模型调用上限目前复用了：

```
settings.agent_max_tool_calls
```

因此虽然“模型调用计数器”和“工具调用计数器”已经是两个独立 Middleware，但它们使用了同一个数值配置：

```
Coordinator 模型调用上限 = 12
Coordinator 工具调用上限 = 12
```

当前并不存在：

```
AGENT_DOCUMENT_COORDINATOR_MAX_STEPS=12
```

所以报告中的“Coordinator 最多 12 个模型决策”是正确的运行结果，但配置名称不够准确。修改 `AGENT_MAX_TOOL_CALLS` 会同时影响 Coordinator 的模型调用上限和通用 ToolCall 上限。

## 三、每个文档子 Agent 默认最多 12 步

### 配置在哪里

[config.py (line 316)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/core/config.py:316)

```
agent_document_subagent_max_steps: int = Field(
    default=12,
    ge=3,
    le=20,
    alias="AGENT_DOCUMENT_SUBAGENT_MAX_STEPS",
)
```

当前 `.env` 没有显式声明，因此使用默认值 `12`。

需要覆盖时可以增加：

```
AGENT_DOCUMENT_SUBAGENT_MAX_STEPS=12
```

### Researcher 如何使用

[deep_document_agent.py (line 526)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:526)

```
build_document_deep_agent_middlewares(
    self._settings,
    model_run_limit=(
        self._settings.agent_document_subagent_max_steps
    ),
    ...
)
```

### Writer 如何使用

[deep_document_agent.py (line 556)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:556)

```
model_run_limit=(
    self._settings.agent_document_subagent_max_steps
)
```

### Reviewer 如何使用

[deep_document_agent.py (line 578)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:578)

```
model_run_limit=(
    self._settings.agent_document_subagent_max_steps
)
```

这里的“每个子 Agent 12 步”是分别计数的：

```
Researcher：最多 12 次模型调用
Writer：最多 12 次模型调用
Reviewer：最多 12 次模型调用
```

不是三个 Agent 合计只能调用 12 次。

一个 Writer 的模型调用可能是：

```
读取研究摘要后决定读取 source.md
→ 读取后决定写草稿
→ 写入后检查草稿
→ 生成 DocumentDraftResult
```

虚拟文件工具调用之间需要模型重新判断，因此一个子 Agent 通常需要多次模型调用。

## 四、Researcher 的工具次数限制

Researcher 的专用限制在：

[deep_document_agent.py (line 531)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:531)

```
tool_run_limits={
    "knowledge_retrieval": 2,
    "knowledge_document_read": 1,
    "web_search": 2,
},
```

含义是每次 Researcher 运行期间：

```
knowledge_retrieval：最多 2 次
knowledge_document_read：最多 1 次
web_search：最多 2 次
```

### 为什么检索允许两次

设计为：

```
第一次：按照原始目标执行初始检索
第二次：证据不足时修改 Query，执行纠正检索
```

不允许模型不断换关键词重复搜索。

### 限制是怎么执行的

构造逻辑在：

[langchain_agent_middlewares.py (line 113)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/agents/runtime/langchain_agent_middlewares.py:113)

```
ToolCallLimitMiddleware(
    tool_name=tool_name,
    run_limit=run_limit,
    exit_behavior="continue",
)
```

会分别生成近似下面的 Middleware：

```
ToolCallLimitMiddleware(
    tool_name="knowledge_retrieval",
    run_limit=2,
)

ToolCallLimitMiddleware(
    tool_name="knowledge_document_read",
    run_limit=1,
)

ToolCallLimitMiddleware(
    tool_name="web_search",
    run_limit=2,
)
```

达到上限后：

- 不会实际执行超额工具调用。
- Middleware 返回失败 `ToolMessage`。
- 因为使用 `exit_behavior="continue"`，Agent 仍有机会根据已有证据生成结果，而不是让整个任务立即崩溃。

除此之外，每个 Agent 还有一个通用 ToolCall 总上限：

[langchain_agent_middlewares.py (line 44)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/agents/runtime/langchain_agent_middlewares.py:44)

```
ToolCallLimitMiddleware(
    run_limit=settings.agent_max_tool_calls,
    exit_behavior="continue",
)
```

因此 Researcher 同时受两类限制：

```
全部 ToolCall 合计不超过 12
+
knowledge_retrieval 不超过 2
knowledge_document_read 不超过 1
web_search 不超过 2
```

## 五、`top_k=5` 为什么不能被模型扩大为 10

`top_k` 不是模型步数，而是一次检索最多返回多少个 Chunk。

Researcher 工具允许模型传入：

```
knowledge_retrieval(
    query="...",
    mode="hybrid",
    top_k=10,
)
```

但用户请求进入 TaskPlan 时已经保存了：

```
top_k=5
```

构建工具时先冻结这个服务端上限：

[deep_document_agent.py (line 1044)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:1044)

```
policy_top_k = top_k
```

每次真正执行工具时计算：

[deep_document_agent.py (line 1055)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:1055)

```
effective_top_k = min(top_k, policy_top_k)
```

例如：

```
用户允许 top_k=5
模型请求 top_k=10
effective_top_k=min(10, 5)=5
```

模型可以主动缩小：

```
模型请求 top_k=3
effective_top_k=min(3, 5)=3
```

最终 Retriever 只接收处理后的值：

```
docs = await retrieve_knowledge_docs(
    ...
    top_k=effective_top_k,
)
```

这不仅控制检索数据量，也限制了后续：

- Prompt Guard 检查数量。
- Researcher 上下文长度。
- Token 消耗。
- 延迟。

## 六、整个工作流 300 秒总时限

### 配置在哪里

[config.py (line 307)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/core/config.py:307)

```
agent_document_worker_timeout_seconds: float = Field(
    default=300.0,
    gt=0.0,
    alias="AGENT_DOCUMENT_WORKER_TIMEOUT_SECONDS",
)
```

当前 `.env` 没有显式写入，因此使用默认值：

```
300 秒
```

需要显式配置时可以增加：

```
AGENT_DOCUMENT_WORKER_TIMEOUT_SECONDS=300
```

### 如何执行

整个 Deep Agent 图被包在：

[deep_document_agent.py (line 635)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:635)

```
result = await asyncio.wait_for(
    graph.ainvoke(
        graph_input,
        config=config,
        durability="sync",
    ),
    timeout=self._settings.agent_document_worker_timeout_seconds,
)
```

这个 300 秒覆盖：

```
Coordinator
+ Researcher
+ 本地检索
+ WebSearch
+ Writer
+ Reviewer
+ 可能的 Writer 修订
+ Coordinator 最终汇总
```

它不是每个 Agent 各 300 秒，而是整个 `graph.ainvoke()` 合计 300 秒。

超时后：

```
asyncio.wait_for() 取消当前等待
→ DeepDocumentAgent 捕获异常
→ Checkpoint 标记为 resumable
→ 异常交给 DocumentTaskExecutor
→ TaskPlan 保存失败原因
→ 后续 /retry 使用同一个 thread_id 恢复
```

相关异常收尾在：

[deep_document_agent.py (line 646)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:646)

## 七、“预算已经分开”的准确含义

当前已经分开的是真实计数器和作用范围：

```
Coordinator 模型调用计数
每个子 Agent 的模型调用计数
每个 Agent 的 ToolCall 总计数
Researcher 指定工具调用计数
单次检索 top_k
整个工作流墙钟时间
```

但并不是所有限制都有独立 `.env`：

- `AGENT_DOCUMENT_SUBAGENT_MAX_STEPS`：独立配置，当前使用默认值。
- `AGENT_DOCUMENT_WORKER_TIMEOUT_SECONDS`：独立配置，当前使用默认值。
- Researcher 的 `2/1/2`：代码固定。
- `top_k`：来自用户请求和 TaskPlan。
- Coordinator 模型上限：仍复用 `AGENT_MAX_TOOL_CALLS` 的值。

因此当前运行隔离已经成立，但 Coordinator 配置命名仍有进一步明确化空间。
