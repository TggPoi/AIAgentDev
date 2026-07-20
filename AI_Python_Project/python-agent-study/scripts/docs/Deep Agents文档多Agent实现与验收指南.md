# Deep Agents 文档多 Agent 实现与验收指南

## 1. 本轮实现解决了什么问题

原来的文档任务只有一个 `DocumentTaskExecutor` Tool Loop。模型可以检索、读取并提出一次
`create/update/delete` dry-run，但复杂任务中的“研究、完整起草、独立审查、按意见修订”没有明确角色边界。

现在文档链路分成两条：

```text
简单且目标明确的任务
→ 原 Document Tool Loop
→ dry-run
→ WAITING_CONFIRMATION

复杂研究或重构任务
→ DocumentSupervisorAgent
→ DeepDocumentAgent
→ Researcher / Writer / Reviewer
→ 服务端交叉校验
→ 同一个 dry-run 和确认链路
```

无论走哪条链路，模型都不能直接写知识库。

## 2. 代码入口与职责

| 文件 | 职责 |
|---|---|
| `services/agent_tasks/document_supervisor_agent.py` | 用结构化 Qwen 输出判断 direct/agentic，并拆分交付物 |
| `services/agent_tasks/deep_document_agent.py` | 装配 Deep Agents Coordinator、三个显式 SubAgent、虚拟工作区和只读工具 |
| `services/agent_tasks/deep_document_runtime.py` | 管理加密 PostgreSQL checkpoint、可信运行事实、版本与过期清理 |
| `domain/document_workflow.py` | 定义 Supervisor、Research、Draft、Review、Proposal 的 Pydantic 契约 |
| `services/agent_tasks/document_change_plan_service.py` | 把 direct/agentic 建议统一转换成现有安全 dry-run |
| `services/agent_tasks/document_task_executor.py` | 选择链路、复验模型结果、准备步骤、确认后调用确定性写入服务 |
| `services/knowledge/knowledge_document_management_service.py` | 真正修改 `.md/.txt`、同步 ES/Milvus、失败补偿 |
| `agents/runtime/langchain_agent_middlewares.py` | 复用 PII、模型调用预算、工具调用预算和日志 Middleware |
| `agents/skills/document-*` | 给 Researcher、Writer、Reviewer 的可加载操作规范 |

依赖装配在 `dependencies/rag_dependencies.py` 中完成。API 仍然只依赖统一的
`AgentTaskExecutor`，没有增加第二套确认接口。

## 3. 一次复杂 update 的真实运行顺序

### 3.1 Router 和 Planner

现有 Router 先把请求判为 `knowledge_document_management`。Planner 创建 TaskPlan，并把本次
`mode/top_k/source_path/web_policy` 保存进 `research_policy`。这些参数必须跨越“创建计划”和
“稍后执行计划”两个请求。

### 3.2 Supervisor 使用一次真实 LLM

`DocumentSupervisorAgent.decide()` 调用 Qwen，并要求返回 `DocumentWorkflowDecision`：

```text
execution_mode
objective
deliverables[]
web_policy
reason
```

LLM 负责语义判断和交付物拆分。随后 Python 规则检查：

- 交付物不超过配置上限；
- `deliverable_id` 唯一；
- 依赖存在、无自依赖、无循环；
- 模型不能扩大用户允许的联网范围；
- agentic 任务不能为空。

Supervisor 不能生成可信 `doc_id`、文件路径、ACL 或写入参数。

### 3.3 Deep Agents Coordinator 使用真实 LLM 编排 SubAgent

`DeepDocumentAgent.run()` 使用 `deepagents.create_deep_agent()` 创建一次任务隔离图，后端是
`StateBackend`。因此 `/workspace` 和 `/skills` 都是当前 LangGraph state 中的虚拟文件，不是
Windows 文件，也不是知识库目录。

当前图同时注入 PostgreSQL Checkpointer。`StateBackend.files` 仍是 LangGraph State 的一部分，
但每个节点完成后会使用 `durability="sync"` 先加密写入 PostgreSQL，再进入下一节点。因此应用
重启后可以用稳定的 `thread_id=document:{task_plan_id}` 恢复虚拟文件、Todo、消息和结构化结果。
Windows 默认 Proactor loop 不支持 psycopg 异步连接，工程使用官方同步 `PostgresSaver/PostgresStore`
加一层 `asyncio.to_thread()` 适配；LangGraph 图和模型调用仍保持异步。

Coordinator 可以调用框架内置 `task` 工具派发：

```text
document-researcher
document-writer
document-reviewer
```

项目显式覆盖并禁用了默认 `general-purpose`，避免一个通用 Agent 继承过宽职责。Deep Agents
内置的 Todo、Skills、Filesystem、SubAgent、Summarization 等 Middleware 直接复用；项目没有再写
一套同类 Middleware。

