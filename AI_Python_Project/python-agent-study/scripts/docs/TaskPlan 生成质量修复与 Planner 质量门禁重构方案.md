# TaskPlan 生成质量修复与 Planner 质量门禁重构方案

## 1. 方案摘要

### Goal

修复所有 `question_decomposition` TaskPlan 的生成质量，而不是只修补 NL2SQL 场景。最终链路调整为：

```text
Router
→ 构造服务端可信 PlanningContext
→ Planner 生成候选计划
→ 确定性契约校验
→ 独立 Plan Reviewer 评审/修订
→ 最终确定性校验
→ 保存 TaskPlan
→ 等待用户确认
```

每个复杂 TaskPlan 固定增加一次 Reviewer 模型调用。一次修订后仍不合格时，不创建 `waiting_confirmation` 计划，返回结构化错误。

保留现有显式 LangGraph、TaskPlan 持久化、人工确认、依赖波次执行和 Worker 证据评估；不替换为 Grok Build、Deep Agents、AutoGen 或 Microsoft Agent Framework，也不新增依赖。

采用的成熟模式：

- LangGraph 官方的 evaluator–optimizer：生成结果后由独立评估器依据明确标准检查和修订。[LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- Magentic-One 的 Task Ledger/Progress Ledger：计划必须看到可用能力，执行过程中持续核对目标和进度。[AutoGen Magentic-One](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/magentic-one.html)
- Deep Agents 的规划、持久状态和受限工具思想，但官方也建议在固定 Agent Loop 不适合时继续使用自定义 LangGraph，因此不替换当前主线。[Deep Agents](https://github.com/langchain-ai/deepagents)
- Grok Build 是 Rust 编码 Agent Runtime/TUI，其整体架构与当前 RAG 研究任务不同，只参考任务状态管理思想，不移植实现。[xAI Grok Build](https://github.com/xai-org/grok-build)

## 2. 核心实现改造

### 2.1 修正 Router 的多来源路由边界

在现有 Router Prompt 基础上补充，不改变其他意图含义：

- `web_research`：任务只需要公开网络事实。
- `question_decomposition`：任务同时需要知识库、公开网络、Dataset 或多个相互依赖的分析步骤。
- “联网查询并结合知识库分析”不能因为出现“联网搜索”而直接降成单一 `web_research`。
- Dataset 绑定仍只表示 `nl2sql_query` 可用，不表示一定调用数据库。

删除 `_route_with_high_confidence_rules()` 中“出现联网关键词或 URL 就直接进入 `web_research`”的快捷分支，避免混合任务绕过 Planner。明确文档写操作的确定性规则继续保留。

Router 仍只决定意图，不生成子问题、工具参数、Dataset Scope 或可信执行事实。

### 2.2 新增服务端可信 PlanningContext

在进入 Planner 前构造内部 `AgentPlanningContext`，至少包含：

- 当前允许使用的信息源及用途：
  - `knowledge_retrieval`
  - `nl2sql_query`
  - `web_search`
  - `none`
- 本次请求的 `web_policy`。
- 子问题数量上限。
- 当前 Dataset 是否已绑定、是否允许查询。
- 非敏感 Dataset 的名称、领域、白名单视图、字段 COMMENT、关系和业务同义词。
- 每种来源当前是否可执行以及不可执行原因。

能力来源必须由服务端解析：

- 知识库：当前请求已生成的 ACL 检索范围。
- Web：请求允许联网、Bocha 已配置，并且当前用户具有 `agent:tool:web_search`。
- NL2SQL：API 已完成 Dataset 授权，Dataset 为非敏感，且 action 为 `query`。
- 敏感 Dataset 继续在 Router 前直达标记化 NL2SQL，不构造 Planner Context。

复用现有 `SchemaCatalog` 读取非敏感 Dataset 的字段 COMMENT，不发送数据行、连接信息、Scope ID、数据库凭据或用户权限明细。

Planner 和 Research Worker 共用同一套来源能力解析函数，防止出现“Planner 认为工具可用，Worker 实际没有注入”的漂移。

### 2.3 将 TaskPlan 改成可验证的需求契约

扩展领域模型：

```text
AgentTaskRequirement
- requirement_id
- description
- required_source_types
- expected_evidence

AgentTaskSubQuestion
- covers_requirement_ids

AgentTaskPlanQualityIssue
- code
- message
- requirement_ids
- severity

AgentTaskPlanQualityReview
- verdict: accepted | revised
- requirement_coverage
- source_alignment
- dependency_quality
- executability
- issues
- revision_count
```

`AgentTaskPlan` 增加：

```text
requirements
quality_review
```

所有字段提供 `Field(description=...)`。新增字段作为新的必填契约，不为旧 TaskPlan 提供兼容默认值。

实施新模型前，直接删除当前 `runtime/agent-task-plans/` 中已有的旧 TaskPlan JSON 和 Markdown 快照，不增加旧版本解析、迁移、回填或兼容分支。

确定性校验必须检查：

- Requirement ID 和 SubQuestion ID 唯一。
- 每项 Requirement 至少被一个子问题覆盖。
- `covers_requirement_ids` 只能引用真实 Requirement。
- 每个 Requirement 要求的来源至少由一个覆盖它的子问题提供。
- 子问题不能引用当前不可用的信息源。
- `nl2sql_query` 必须存在服务端绑定的非敏感 Dataset。
- `web_search` 必须受当前 Web 策略、配置和权限允许。
- `none` 只能用于依赖已有结果的综合判断，不能作为无依赖事实来源。
- 依赖 ID、循环依赖、最大子问题数和 DAG 结构合法。
- 不再使用固定业务主题白名单或 `_missing_topics` 式关键词补题。

### 2.4 重写 Planner 输入，而不是只追加 NL2SQL 例子

保留现有 Prompt 中这些规则：

- Planner 不重新决定 Router intent。
- 子问题必须是可回答的问题，不是 Tool TODO。
- 当前 query 优先于 history。
- Planner 不生成路径、权限、文档动作或工具参数。

新增以下内容：

- 先提取用户的原子 Requirement，再生成子问题。
- 每个子问题必须声明覆盖哪些 Requirement。
- 根据 `PlanningContext.available_sources` 选择来源，禁止编造或选择不可用来源。
- 知识库设计事实使用 `knowledge_retrieval`。
- Dataset 中的费用、库存、数量、模型面数等事实使用 `nl2sql_query`。
- 公开资料、最新规范和外部建议使用 `web_search`。
- 只依赖前置结果的比较或综合使用 `none`。
- 同一个复杂任务可以同时出现三种真实信息源。
- 不得脱离 Dataset COMMENT 重新解释业务字段。

加入至少三类完整示例：

- 纯知识库多模块分析。
- 知识库与公开网络联合研究。
- 知识库、公开网络与 Dataset 联合研究。

场景 4 中“费用”必须依据 `game_test` 的 `cost_yuan` COMMENT 和同义词解释为游戏资产费用，不得扩展为数据库服务器、存储或带宽费用。

### 2.5 增加独立 Plan Reviewer

所有 `question_decomposition` 候选计划都执行一次 Reviewer：

```text
原始 query
+ PlanningContext
+ 候选 requirements
+ 候选 sub_questions
→ Plan Reviewer
```

Reviewer 检查：

- 用户明确要求是否全部覆盖。
- 是否发生语义漂移。
- 信息源选择是否合理。
- 数据库字段是否按 Dataset 语义理解。
- 子问题是否可以独立执行。
- 依赖关系是否足以支撑最终综合。
- 是否存在重复、无意义或只描述操作的子问题。
- 是否选择了不可用工具。

Reviewer structured output只能：

- `accepted`：接受候选计划。
- `revised`：返回修订后的完整 Requirement 和 SubQuestion。
- 拒绝：没有可接受修订结果。

Reviewer 最多调用一次，不做无限反思循环。修订结果还必须重新通过确定性校验。

Planner 或 Reviewer 不可用、输出非法、语义评审拒绝时：

- 不再用通用知识库规则生成表面可执行的低质量计划。
- 返回 `AGENT_TASK_PLANNER_UNAVAILABLE` 或 `AGENT_TASK_PLAN_QUALITY_REJECTED`。
- 不持久化 TaskPlan，不进入 `waiting_confirmation`。

### 2.6 修复 Planner 与 Worker 的工具可用性漂移

修复 Web 执行逻辑：

```text
sub_question.information_source_hint == web_search
且 web_policy in {fallback, required}
且当前能力解析确认 Web 可用
→ 第一次 attempt 就注入 WebSearch
```

`fallback` 的统一语义为：

- 普通知识库子问题先本地检索，证据不足后允许 Evaluator 升级到 Web。
- Planner 已明确生成 `web_search` 子问题时，说明该子问题本身需要公开网络证据，应直接使用 Web。
- `disabled` 永远不注入 Web。

确认执行时重新解析当前工具能力并复验 TaskPlan：

- 权限被撤销。
- Dataset Grant 失效。
- WebSearch 配置被关闭。
- Dataset 被禁用。

上述情况必须在调用任何工具前终止，不得依赖创建计划时的旧能力快照。

不引入确认后的顶层动态增删子问题。TaskPlan 已经由用户确认，执行期只能使用现有 Worker Evidence Evaluator 做有限纠正检索；如需改变顶层计划，应生成新的 TaskPlan 并重新确认。

## 3. API、SSE 与可观测性

现有请求接口保持不变：

- `POST /rag/chat`
- `POST /rag/chat/stream/events`
- TaskPlan 查询、确认、恢复接口
- `dataset_id`
- `nl2sql_action`
- `allow_web_fallback`

`RagChatResponse.agent_task_plan` 和 TaskPlan 查询接口新增：

```text
requirements
sub_questions[].covers_requirement_ids
quality_review
```

现有 `agent_task_plan_created` SSE 事件同步返回这些字段，不增加新的控制接口。React 可以展示：

- 用户要求列表。
- 每个子问题覆盖的 Requirement。
- 计划使用的信息源。
- Reviewer 分数。
- 修订原因。
- 当前计划是否可以确认。

错误通过现有结构化错误通道返回：

```text
AGENT_TASK_PLANNER_UNAVAILABLE
AGENT_TASK_PLAN_QUALITY_REJECTED
AGENT_TASK_PLAN_CAPABILITY_CHANGED
```

LangSmith 增加明确名称：

```text
task_planner.generate
task_planner.review
task_planner.validate
```

Trace 记录 Requirement 数量、来源分布、质量分数、修订次数和问题 code；不记录数据库凭据、Scope、结果行或敏感 Dataset 原文。

不修改 legacy `/rag/chat/stream`，不新增数据库迁移或第三方依赖。

## 4. 测试与验收

### 自动化回归

扩展现有 Router、Planner、Research Worker 和 Schema 测试：

- 纯知识库复杂任务能够生成完整 Requirement 映射。
- 混合知识库与 Web 任务进入 `question_decomposition`。
- 非敏感 Dataset 混合任务能同时规划知识库、Web 和 NL2SQL。
- 没有 Dataset 时拒绝 `nl2sql_query`。
- Web disabled、缺少配置或缺少权限时拒绝 `web_search` 计划。
- 所有 Requirement 均有覆盖，非法引用和循环依赖被拒绝。
- Reviewer 接受、修订、拒绝三个分支均有测试。
- Reviewer 修订后的非法计划仍被拒绝。
- Planner/Reviewer 不可用时不生成规则降级 TaskPlan。
- `fallback + web_search hint` 首轮真实注入 WebSearch。
- 普通知识库子问题在 fallback 模式下仍先本地、证据不足后才联网。
- 确认时权限或工具能力变化返回 `AGENT_TASK_PLAN_CAPABILITY_CHANGED`。
- 新模型启用前旧 TaskPlan 文件已删除，测试不包含旧 TaskPlan 兼容加载。
- Pydantic 字段描述测试、LangSmith 命名测试和现有 Agent 回归全部通过。

### TaskPlan 真实模型 Web 基准

只测试 10 个真实复杂问题，覆盖：

- 多主题知识库分析。
- 比较与依赖综合。
- 公开网络研究。
- 知识库与 Web 混合。
- Dataset 与知识库混合。
- Dataset、知识库与 Web 三源混合。
- 模糊业务词和同义词。
- 多轮指代。
- 不可用来源。
- 权限拒绝。

这 10 个问题必须逐个通过 `scripts/phase_15/rag_agent_manual_acceptance.html` 发起，不使用独立模块脚本或 Mock 结果代替最终验收。

测试时保留 Web 页面和结构化 SSE 事件，使用户能够直接观察：

- Router intent。
- Requirement 列表。
- 子问题和来源选择。
- Reviewer 评分与修订原因。
- TaskPlan 状态。
- 确认后的 Worker、Tool 和证据事件。
- 失败场景的稳定错误码。

最低标准：

- 结构和 DAG 合法率 100%。
- 明确 Requirement 覆盖率 ≥95%。
- 信息源选择正确率 ≥90%。
- 明显语义漂移率 ≤5%。
- 不可执行来源阻断率 100%。
- 总计只执行上述 10 个真实复杂问题，不进行三轮重复基准。

### Web 重点验收场景

重点测试：

> 联网查询公开的移动端 3D 资产性能优化建议，并结合知识库中的《星港远征资产选型报告》，分步骤分析报告中的资产是否适合移动端项目，说明游戏资产数据库中的资产费用与模型面数还需要核实哪些问题。

TaskPlan 必须包含：

- 公开移动端优化建议：`web_search`。
- 《星港远征资产选型报告》事实：`knowledge_retrieval`。
- 游戏资产费用和模型面数：`nl2sql_query`。
- 移动端适配综合判断：依赖上述事实子问题。
- 不得出现数据库服务器、云存储、带宽或数据库基础设施成本分析。
- 页面可看到 Requirement 映射、Reviewer 分数和修订信息。

点击确认后必须验证：

```text
used_tools 包含：
knowledge_retrieval
web_search
nl2sql_query
```

最终回答必须同时引用：

- 真实公开网页证据。
- 真实知识库检索证据。
- 真实游戏资产数据库查询结果及 `query_id`。

同时重跑原有四个路由场景，确认敏感 Dataset 直达、单一数据库查询、简单 RAG 和复杂拆解没有回归。

### 测试记录文档

新增独立文档：

```text
scripts/docs/TaskPlan真实模型Web测试过程与问题记录.md
```

持续记录：

- 测试环境、模型、依赖和服务状态。
- 10 个真实复杂问题的完整输入。
- Web 页面控件选择和操作步骤。
- request、trace、task_plan、query ID。
- Router、Planner、Reviewer 和 Worker 的关键事件。
- 预期 Requirement、实际 Requirement 和覆盖结果。
- 预期来源、实际来源和工具调用结果。
- Reviewer 是否修订以及修订原因。
- 最终状态和人工结论。
- 每个 Bug 的现象、复现步骤、根因、修复位置和 Web 回归结果。
- 无法完成的外部依赖或权限问题，不得记录成测试通过。

原有 NL2SQL 教程和测试记录仍按实际改造结果更新，但这次 TaskPlan 质量测试的完整过程和 Bug 以该新文档为主。

## 5. 已确定的约束与默认决策

- 所有 `question_decomposition` 计划都执行一次 Reviewer。
- 一次修订后仍不合格则拒绝，不允许带警告进入确认。
- Requirement 映射和质量评审完整暴露给 API、SSE 和 React。
- 旧 TaskPlan 直接删除，不实现旧 Schema 兼容、迁移或回填。
- 真实模型基准只测试 10 个复杂问题，并全部通过 Web 验收页面执行。
- 新建独立文档记录可观察的测试过程、结果和 Bug。
- 不使用固定主题白名单、业务关键词补题或 NL2SQL 专用硬编码修复。
- 不替换显式 LangGraph 主线，不使用 `create_agent()` 重写当前研究编排。
- 不修改 `src/app`、`app`、legacy stream、文档写入和 GitLab 工作流。
- 保留当前工作区已有未提交改动，实施时只修改与本方案直接相关的代码和文档。