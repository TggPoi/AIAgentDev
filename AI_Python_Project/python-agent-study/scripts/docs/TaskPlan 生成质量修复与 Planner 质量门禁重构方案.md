# TaskPlan 生成质量修复与真实 Web 验收 Plan

## 1. 总体方案

保留当前显式 LangGraph、`AgentTaskRouter`、`AgentTaskPlanner`、TaskPlan、Research Worker 和结构化 SSE 主线，将复杂问题的规划流程调整为：

```text
Router
→ 服务端构造 PlanningContext
→ Planner 生成候选 TaskPlan
→ 确定性质量校验
→ 独立 Plan Reviewer 审查或修订
→ 再次确定性校验
→ 保存 TaskPlan
→ 等待用户确认
→ Worker 执行
```

所有 `question_decomposition` TaskPlan 都增加一次 Reviewer 模型调用。Reviewer 最多修订一次；修订后仍不合格则返回结构化错误，不保存低质量 TaskPlan，也不进入 `waiting_confirmation`。

不引入新的 Agent 框架、不替换当前 LangGraph、不新增依赖。参考项目只提供设计模式，不复制其完整运行时。

## 2. Router 与 PlanningContext

### Router 调整

保留当前 Router Prompt 的既有意图和输出结构，只修改以下边界：

- `web_research` 只表示主要目标是公开网络研究、无需同时组合知识库或业务数据库证据的任务。
- 同时要求知识库、NL2SQL、公开网络或多阶段综合分析时，路由为 `question_decomposition`。
- `structured_data_query` 仍表示可以由单次 NL2SQL 独立回答的数据库问题。
- 删除“只要出现联网关键词或 URL 就硬路由 `web_research`”的规则；明确文档操作的确定性规则继续保留。
- Router 只决定意图，不生成子任务、Tool 参数或可信 Dataset 信息。

### PlanningContext

在进入 Planner 前由服务端构造请求级上下文，包含：

- 当前可用数据源：`knowledge_retrieval`、`nl2sql_query`、`web_search`、`none`。
- Web 策略、配置状态和当前用户权限。
- 已绑定 Dataset 的 `dataset_id`、名称、业务领域和隐私类型。
- 非敏感 Dataset 的白名单视图、字段类型、COMMENT、关系和业务同义词。
- 每个数据源是否可执行以及不可执行原因。
- 最大子任务数等现有执行限制。

上下文不包含数据库连接、结果行、Scope 值或其他敏感执行事实。敏感 Dataset 的直接查询继续在 Router 前进入 NL2SQL 安全链路，不把敏感问题交给 Planner。

Planner 和 Worker 使用同一个服务端能力解析函数，避免 Planner 计划了 Worker 实际不存在的工具。

## 3. TaskPlan 数据模型与质量门禁

### 新增必填结构

TaskPlan 增加：

- `requirements`：从用户问题提取的原子需求。
- 每个 SubQuestion 增加 `covers_requirement_ids`。
- `quality_review`：记录 Reviewer 的结论、问题、修订说明和最终状态。
- `quality_issues`：保存确定性校验发现的结构化问题。

所有新增 Pydantic 公共字段必须具有 `Field(description="...")`。

新字段不设置兼容默认值。现有 `runtime/agent-task-plans/` 中的旧 JSON、Markdown 快照在实施时直接删除；不实现旧 TaskPlan 加载、升级或兼容逻辑，也不编写旧格式兼容测试。

### 确定性质量检查

模型输出后必须检查：

- Requirement ID 和 SubQuestion ID 唯一且引用有效。
- 每项 Requirement 至少被一个子任务覆盖。
- 用户明确需要的知识库、数据库或公开网络来源已被覆盖。
- `information_source_hint` 在当前 PlanningContext 中真实可用。
- 综合子任务依赖其所需证据子任务。
- DAG 无循环、无缺失依赖。
- `none` 只用于不需要外部证据的整理或综合步骤。
- 子任务不能把 Dataset 字段语义改写成其他业务概念。

不新增固定主题白名单、业务关键词修补器或 `_missing_topics` 式硬编码修复。

## 4. Planner Prompt 与 Plan Reviewer

### Planner Prompt

保留当前通用拆分规则，并补充：