### 3.4 Researcher：LLM 选择只读工具，服务端执行

Researcher 必须按下面顺序处理 update：

```text
knowledge_retrieval
→ 从当前 ACL 结果中选择 doc_id
→ knowledge_document_read
→ 获得完整原文和 base_sha256
→ 保存到 /workspace/research/{deliverable_id}
```

这里要区分两种“读取”：

- `knowledge_document_read` 读取真实知识库，目标必须来自当前用户的检索候选；
- `read_file` 只读取虚拟工作区研究产物和草稿，不能读取真实知识库路径。

检索过滤器由当前用户身份和部门权限生成，不来自 LLM。用户取消 TaskPlan 后，取消 Middleware
会在下一次模型调用前中断；自定义外部工具也会在调用前检查取消状态。

### 3.5 Writer：LLM 生成完整候选正文

Writer 没有知识库写工具。update 时只能基于 Researcher 已授权读取的完整原文编写，输出
`DocumentDraftResult`，包括：

```text
candidate_doc_id
candidate_source_path
base_sha256
content
evidence_refs
assumptions
unresolved_points
```

当前 `.md/.txt` 更新仍是“生成完整新正文，确认后整文件替换”，不是 Markdown Chunk 级增量写入。
替换后由已有 ingestion 逻辑重新分块并替换该文档的 ES/Milvus 数据。

### 3.6 Reviewer：独立 LLM 审查

Reviewer 没有知识库写工具，也不能修改草稿。它返回：

```text
approved | revision_required | rejected
```

以及事实问题、无证据结论、缺失章节、冲突和修订说明。Coordinator 可以在预算内把
`revision_required` 交回 Writer；超过修订预算不能无限循环。

### 3.7 服务端不信任 Coordinator 的最终 Proposal

`DocumentTaskExecutor` 在生成 dry-run 前执行交叉校验：

- Proposal 必须属于 Supervisor 的交付物，操作类型必须相同；
- 一个交付物只能有一个终态，不能同时 approved/failed/skipped；
- Proposal 必须对应同一交付物最后一版 Writer 草稿；
- Proposal 内嵌 Review 必须与独立 Reviewer 最终结果完全一致；
- Reviewer 最终 verdict 必须是 `approved`；
- update 的 `doc_id/source_path/base_sha256` 必须与服务端候选和读取快照一致；
- dry-run 前重新读取真实文件，SHA 已变化则拒绝；
- 同一个 `doc_id` 不能生成重复或冲突动作。

模型即使伪造路径、SHA、批准结果或正文，也无法越过这些规则。

## 4. 人工确认和真实写入

通过审查和规则校验只会生成现有 `AgentToolStep`，TaskPlan 进入：

```text
waiting_confirmation
```

React 应展示完整正文或 diff、目标路径、风险、权限决定、失败交付物和警告。用户调用：

```text
POST /agent/task-plans/{task_plan_id}/confirm
```

后端会重新读取当前用户身份并对整批动作重新鉴权。只有全部动作通过，才调用
`KnowledgeDocumentManagementService.execute_confirmed_actions()`。

真实执行包括：

```text
版本检查
→ 修改 .md/.txt
→ 重新分块和 Embedding
→ ES/Milvus 同步
→ 成功提交
```

整批中某项失败时，已有 Service 负责补偿；Deep Agents 虚拟文件从不参与真实发布。

## 5. 部分失败如何处理

各交付物可以返回 completed、failed 或 skipped。只要至少一个交付物形成安全 dry-run，TaskPlan
仍进入一次人工确认，并在确认页明确展示失败和跳过项。确认成功后：

- 无失败或警告：`completed`；
- 有失败、跳过或警告但已有动作成功：`completed_with_warnings`；
- 没有任何可确认动作：`failed`，不会生成伪成功计划。

单个 SubAgent 普通失败不应授权其他 Agent 猜测其结论。权限、取消、TaskPlan 损坏和确认阶段写入
异常属于任务级错误。

## 6. Middleware 的复用与新增边界

复用的 LangChain Middleware：

- `PIIMiddleware`；
- `ModelCallLimitMiddleware`；
- `ToolCallLimitMiddleware`；
- 已有模型调用日志 Middleware。

复用的 Deep Agents Middleware：

- Todo；
- Skills；
- Filesystem；
- SubAgent；
- Summarization；
- Permission。

项目只增加了 Deep Agents 不可能理解的领域边界：

- TaskPlan 是否已取消；
- `task` 工具实际开始、完成或失败时，把进度原子写回 TaskPlan。

这不是重复实现通用框架能力，而是把框架运行状态连接到项目自己的任务控制 API 和 SSE。