- 先提取原子 Requirements，再生成 SubQuestions。
- 每个子任务必须声明覆盖哪些 Requirement。
- 数据源选择规则：
  - 项目文档、设计规范、历史报告使用 `knowledge_retrieval`。
  - 资产费用、模型面数、库存、数量等结构化事实使用 `nl2sql_query`。
  - 最新公开资料、行业建议、外部网页使用 `web_search`。
  - 仅整理已有证据的步骤使用 `none`。
- Dataset 上下文优先消除通用词歧义。例如绑定 `game_test` 时，“费用”应结合 `cost_yuan` COMMENT 理解为资产费用。
- 提供知识库与数据库、知识库与 Web、三种来源混合的正确示例。
- 禁止凭空创建当前不可用的数据源。

### Plan Reviewer

新增独立 structured-output Reviewer，输入：

- 用户原始问题。
- PlanningContext。
- Planner 生成的 requirements、subquestions 和依赖关系。
- 确定性校验结果。

Reviewer 检查：

- 是否遗漏用户要求。
- 是否发生语义漂移。
- 数据源选择是否正确。
- Dataset 字段含义是否被误解。
- 子任务是否可执行。
- 依赖关系是否支持最终综合。
- 是否存在重复或无贡献的子任务。

Reviewer 输出：

- `accepted`：候选 Plan 可直接使用。
- `revised`：返回完整修订后的 Requirements 和 SubQuestions。
- `rejected`：无法在当前能力下形成可靠 Plan，并说明原因。

Reviewer 只调用一次。修订结果必须重新经过确定性检查；不合格时返回 `AGENT_TASK_PLAN_QUALITY_REJECTED`。Planner 或 Reviewer 模型不可用时返回 `AGENT_TASK_PLANNER_UNAVAILABLE`，不再使用规则生成一个表面可用的复杂 TaskPlan。

## 5. Worker 与联网策略修复

统一 `information_source_hint` 与实际 Tool 注入规则：

- `web_search` 子任务在 `web_policy=required` 时首轮注入 WebSearch。
- `web_search` 子任务在 `web_policy=fallback` 且 Web 配置和权限可用时，也在首轮注入 WebSearch。
- 普通知识库子任务在 `fallback` 下仍保持本地检索优先，只有证据不足时才升级 Web。
- NL2SQL 子任务只在 Dataset、权限和 Tool 能力都可用时执行。
- TaskPlan 确认时重新解析能力；若权限、Dataset 或 Web 能力发生变化，在任何 Tool 调用前返回 `AGENT_TASK_PLAN_CAPABILITY_CHANGED`。
- 确认后的顶层 TaskPlan 不进行动态改写；Worker 只保留当前已有的任务内检索评价与证据补救能力。

## 6. API、SSE、React 与可观测性

现有请求入口和字段保持不变。

TaskPlan API 与 `agent_task_plan_created` SSE 事件增加：

- `requirements`
- `covers_requirement_ids`
- `quality_review`
- `quality_issues`

React 验收页必须能直接展示：

- 用户需求列表。
- 每个子任务覆盖的需求。
- 数据源选择。
- Reviewer 是否接受或修订。
- 修订原因或拒绝原因。
- Worker 和 Tool 的实际执行状态。

新增稳定错误码：

- `AGENT_TASK_PLAN_QUALITY_REJECTED`
- `AGENT_TASK_PLANNER_UNAVAILABLE`
- `AGENT_TASK_PLAN_CAPABILITY_CHANGED`

LangSmith 业务事件命名为：

- `task_planner.generate`
- `task_planner.review`
- `task_planner.validate`

不修改 deprecated `/rag/chat/stream`，不新增控制 API，不新增数据库迁移。

## 7. 自动化测试

自动化测试覆盖：

- 纯知识库复杂问题。
- 知识库与 Web 混合问题。
- 知识库与 NL2SQL 混合问题。
- 知识库、NL2SQL、Web 三来源混合问题。
- 数据源缺失或权限不足。
- Web 未配置、无权限和被禁用。
- Requirement 覆盖完整与缺失。
- Reviewer 接受、修订、拒绝。
- Reviewer 修订后仍不合法。
- Planner 或 Reviewer 模型不可用时不生成规则 TaskPlan。
- `fallback` 下显式 Web 子任务首轮获得 WebSearch。
- 普通知识库子任务在 `fallback` 下仍本地优先。
- 确认前能力变化。
- 新模型启用前旧 TaskPlan 文件已删除。
- Schema Field Description、LangSmith 和现有 Agent 回归测试。

不实现旧 TaskPlan 格式兼容测试。

## 8. 10 个真实模型 Web 测试

只测试 10 个真实复杂问题。所有问题必须通过：

`scripts/phase_15/rag_agent_manual_acceptance.html`

在内置浏览器中操作，使测试请求、SSE 事件和结果对用户可观察。不使用单模块脚本替代真实 Web 验收，也不对同一问题重复运行三次计算稳定率。

10 个问题覆盖：

1. 多主题知识库问题。
2. 需要比较和依赖关系的知识库问题。
3. 纯公开网络复杂研究。
4. 知识库与 Web 混合问题。
5. 游戏数据库与知识库混合问题。
6. 游戏数据库、知识库、Web 三来源问题。
7. Dataset 同义词和歧义问题。
8. 带有限会话上下文的复杂问题。
9. 所需数据源不可用。
10. 当前用户没有对应 Tool 或 Dataset 权限。

Web 页面必须能观察：

- Router 结果。
- Requirements。
- SubQuestions 和依赖。
- `covers_requirement_ids`。
- Reviewer 的接受、修订或拒绝。
- TaskPlan 最终状态。
- 确认后的 Worker、Tool 和证据事件。
- 失败时的稳定错误码。

10 问总体标准：

- DAG 合法率 100%。
- Requirement 覆盖率 ≥95%。
- 数据源选择正确率 ≥90%。
- 语义漂移率 ≤5%。
- 不可用数据源阻断率 100%。
- 总测试问题数固定为 10，不执行三次重复基准。

## 9. 场景 4 专项回归

重新测试此前失败的问题，TaskPlan 至少包含：

1. 使用 `web_search` 查询公开移动端 3D 资产优化建议。
2. 使用 `knowledge_retrieval` 获取《星港远征资产选型报告》中的资产事实。
3. 使用 `nl2sql_query` 查询游戏资产费用和模型面数。
4. 综合子任务依赖以上三个证据子任务，判断资产是否适合移动端并列出仍需核实的信息。

验收要求：

- 不再生成数据库服务器、云服务、存储或带宽费用子任务。
- Requirements 明确覆盖公开建议、知识库资产、资产费用、模型面数和综合判断。
- Planner 或 Reviewer 能基于 Dataset COMMENT 消除“费用”歧义。
- 确认执行后，`used_tools` 包含 `web_search`、`knowledge_retrieval`、`nl2sql_query`。
- 最终回答引用真实 Web、知识库证据和数据库 `query_id`。

此前四个 Router Web 场景也重新执行，确认敏感查询、单一数据库查询、简单 RAG 和复杂拆解路由没有回归。

## 10. 文档与 Bug 记录

新增独立记录：

`scripts/docs/TaskPlan真实模型Web测试过程与问题记录.md`

该文档持续记录：

- 环境、模型和依赖版本。
- 10 个真实复杂问题原文。
- Web 页面操作步骤和选项。
- request、trace、task_plan、query ID。
- Router、Planner、Reviewer、Worker 和 Tool SSE 事件。
- 预期与实际 Requirements、数据源和依赖。
- Reviewer 是否修订以及修订内容。
- 最终执行结果。
- 测试发现的 Bug、根因、修改位置和 Web 回归结果。
- 外部服务未启动或权限不足等阻塞项；阻塞场景不得标记为通过。

同时维护现有 NL2SQL 教程和相关测试记录，删除“复杂 query 直接绕过 Agent”或“Planner 看不到 Dataset”等已过时描述。新文档是本次 TaskPlan 质量改造的主要测试证据。

## 11. 默认约束

- 所有 `question_decomposition` Plan 都执行 Reviewer。
- Reviewer 最多修订一次；仍不合格直接拒绝。
- Requirements、覆盖关系和 Reviewer 结果全部对 API、SSE 和 React 可见。
- 旧 TaskPlan 直接删除，不兼容、不迁移。
- 真实模型验收固定为 10 个复杂问题，全部通过 Web 验收页执行。
- 单独维护新的 Web 测试和 Bug 记录文档。
- 不使用关键词白名单修复 TaskPlan。
- 不引入 `create_agent()`、Deep Agents、AutoGen 或 Grok Build 运行时。
- 不修改 `src/app`、`app`、legacy stream 或 GitLab 相关模块。
- 保留工作区现有未提交修改，不覆盖无关文件。