## 7. SSE 和前端验收

`POST /agent/task-plans/{task_plan_id}/confirm/stream` 与主结构化 SSE 可以看到：

```text
agent_task_document_supervised
agent_task_document_subagent_started
agent_task_document_subagent_completed
agent_task_document_subagent_failed
agent_task_document_draft_created
agent_task_document_review_completed
agent_task_document_revision_started
agent_task_document_action_prepared
```

其中 SubAgent started/completed/failed 来自真实 `task` 工具 Middleware；其余结果事件在结构化
工作流完成后补充。旧的 `/rag/chat/stream` 仍是兼容 token 流，没有加入新控制事件。

## 8. 当前支持范围

- Agent 创建或修改：`.md`、`.txt`；
- PPTX/XLSX：继续支持导入、受控更新和检索，不允许 Agent 自由写 Office 文件；
- Markdown：确认后整文档替换，不是 Chunk 级增量更新；
- Deep Agents 工作区：是加密 PostgreSQL checkpoint 中的可恢复中间状态，不是最终文件系统；
- 真正写入、ES/Milvus 同步与回滚：继续由确定性 Service 完成。

## 9. 验收命令

```powershell
$env:PYTHONPATH = "src"
$env:LANGSMITH_TRACING = "false"
$env:LANGCHAIN_TRACING_V2 = "false"

.\.venv\Scripts\python.exe scripts\phase_15\test_deep_document_agent_workflow.py
.\.venv\Scripts\python.exe scripts\phase_15\test_deep_document_checkpoint_runtime.py
.\.venv\Scripts\python.exe scripts\phase_15\test_llm_document_management_task.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agentic_research_orchestration.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_task_sub_question_execution.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_task_tool_loop.py
```

真实 Qwen + Deep Agents 测试会把测试文档发送到外部模型：

```powershell
$env:RUN_REAL_LLM = "1"
$env:REAL_LLM_WORKER_TIMEOUT_SECONDS = "360"
.\.venv\Scripts\python.exe scripts\phase_15\test_deep_document_agent_workflow.py
```

测试使用临时 TaskPlan 目录，结束后不在 `runtime` 留下 smoke 产物。

## 10. 2026-07-18 真实验收结果

- `deepagents==0.5.4` 已安装，`pip check` 无损坏依赖。
- 真实 Qwen + Deep Agents 单交付物链路通过：122.2 秒，26 次模型调用。
- Researcher 实际执行了受控 `knowledge_retrieval` 和 `knowledge_document_read`，没有把真实知识库路径当成虚拟文件。
- TaskPlan 快照实际记录了 SubAgent started/completed 事件。
- 临时真实 Markdown 文档确认写入后：文件存在、ES 1 Chunk、Milvus 1 Chunk。
- 同一临时文档确认删除后：文件不存在、ES 0 Chunk、Milvus 0 Chunk。
- 临时文件和索引已清理，没有修改现有知识库测试文档。
- Research 多 Agent、原文档 Tool Loop、SSE Guard、LangSmith、OpenAPI、Markdown ingestion、Office ingestion 回归均通过。

真实 Deep Agents 测试使用测试 Retriever 和测试文档 Service，专门隔离验证 LLM 编排与安全 Proposal；
真实文件/ES/Milvus 测试单独验证确认后的确定性写入层。两段之间的 dry-run、权限复验、版本检查和
confirm 契约由 `test_deep_document_agent_workflow.py` 与 `test_llm_document_management_task.py` 覆盖。

# 关键代码位置：

本次文档操作多 Agent 的关键链路如下：

```
Router / Planner
→ AgentTaskExecutor
→ DocumentTaskExecutor
→ Supervisor Agent
→ Deep Agent Coordinator
→ Researcher / Writer / Reviewer
→ 服务端结果校验
→ dry-run
→ 人工确认
→ 真实知识库写入
```

需要特别注意：这条链路没有使用 LangGraph `Send`。显式子 Agent 由 Deep Agents 的 `task` 工具启动。

## 关键代码位置

| 环节                | 代码位置                                                     | 作用                                                         |
| ------------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 识别文档任务        | [rag_agent_nodes.py (line 361)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py:361) | Router 判定为 `knowledge_document_management` 后创建 TaskPlan。 |
| 创建文档 TaskPlan   | [agent_task_planner.py (line 342)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/agent_task_planner.py:342) | 保存原始任务、用户确认状态等执行信息，但不生成可信写入参数。 |
| 统一执行入口        | [agent_task_executor.py (line 42)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/agent_task_executor.py:42) | Facade，根据 `task_kind` 把任务分派给 Research 或文档执行器。 |
| 文档工作流入口      | [document_task_executor.py (line 133)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:133) | 判断使用旧的 direct Tool Loop，还是新的 agentic 多 Agent 工作流。 |
| Supervisor Agent    | [document_supervisor_agent.py (line 29)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_supervisor_agent.py:29) | 使用真实 LLM 判断任务复杂度，生成交付物、依赖关系和执行模式；随后用硬编码规则验证结构、数量和循环依赖。 |
| 多 Agent 主体       | [deep_document_agent.py (line 201)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:201) | 创建 Coordinator，并声明 Researcher、Writer、Reviewer 三个显式子 Agent。 |
| 子 Agent 真正启动点 | [deep_document_agent.py (line 352)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:352) | `create_deep_agent()` 注入 `task` 工具。Coordinator 执行 `task` 时，Deep Agents 才创建并运行对应子 Agent。 |
| 只读研究工具        | [deep_document_agent.py (line 442)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:442) | 向 Researcher 提供 ACL 过滤后的知识库检索、文档读取、可控 WebSearch 和 MCP；Writer、Reviewer没有真实知识库工具。 |
| 结构化数据契约      | [document_workflow.py (line 14)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/domain/document_workflow.py:14) | 定义 Supervisor 计划、研究结果、草稿、审查结果、修改建议和最终工作流结果。 |
| 服务端交叉验证      | [document_task_executor.py (line 1315)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:1315) | 验证 Proposal 必须来自同一交付物的最终草稿，并且 Reviewer 最终批准；防止 Coordinator 篡改正文或目标。 |
| Proposal 转 dry-run | [document_task_executor.py (line 470)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:470) | 绑定服务端 ACL 候选、目标路径和 SHA 快照；这里只准备动作，不写文件。 |
| 统一安全边界        | [document_change_plan_service.py (line 45)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_change_plan_service.py:45) | direct 和 agentic 两条链路共用同一套路径、ACL、冲突、风险、审计和 dry-run 校验。 |
| 人工确认和真实执行  | [document_task_executor.py (line 1153)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:1153) | 用户确认后重新检查当前权限，再调用知识文档管理服务进行真实写入和补偿。 |
| Middleware          | [langchain_agent_middlewares.py (line 91)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/agents/runtime/langchain_agent_middlewares.py:91) | 复用已有 PII、模型调用限制、工具调用限制和日志 Middleware。  |
| 依赖装配            | [rag_dependencies.py (line 314)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/dependencies/rag_dependencies.py:314) | 显式组装 Supervisor、DeepDocumentAgent、DocumentTaskExecutor 和统一 Facade。 |
| React/SSE 进度      | [agent_task_plan_routes.py (line 408)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/api/agent_task_plan_routes.py:408) | 将 Supervisor、子 Agent、草稿、审查和动作准备事件转换成稳定 SSE 协议。 |

**`direct` 旧工作链路**：根据 TaskPlan 的任务目标，由单 Agent 动态执行 Tool Loop。

**`agentic` deepagent工作链路**：根据 Supervisor 的交付物计划，由 Coordinator 使用 Todo List 调度多个子 Agent。



三个子 Agent 的具体职责还通过 Skill 文件约束：

- [document-research/SKILL.md (line 1)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/agents/skills/document-research/SKILL.md:1)：检索证据、读取原文、保留来源和 SHA。
- [document-writing/SKILL.md (line 1)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/agents/skills/document-writing/SKILL.md:1)：根据证据生成完整草稿。
- [document-review/SKILL.md (line 1)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/agents/skills/document-review/SKILL.md:1)：独立检查事实、范围、遗漏和冲突。

## LLM 与硬编码规则的职责

使用 LLM 的部分：

- Supervisor 判断任务复杂度并拆成交付物。
- Coordinator 调度三个子 Agent。
- Researcher 理解检索目标、选择只读工具。
- Writer 生成或修改文档草稿。
- Reviewer 审查草稿并给出批准或修订意见。

使用服务端硬编码规则的部分：

- ACL、部门权限和候选文档范围。
- 真实目标路径和 `doc_id`。
- 文档 SHA 与并发修改检查。
- Supervisor 依赖图合法性。
- Writer 草稿、Reviewer 结果和 Proposal 的一致性。
- dry-run、冲突检测、审计和人工确认。
- 真实文件、ES、Milvus 写入。

也就是说，LLM负责“理解、研究、编写和审查”，服务器负责“信任边界、权限、版本和真实执行”。

我已经在上述关键边界补充了辅助理解注释，重点解释了：

- `task` 调用何时真正启动子 Agent。
- 虚拟工作区为什么不等于真实知识库。
- 哪些数据属于服务端事实，不能信任模型输出。
- Proposal 如何绑定 ACL 候选和 SHA 快照。
- 为什么必须交叉验证 Draft、Review 和 Proposal。
- 为什么 Deep Agent 不能直接写入知识库。

本轮没有修改执行行为。验证结果：

- `compileall`：通过
- `test_deep_document_agent_workflow.py`：通过
- `test_llm_document_management_task.py`：通过
- `git diff --check`：通过

# Dry run阶段执行的工作：

Agentic 链路中，dry-run 的次数不是固定的，而是：

```
dry-run 次数
= 通过 Reviewer 审查并进入 approved_changes 的 Proposal 数量
```

例如：

- 创建 1 个文档：1 次 dry-run。
- 更新 2 个文档、创建 1 个文档：3 次 dry-run。
- 计划有 4 个交付物，但只有 2 个通过审查：最多执行 2 次 dry-run。
- Reviewer 要求 Writer 修改三轮：仍然只在最终批准后执行 1 次 dry-run。
- 交付物失败或被跳过：不执行 dry-run。

循环位置在 [document_task_executor.py (line 349)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:349)。

## 单次 dry-run 的执行过程

### 1. 读取一个批准后的 Proposal

```
for proposal in workflow.approved_changes:
    output = await self._prepare_agentic_proposal(...)
```

一个 `Proposal` 对应一个准备执行的文档操作：

```
create
update
delete
```

此时 LLM 工作已经结束。dry-run 全部由服务端规则执行，不再调用 LLM。

### 2. 确定真实操作目标

代码位于 [document_task_executor.py (line 470)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:470)。

不同操作处理不同：

#### Create

```
模型提供 filename
→ 服务端根据当前用户部门生成 target_path
→ 检查目标文件不能已经存在
→ 检查正文不能为空
```

模型不能自由指定知识库目录。

#### Update

```
模型提供 candidate_doc_id
→ 必须在 ACL 检索产生的 candidates 中
→ 从服务端候选取得真实 source_path
→ 检查模型携带的 base_sha256
→ 检查 Researcher 读取时保存的 SHA
→ 再次读取当前真实文件
→ 再次计算当前 SHA
→ 生成旧正文与新正文的 diff
```

这里进行了两层版本检查，防止 Researcher 读取文档后，其他用户又修改了该文件。

#### Delete

```
模型提供 candidate_doc_id
→ 必须在 ACL 候选集合中
→ 使用服务端候选记录的真实 source_path
→ 不允许携带正文
```

### 3. 创建 `dry_run=True` 请求

三个操作最终都进入同一个方法：

[document_change_plan_service.py (line 45)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_change_plan_service.py:45)

```
request = KnowledgeDocumentActionRequest(
    operation=operation,
    target_path=target_path,
    content=content,
    reason=reason,
    dry_run=True,
)
```

`dry_run=True` 保证不会进入真实写入入口。

### 4. 执行路径和业务校验

随后调用：

```
document_management_service.plan_action(...)
```

代码位于 [knowledge_document_management_service.py (line 95)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/knowledge/knowledge_document_management_service.py:95)。

它会执行：

- 规范化目标路径。
- 防止目录穿越。
- 限制只能处理允许的文档格式。
- 禁止修改权限规则和 sidecar 文件。
- 检查 create/update/delete 的文件存在性规则。
- 检查正文是否为空。
- 检查正文大小限制。

### 5. 读取权限事实

对于 create：

```
有主部门
→ 新文档默认属于该部门

没有主部门
→ 新文档默认只允许创建者访问
```

对于 update/delete：

```
同时读取 ES 和 Milvus 的权限 metadata
→ 两边必须都有该文档
→ 两边权限必须一致
→ 使用存储中的真实权限
```

这部分位于 [knowledge_document_management_service.py (line 483)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/knowledge/knowledge_document_management_service.py:483)。

### 6. 在内存中模拟 Chunk

dry-run 会使用现有 `MarkdownChunkBuilder` 在内存中构建 Chunk：

```
新正文或旧正文
→ MarkdownChunkBuilder
→ 计算预计影响的 Chunk 数量
```

它只计算：

- `affected_chunk_count`
- `before_hash`
- `after_hash`
- `doc_id`
- 风险等级
- 权限 metadata
- warnings

不会调用 Embedding，也不会写入 ES、Milvus或文件。

代码位置：[knowledge_document_management_service.py (line 528)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/knowledge/knowledge_document_management_service.py:528)。

### 7. 检查同一任务中的动作冲突

服务端使用 `document_actions` 记录已经准备的 `doc_id`：

```
同一个 doc_id 已经存在 update
+ 又出现 delete
→ 拒绝

两个交付物同时 update 同一个 doc_id
→ 拒绝
```

代码位置：[document_change_plan_service.py (line 83)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_change_plan_service.py:83)。

### 8. 权限决策和审计

每个 dry-run 都会：

```
构造 AgentToolCallContext
→ 调用权限服务 authorize()
→ 记录审计日志
→ DENY 时拒绝该 Proposal
```

这里需要注意：

- 不会修改知识库文件。
- 不会写 ES/Milvus。
- 但会真实写入权限决策的审计记录。

代码位置：[document_change_plan_service.py (line 90)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_change_plan_service.py:90)。

### 9. 冻结为 TaskPlan Step

dry-run 成功后，返回包含以下信息的 JSON：

```
operation
target_path
action_request
preview
permission_decision
candidate
selection_reason
diff
```

调用方将它转换成一个 `AgentToolStep`：

```
dry-run 1 → TaskPlan Step 1
dry-run 2 → TaskPlan Step 2
dry-run 3 → TaskPlan Step 3
```

然后任务进入：

```
WAITING_CONFIRMATION
```

用户确认前仍未修改真实知识库。

## 最终结论

一次 agentic 工作流可以执行多次 dry-run，但每个最终批准的 Proposal 只执行一次：

```
Researcher / Writer / Reviewer 的多轮协作
→ 不执行 dry-run

Reviewer 最终批准
→ 对该 Proposal 执行一次 dry-run

dry-run 成功
→ 生成一个待确认 TaskPlan Step

用户确认
→ 才执行一次真实文档操作
```

因此，dry-run 是“模型协作结果”转换成“可信服务端操作计划”的安全边界，而不是子 Agent 工作过程中的反复试写。

# Deepagent的虚拟工作区内容如何映射到真实数据库？

是的，但需要区分“虚拟工作区文件”和“从虚拟工作区提取出来的最终正文”。

## 1. 虚拟工作区是否在内存中

当前 Deep Agent 使用：

```
backend=StateBackend()
```

位置：[deep_document_agent.py (line 354)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:354)

`StateBackend` 将虚拟文件保存在 LangGraph State 中，例如：

```
/workspace/research/deliverable_1/source.md
/workspace/research/deliverable_1/summary.md
/workspace/drafts/deliverable_1.md
```

这些不是 Windows 上的真实文件：

```
D:\...\knowledge-base\xxx.md
```

当前没有为 Deep Agent 配置持久化 `StoreBackend` 或独立文件目录，所以 `/workspace` 本身是当前 Deep Agent 执行期间的临时状态。Deep Agent 执行结束后，代码不会直接把这些虚拟文件复制到知识库目录。

## 2. 正文如何离开虚拟工作区

关键不是“复制虚拟文件”，而是由子 Agent 把正文放入结构化结果。

### Writer 产生正文

Writer 返回：

```
DocumentDraftResult(
    deliverable_id="deliverable_1",
    operation="update",
    content="完整的新文档正文",
    ...
)
```

类型定义：[document_workflow.py (line 55)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/domain/document_workflow.py:55)

Writer 通常同时：

- 把草稿写入 `/workspace/drafts/...`，供 Reviewer 读取。
- 把完整正文放入 `DocumentDraftResult.content`，供 Coordinator 汇总。

### Coordinator 产生 Proposal

Reviewer 批准后，Coordinator 返回：

```
DocumentChangeProposal(
    deliverable_id="deliverable_1",
    operation="update",
    content="完整的新文档正文",
    review=approved_review,
    ...
)
```

Proposal 被放入：

```
DocumentWorkflowResult.approved_changes
```

位置：[document_workflow.py (line 132)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/domain/document_workflow.py:132)

因此传递过程是：

```
虚拟草稿文件
→ Writer 的 DocumentDraftResult.content
→ Coordinator 的 DocumentChangeProposal.content
→ DocumentWorkflowResult.approved_changes
→ Python 服务端对象
```

不是：

```
虚拟文件
→ 直接复制到真实知识库
```

## 3. 用户确认前正文保存在哪里

Deep Agent 结束后，`DocumentTaskExecutor` 取得：

```
proposal.content
```

然后把它放入：

```
KnowledgeDocumentActionRequest.content
```

位置：[document_task_executor.py (line 470)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:470)

dry-run 成功后，这个请求被保存到：

```
AgentToolStep.output["action_request"]
```

位置：[document_task_executor.py (line 1403)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:1403)

然后整个 TaskPlan 被保存为 runtime JSON：

[agent_task_plan_store.py (line 23)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/agent_task_plan_store.py:23)

所以更准确地说：

- `/workspace/drafts/...` 虚拟文件属于 LangGraph State，并以 AES 加密 checkpoint 持久化到 PostgreSQL。
- 最终正文会从虚拟文件提取到 Pydantic 对象。
- 最终正文随后保存在 TaskPlan JSON 的 `action_request.content` 中。
- 当前 `final_output.draft_results` 也会保存草稿正文，因此正文可能在 TaskPlan JSON 中出现不止一次。

这样即使创建计划和用户确认是两个不同的 HTTP 请求，确认接口仍然能重新取得完整正文。

## 4. 用户确认后如何取得正文

用户调用确认接口后，执行器加载 TaskPlan，然后读取：

```
action_payload = step.output.get("action_request")
```

再重建请求：

```
request = KnowledgeDocumentActionRequest.model_validate(
    {
        **action_payload,
        "dry_run": False,
    }
)
```

位置：[document_task_executor.py (line 1179)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:1179)

这里的：

```
request.content
```

就是之前从 Proposal 冻结进 TaskPlan 的完整正文。

确认阶段还会：

- 重新检查当前用户权限。
- 检查步骤仍为 `waiting_confirmation`。
- 携带用户确认时看到的 `before_hash`。
- 禁止直接复用模型设置的执行标志。
- 将 `dry_run` 在服务端改为 `False`。

## 5. 如何写入真实知识库

确认通过后调用：

```
execute_confirmed_actions(...)
```

位置：[knowledge_document_management_service.py (line 168)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/knowledge/knowledge_document_management_service.py:168)

它分成两个阶段。

### 第一阶段：预计算，不写入

执行：

```
再次检查安全路径
→ 再次检查操作条件
→ 再次生成 Preview
→ 比较 before_hash
→ 构建新旧 Chunk
→ 调用 Embedding
→ 准备回滚所需的旧正文和旧向量
```

任何一项失败，都不会修改真实文件。

### 第二阶段：真实写入

Create/Update 最终执行：

```
path.write_text(
    item.request.content or "",
    encoding="utf-8",
)
```

位置：[knowledge_document_management_service.py (line 285)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/knowledge/knowledge_document_management_service.py:285)

然后调用：

```
replace_docs_rag_stores(
    chunks=item.new_chunks,
    vectors=item.new_vectors,
)
```

把新版本 Chunk 写入：

- Elasticsearch：全文检索数据。
- Milvus：向量检索数据。

Create 还会写入权限 sidecar：

```
document.md.meta.json
```

Update 保留原来的权限 sidecar，模型不能通过修改正文改变 ACL。

如果其中一个动作失败，服务会使用旧正文、旧 Chunk 和旧向量进行补偿回滚。

## 6. 是否写入 PostgreSQL

这条 `.md/.txt` 文档操作链路不会把 PostgreSQL 当作最终文档库，但执行期间的原文、草稿和
虚拟文件会进入加密 LangGraph checkpoint；到达 `waiting_confirmation` 后释放 checkpoint，
最终待确认正文继续按现有契约保存在 TaskPlan JSON。

实际存储关系是：

| 数据                | 存储位置                                      |
| ------------------- | --------------------------------------------- |
| Deep Agent 虚拟文件 | AES 加密的 PostgreSQL LangGraph checkpoint    |
| 等待确认的完整正文  | TaskPlan runtime JSON                         |
| 知识库源文档        | `KNOWLEDGE_BASE_DIR` 下的真实 `.md/.txt` 文件 |
| 全文检索 Chunk      | Elasticsearch                                 |
| 向量和 metadata     | Milvus                                        |
| 权限 sidecar        | 源文件旁的 `.meta.json`                       |
| 权限与执行审计      | 工程现有审计存储                              |
| Office 异步导入任务 | PostgreSQL，但属于另一条 ingestion 链路       |

完整的数据迁移关系是：

```
Writer 虚拟草稿
→ DocumentDraftResult.content
→ DocumentChangeProposal.content
→ dry-run action_request.content
→ TaskPlan JSON
→ 用户确认
→ KnowledgeDocumentActionRequest.content
→ 真实 Markdown/TXT 文件
→ Chunk + Embedding
→ Elasticsearch + Milvus
```

所以，Deep Agent 不具备直接写知识库的能力；只有确认接口之后的 `KnowledgeDocumentManagementService` 才能把冻结正文写入真实文件和两个检索存储。

是的，而且当前实现中完整正文不只存在一份。



## 7. Deep Agent 执行期间

当前使用：

```
backend=StateBackend()
```

[deep_document_agent.py (line 376)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/deep_document_agent.py:376)

执行期间，以下内容完整保存在当前 LangGraph State 中：

- Researcher 读取的原始文档正文。
- `/workspace/research/.../source.md`。
- Writer 生成的完整草稿。
- `/workspace/drafts/...`。
- Writer、Reviewer、Coordinator 的结构化结果。

当前已经配置 PostgreSQL Checkpointer，因此虚拟工作区可在进程中断后按同一 `thread_id` 恢复。
服务端候选、读取 SHA 和 `record_version` 另存到 PostgreSQL Store；完整正文不在该明文事实记录中重复保存。

## Deep Agent 结束后

正文会从虚拟工作区进入 Python 结构化对象：

```
虚拟草稿
→ DocumentDraftResult.content
→ DocumentChangeProposal.content
→ DocumentWorkflowResult
```

所以即使虚拟工作区被释放，正文已经被提取到 Python 对象中。

## 等待确认时是否完整写入 JSON

会，而且目前可能重复保存。

### 第一份：全部 Writer 草稿

执行器把所有草稿版本写入：

```
plan.final_output["draft_results"]
```

代码位置：[document_task_executor.py (line 410)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:410)

如果经历两轮修改：

```
Draft v1
Draft v2
```

那么两个版本的完整 `content` 都会写进 TaskPlan。

### 第二份：最终批准正文

dry-run 的 `action_request` 包含：

```
{
    "operation": "update",
    "target_path": "...",
    "content": "最终完整正文",
    "dry_run": True
}
```

它被保存到：

```
plan.steps[n].output["action_request"]
```

位置：[document_task_executor.py (line 1418)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/document_task_executor.py:1418)

所以最终批准正文会再次出现于：

```
steps[].output.action_request.content
```

### 第三份：修改差异

Update 还会保存：

```
steps[].output.diff
```

虽然不一定是完整正文，但修改范围较大时，diff 可能接近完整文档大小。

## TaskPlan 如何写入磁盘

`AgentTaskPlanStore.save()` 执行：

```
plan.model_dump_json(indent=2)
```

然后写入 runtime JSON 文件：

[agent_task_plan_store.py (line 23)](D:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/agent_task_plan_store.py:23)

因此任务进入：

```
waiting_confirmation
```

后，完整正文已经不只是内存数据，而是明文持久化在 TaskPlan runtime JSON 中。

Markdown 人工审查视图还会保存：

- Create：完整候选正文。
- Update：完整 diff。
- Delete：候选文档证据。

## 当前实际存储关系

```
Deep Agent 执行期间：
  AES 加密 PostgreSQL LangGraph checkpoint
  ├─ 原始正文
  ├─ 研究材料
  └─ 全部草稿

等待用户确认期间：
  TaskPlan JSON
  ├─ final_output.draft_results[].content
  ├─ steps[].output.action_request.content
  └─ steps[].output.diff

用户确认后：
  实际知识库文件
  + Elasticsearch
  + Milvus
```

所以准确结论是：

> 虚拟工作区现在可通过加密 PostgreSQL checkpoint 恢复；进入等待确认阶段后，Writer 草稿和最终批准正文仍会完整写入 TaskPlan runtime JSON。checkpoint 随后释放，确认接口不再依赖 Deep Agent 工作区。

## 11. 2026-07-19 checkpoint 与断点恢复实现

启动前必须配置专用 AES-256 密钥：

```powershell
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$env:LANGGRAPH_AES_KEY_BASE64 = [Convert]::ToBase64String($bytes)
```

运行机制：

```text
FastAPI lifespan
→ 复用 PostgreSQL Saver/Store 连接池
→ Deep Agent 首次执行写入稳定 thread_id
→ 每个节点以 durability="sync" 同步 checkpoint
→ 失败保留 7 天
→ /retry 重新鉴权并从同一 thread 恢复
→ waiting_confirmation/completed/cancelled 释放 thread
```

`/retry`、`/confirm` 和同一文档 TaskPlan 的首次 agentic 执行共用进程级
`task_plan_id → asyncio.Lock`。第二个并发请求不会排队后重复运行，而是返回 HTTP 409 和
`AGENT_TASK_PLAN_BUSY`。运行事实使用 `record_version` 递增；当前单进程由锁串行更新，未来多
Worker 部署时应升级为数据库租约或真正的条件更新 CAS。

恢复前还会比较当前 ACL 指纹和已读取源文件 SHA：权限或源文件变化时删除旧 thread 并在当前
安全边界下完整重启；新格式 TaskPlan 声明 checkpoint 但数据缺失、损坏或无法解密时返回
`DOCUMENT_AGENT_CHECKPOINT_UNAVAILABLE`，不会静默重新调用模型。

### 11.1 真实模型验收结果

2026-07-19 使用工程实际 Qwen 配置执行 Deep Agent 文档工作流，结果如下：

```text
Exit code: 0
Wall time: 108.5 seconds
real_model_call_count=17
deep_document_agent_workflow=passed
```

该结果证明真实模型链路能够完成 Researcher、Writer、Reviewer 和 Coordinator
的当前工作流。checkpoint 的加密、进程重建后恢复、精确节点续跑、ACL/源文件
变化后安全重启和同任务并发保护，由 `test_deep_document_checkpoint_runtime.py` 的真实
PostgreSQL 回归测试覆盖。
