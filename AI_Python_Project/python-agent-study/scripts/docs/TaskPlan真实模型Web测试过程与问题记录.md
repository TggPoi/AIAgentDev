# TaskPlan 真实模型 Web 测试过程与问题记录

## 1. 记录目的

本文只记录 `scripts/phase_15/rag_agent_manual_acceptance.html` 中冻结的 10 个真实 Web 场景、自动化回归、执行结果和 Bug。它不是稳定率统计，也不使用 Mock LLM、Mock Retriever 或 Mock Database 替代最终验收。

本轮不启动或测试 GitLab。

## 2. 环境

- 日期：2026-08-02
- 后端：FastAPI，`http://127.0.0.1:8000`
- 验收页：`http://127.0.0.1:5173/rag_agent_manual_acceptance.html`
- Python：项目 `.venv`
- PostgreSQL：平台主库、`nl2sql_game_test`、`nl2sql_real_estate_test`
- Research TaskPlan Schema：`schema_version=2`
- 员工正向账号：`rbac_operator`，具有知识库、Web Tool 和 `game_test` Dataset 权限
- 员工反向账号：`rbac_reader`，不具有 Web Tool 和 Dataset 查询权限
- 凭据、连接 URL、数据库结果行不写入本文。

## 3. 自动化回归

执行命令：

```powershell
$env:PYTHONPATH = "src"

.\.venv\Scripts\python.exe scripts\phase_15\test_research_task_plan_v2.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agentic_research_orchestration.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_task_plan_decomposition.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_task_planning_flow.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_task_router.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_router_clarification_flow.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_task_tool_loop.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_conversation_context.py
.\.venv\Scripts\python.exe scripts\phase_15\test_structured_output_transport.py
.\.venv\Scripts\python.exe scripts\phase_15\test_schema_field_descriptions.py
.\.venv\Scripts\python.exe scripts\test_langsmith_tracing.py
.\.venv\Scripts\python.exe scripts\nl2sql\test_nl2sql_rag_routing.py
```

结果：全部通过。测试进程所在受限网络不能上传 LangSmith 数据，出现连接警告，但本地 tracing 契约断言通过。

## 4. 冻结场景与结果

所有 Query 和请求开关由验收页 `SCENARIOS` 常量冻结，测试失败后没有修改输入或预期来让结果通过。

### 4.1 场景 1：复杂知识库

- Query：根据当前知识库，分别说明混合检索、Rerank 和 Prompt Guard 的职责，并分析它们在一次 RAG 请求中的先后关系与协作边界。
- 配置：无 Dataset；`allow_direct_web=false`；`allow_web_fallback=false`。
- 账号：`rbac_operator`。
- 预期：`question_decomposition`，创建 ResearchTaskPlan，全部事实来源为 `knowledge_retrieval`。
- 实际：通过。
- TaskPlan：`task_plan_20260802043420_9759f2098929`
- 最终状态：`completed`
- Request/trace：`4f9115d3abd647209a363df373af29cd`
- 观察：3 个知识事实 Requirement 和 2 个派生 Requirement 均完成；派生子问题使用依赖结果，不进入外部 Tool Loop。

### 4.2 场景 2：简单纯 Web

- Query：请联网查询 PostgreSQL 16 官方文档中行级安全策略的作用，并给出来源链接。
- 配置：无 Dataset；`allow_direct_web=true`；`allow_web_fallback=false`。
- 账号：`rbac_operator`。
- 预期：`web_research`，不创建 TaskPlan，经过 Direct Web Capability Resolve。
- 实际：Router 和 Graph 分支通过；真实 Web Provider 返回外部服务错误，未取得最终答案。
- Request/trace：`ba23f880cb674c5d872b4feb9ce6ff7e`
- 结论：应用分流通过，外部 Web E2E 未通过。

### 4.3 场景 3：复杂纯 Web

- Query：请联网比较 PostgreSQL 16 的 RLS 与 security_invoker 视图分别解决什么问题、如何配合，并基于至少两份官方网页证据给出适用边界。
- 配置：无 Dataset；`allow_direct_web=true`；`allow_web_fallback=false`。
- 账号：`rbac_operator`。
- 预期：`question_decomposition`；所有外部事实子问题为 `web_search/direct`；至少两份网页证据；严格完成。
- 实际计划：通过。
- TaskPlan：`task_plan_20260802045810_39283afd1053`
- 计划事实：4 个 Requirement 均为 `strict`；所有外部子问题为 `web_search` 和 `web_usage=direct`；至少两份证据阈值存在。
- 执行结果：Web Provider 返回 `ExternalServiceError`，事实 Requirement 失败，依赖子问题跳过，TaskPlan 正确收敛为 `failed`，没有调用 Final Synthesis。
- 恢复 Request/trace：`71073802aa7043bf80859968986f8a90`
- 结论：计划质量通过，外部 Web E2E 未通过。

### 4.4 场景 4：知识库与 Web

- Query：结合当前知识库中的 RAG 设计与 FastAPI 官方部署资料，分析把当前服务部署为多 Worker 时，哪些状态可以保留在进程内，哪些必须外置，并说明依据。
- 配置：无 Dataset；`allow_direct_web=true`；`allow_web_fallback=false`。
- 账号：`rbac_operator`。
- 预期：`question_decomposition`，同时产生 `knowledge_retrieval` 和 `web_search/direct` Requirement。
- 实际：在受限网络后端中，Input Guard 按 fail-closed 返回 `503 EXTERNAL_SERVICE_ERROR`，没有创建 TaskPlan。
- Request/trace：`2bfa9f4e186043f4b5b53bcc8dae8a94`、`069bebb3c8a84c34a0ef7f4f4a01d817`
- 结论：安全失败语义正确；真实外网场景未完成。

### 4.5 场景 5：知识库与游戏数据库

- Query：结合《星港远征资产选型报告》和游戏资产数据库，比较已授权 3D 模型的资产费用、模型面数与设计用途，给出候选资产及依据。
- 配置：`dataset_id=game_test`；`nl2sql_action=query`；Direct Web 和 fallback 均关闭。
- 账号：`rbac_operator`。
- 预期：`question_decomposition`；知识库与 NL2SQL 严格证据；综合子问题依赖二者。
- 实际：通过。
- TaskPlan：`task_plan_20260802051816_5824cf7942af`
- NL2SQL query ID：`fd6d13fd-1d49-4453-9c3d-180fb2ce606c`
- Requirement 状态：`R1:satisfied`、`R2:satisfied`、`R3:satisfied`
- Evidence 类型：`knowledge_chunk`、`sql_query_result`、`derived_synthesis`
- 最终状态：`completed`
- 观察：数据库费用没有被解释为服务器、云存储或带宽费用；SQL Evidence 带真实 `query_id`。

### 4.6 场景 6：知识库、游戏数据库与 Web

- Query：请联网查询公开的移动端 3D 资产优化建议，并结合《星港远征资产选型报告》和游戏资产数据库中的资产费用、模型面数，判断哪些已授权 3D 模型适合移动端，同时列出仍需进一步核实的问题。
- 配置：`dataset_id=game_test`；`nl2sql_action=query`；`allow_direct_web=true`；fallback 关闭。
- 账号：`rbac_operator`。
- 首次 TaskPlan：`task_plan_20260802052434_885cc9642ea3`，已取消。
- Bug：Planner 把费用与模型面数合并为一个 Requirement，又把移动端结论与待核实项合并为一个 Requirement。来源选择正确，但不满足独立 Requirement 证据聚合基准。
- 修复：Planner/Reviewer Prompt 增加通用原子性约束；可独立验证、可独立失败的事实必须拆开，同一 SQL SubQuestion 可以覆盖多个独立 SQL Requirement。没有加入业务关键词白名单。
- 复测：因外网验收进程重启权限额度耗尽，修复后的真实模型复测未执行。
- 结论：未通过，待复测。

### 4.7 场景 7：有限会话指代

- 前置消息：本轮分析对象是《星港远征》中已授权的 3D 模型资产，重点关注费用、模型面数和移动端适配。
- 当前 Query：结合知识库继续比较这些资产，并说明哪些内容还需要公开资料验证。
- 配置：同一 session；`dataset_id=game_test`；Direct Web 开启。
- 账号：`rbac_operator`。
- 预期：Rewriter 只使用有限历史解析“这些资产”，Planner/Reviewer 使用同一个 ResolvedPlanningRequest。
- 实际：因外网验收进程额度中断，未执行。

### 4.8 场景 8：请求策略禁止 direct Web

- Query：请联网比较 PostgreSQL 16 的 RLS 与 security_invoker 视图，并综合官方证据说明二者的配合边界。
- 配置：`allow_direct_web=false`；`allow_web_fallback=false`。
- 账号：`rbac_operator`。
- 预期：`422 AGENT_TASK_SOURCE_UNAVAILABLE`。
- 实际：因外网验收进程额度中断，未执行。

### 4.9 场景 9：无 Web Tool 权限

- Query：请联网查询 PostgreSQL 16 官方文档中行级安全策略的作用，并给出来源链接。
- 配置：Direct Web 开启。
- 账号：`rbac_reader`，没有 `agent:tool:web_search`。
- 预期：`403 TOOL_PERMISSION_DENIED`。
- 实际：因非敏感请求必须先通过真实 Input Guard，而外网验收进程额度中断，未执行。没有用关闭 Guard 的方式绕过安全主线。

### 4.10 场景 10：无 Dataset Grant

- Query：查询《星港远征》中已授权 3D 模型资产的费用和模型面数。
- 配置：`dataset_id=game_test`；`nl2sql_action=query`；Direct Web 和 fallback 均关闭。
- 账号：`rbac_reader`。
- 预期：403，不创建 TaskPlan，不调用普通模型。
- 实际：通过。
- 错误：`403 NL2SQL_PERMISSION_DENIED`
- Request/trace：`5393158fe72a4a26ba4989b205f606b8`
- 观察：无 TaskPlan，权限拒绝发生在敏感/绑定 Dataset 前置分流中。

## 5. 本轮发现并修复的 Bug

1. Planner structured output 对非 SQL Evidence 错误设置 `requires_query_id=true`：补充明确 Prompt 契约。
2. 非 SQL Evidence 错误填写 `required_attributes`：补充只有 SQL Evidence 允许字段属性的 Prompt 契约。
3. Reviewer 在 `accepted` 时仍返回 revised 字段：明确 accepted/rejected 必须返回 `null`。
4. Research `final_output=None` 被旧兼容代码当作 `dict` 调用 `.get()`：API 和回答构造按 TaskPlan 类型读取。
5. `information_source_hint=none` 仍进入外部 Tool Loop：改为基于依赖结果执行派生综合。
6. allow-partial Requirement 零合法 Evidence 时仍可能进入综合：任一 `failed` Requirement 均禁止 Final Synthesis。
7. `route_after_loop_check()` 漏掉 `direct_web`：补齐 Graph 路由并增加断言。
8. “至少两份证据”的计划被生成 `allow_partial`：Planner/Reviewer 默认 strict，并明确“结合、必须、需要、至少 N”不得降级。
9. Research 失败终态 SSE 再次读取空 `final_output`：按 Research 模型安全读取，回归通过。
10. 三来源专项 Requirement 过度合并：新增通用原子性审查规则，待真实模型复测。

## 6. 指标

本轮只对已实际生成的计划计算计划质量，不把未执行场景计为成功，也不把 10 问单次执行解释为稳定率。

- 完整 E2E 通过率：`3 / 10 = 30%`，通过场景为 1、5、10。
- DAG 合法率：已保存的有效 ResearchTaskPlan 均通过确定性 DAG 校验。
- 场景 3 来源策略：全部 Web Requirement 和 SubQuestion 来源正确；实际执行被外部服务阻断。
- 场景 5 Requirement 覆盖率：`3 / 3 = 100%`。
- 场景 5 Requirement 来源策略正确率：`2 / 2 = 100%`（只统计需要外部来源的 Requirement）。
- 场景 5 SubQuestion 来源执行正确率：`2 / 2 = 100%`（综合 `none` 不进入分母）。
- 不可用来源阻断：本轮观察到的 Dataset 权限不足、Input Guard 技术失败均被阻断，没有静默降级。

由于 4、6、7、8、9 未完成，不能给出整个 10 问集合的 Requirement 覆盖率、来源正确率或语义漂移率。完成剩余真实 Web 复测后再计算总指标，且不得修改本节之前冻结的 Query 和人工预期。

## 7. 待复测项

1. 恢复允许外部模型和 Web Provider 的本地后端进程。
2. 从场景 4 开始补测 4、6、7、8、9。
3. 场景 6 必须确认费用与模型面数拆为独立 Requirement，同一个 NL2SQL SubQuestion 可以同时覆盖二者。
4. 场景 8 必须由请求策略返回 422；不能把 `allow_web_fallback=false` 误当成 direct Web 禁止。
5. 场景 9 必须在 Input Guard 正常可用时验证真实 403 Tool 权限拒绝。
6. 记录补测后的 TaskPlan/request/trace/query ID 和最终总指标。

## 8. 2026-08-03 最终代码补测：TaskPlan 质量评估

### 8.1 本轮评估规则

本轮不是以“成功创建 TaskPlan”作为通过标准。每个 Research TaskPlan 在确认执行前均人工检查以下六项：

1. **Requirement 覆盖与原子性**：用户可独立验证、可独立失败的事实是否拆成独立 Requirement。
2. **来源策略**：`SourcePolicy`、SubQuestion `information_source_hint` 和服务端生成的 `web_usage` 是否与用户要求一致。
3. **Evidence 契约**：证据类型、最小数量、`query_id` 和 SQL `required_attributes` 是否足以分别证明对应 Requirement。
4. **依赖与可执行性**：事实子任务是否先执行，综合子任务是否使用 `none` 并依赖必要事实。
5. **CompletionPolicy**：用户明确要求的内容是否保持 `strict`，没有为了完成率降级为 `allow_partial`。
6. **语义一致性**：是否遗漏用户要求、擅自扩大范围、改变数据含义或把一种来源替换成另一种来源。

质量不合格的计划直接取消，不确认执行。质量合格的计划才进入 Worker；因此“计划质量”和“运行结果”是两个独立结论。

### 8.2 汇总结论

| 场景 | Router/前置行为 | 是否生成计划 | TaskPlan 质量 | 是否执行 | 最终结论 |
| --- | --- | --- | --- | --- | --- |
| 1 复杂知识库 | `question_decomposition` | 是 | **不通过** | 否，已取消 | 派生 Requirement 被错误设计为新的知识库检索；Reviewer 漏检 |
| 2 简单纯 Web | `web_research` | 否，符合设计 | 不适用 | 是 | 分流通过，来源和答案质量不通过 |
| 3 复杂纯 Web | `question_decomposition` | 是 | **通过，带 warning** | 是 | 计划结构合格；Evidence 语义充分性存在运行期 Bug |
| 4 知识库与 Web | `question_decomposition` | 是 | **通过** | 是 | 计划质量通过；知识库 Worker 超时使任务失败 |
| 5 知识库与游戏数据库 | `question_decomposition` | 是 | **不通过** | 否，已取消 | 费用、面数、用途被合并成一个 SQL Requirement |
| 6 三来源专项 | `question_decomposition` | 是 | **不通过** | 否，已取消 | 6 个冻结原子需求被合并为 4 个；Reviewer 漏检 |
| 7 有限会话指代 | `question_decomposition` | 是 | **不通过** | 否，已取消 | 指代解析正确，但新增未要求的平均值查询并合并 SQL 事实 |
| 8 禁止 direct Web | 错误进入规划 | 是，违反预期 | **不通过** | 否，已取消 | 应返回 422，却把 Web 来源静默替换成知识库 |
| 9 无 Web Tool 权限 | 前置权限拒绝 | 否，符合设计 | 不适用 | 否 | 通过，返回 `TOOL_PERMISSION_DENIED` |
| 10 无 Dataset 权限 | Dataset 前置拒绝 | 否，符合设计 | 不适用 | 否 | 通过，返回 `NL2SQL_PERMISSION_DENIED` |

本轮不能得出“10 个场景全部通过”。仅按 TaskPlan 生成质量统计，实际生成 Research TaskPlan 的 7 个场景中：

- 质量通过：场景 3、4，共 `2 / 7`。
- 质量不通过：场景 1、5、6、7、8，共 `5 / 7`。
- Reviewer 对上述 5 份低质量计划均错误给出 `accepted`，说明 Reviewer 当前没有形成有效质量门禁。

### 8.3 场景 1：复杂知识库

- TaskPlan：`task_plan_20260803100145_04bf20347c3c`
- 实际路由：`question_decomposition`
- 质量结论：**不通过**。
- 正确部分：混合检索、Rerank、Prompt Guard 三个事实 Requirement 分别拆分，来源均为 `knowledge_retrieval`。
- 问题：执行先后关系和协作边界属于基于前三项事实的派生分析，应使用 `source_policy.mode=none`、`derived_synthesis` 和 `information_source_hint=none`。实际计划却把两项都设计成新的 `knowledge_retrieval` Requirement。
- Reviewer：`accepted`，所有检查项均为 `pass`，未发现该错误。
- 处理：未确认执行，已取消。取消 request/trace：`e2c99f31f4604711aa9761cdba80a3ff`。

### 8.4 场景 2：简单纯 Web

- 实际路由：`web_research`。
- TaskPlan：未创建，符合简单 Web 分支设计。
- Bocha 额度补充后已重新执行。
- 分流质量：通过。
- 答案质量：**不通过**。
- 实际来源包含豆丁网、华为云社区、SQL Server 文档和旧版 PostgreSQL 文章，没有满足“PostgreSQL 16 官方文档”的来源约束。
- 最终答案为“当前知识库中没有足够信息回答这个问题”，既没有回答 RLS 的作用，也没有提供所要求的官方来源链接。
- 结论：Direct Web Capability Resolve 和 Router 分支正常，但 Direct Web 查询约束、来源筛选及答案生成不合格。

### 8.5 场景 3：复杂纯 Web

- TaskPlan：`task_plan_20260803103351_163c7cb835b7`
- 实际路由：`question_decomposition`
- 质量结论：**通过，带 warning**。
- 正确部分：RLS、`security_invoker`、二者配合、至少两份官方证据边界被拆为 4 个 strict Requirement；4 个事实子问题均为 `web_search/direct`；最后一项 Evidence 阈值为 2。
- Warning：前两个子问题的 reason 允许“官方文档或权威技术文章”，弱于官方资料偏好；不过用户的“至少两份官方网页证据”明确约束的是适用边界 Requirement，因此本项不作为计划拒绝原因。
- 执行观察：Worker 为 `security_invoker` 子问题返回“当前知识库中没有足够信息回答这个问题”，但 Evidence Validator 因收到了格式合法的 Web EvidenceRefs，Requirement 仍被标为 `satisfied`。
- Bug：Typed Evidence 当前主要验证 URL、来源类型和引用结构，未验证 Evidence 内容是否真的支持 Requirement，也未把 Worker 明确的“不足”结论与 Requirement 状态关联。该问题可能让语义无效的证据通过 Aggregator。
- 最终状态：`completed`；4 个 SubQuestion 的执行状态实际全部为 `partial`，4 个 strict Requirement 却全部为 `satisfied`，Final Synthesis 仍被调用。
- 最终答案虽然主动写出“部分满足与限制”，但 TaskPlan 没有进入 `completed_with_warnings`，这进一步证明 Worker、Requirement 和 TaskPlan 三层状态语义不一致。因此场景 3 只判定为“TaskPlan 生成质量通过”，完整 E2E 执行质量仍不通过。

### 8.6 场景 4：知识库与 Web

- 首次使用旧 session：`taskplan-v2-e2e-4`。
- 首次结果：错误返回 `AGENT_TASK_PLANNING_CONTEXT_UNRESOLVED`，把“当前知识库”误判为无法解析的历史指代。
- 隔离复测 session：`taskplan-v2-e2e-4-20260803b`。
- TaskPlan：`task_plan_20260803101559_ddbd936a9ec8`
- 质量结论：**通过**。
- 计划结构：知识库 RAG 状态事实使用 `knowledge_retrieval`；FastAPI 多 Worker 官方资料使用 `web_search/direct`；“可留进程内”和“必须外置”分别作为两个 `none + derived_synthesis` strict Requirement，均依赖前两个事实子任务。
- 执行结果：Web Requirement 满足；知识库 Worker 返回 `WORKER_TIMEOUT`；两个综合子问题因依赖失败而跳过；TaskPlan 正确收敛为 `failed`，没有生成伪完整答案。
- Bug：冻结场景重复使用固定 session 时会受到旧对话污染，导致本应无历史快速通过的 Query 被 Rewriter 错误拒绝。真实 E2E 应使用隔离 session 或在测试前清理对应会话。

### 8.7 场景 5：知识库与游戏数据库

- TaskPlan：`task_plan_20260803102040_1bdfb11da7c2`
- 质量结论：**不通过**。
- 正确部分：知识库事实、NL2SQL 事实和最终综合分别使用 `knowledge_retrieval`、`nl2sql_query`、`none`；依赖关系正确；SQL Evidence 要求真实 `query_id`。
- 问题：资产费用、模型面数、设计用途被合并为同一个 SQL Requirement。若查询只返回费用却缺少面数，系统只能让整组一起失败，无法分别表达各业务事实是否满足。
- Reviewer：`accepted`，未识别 Requirement 原子性不足。
- 处理：未确认执行，已取消。

### 8.8 场景 6：三来源专项

- TaskPlan：`task_plan_20260803102231_fff9e0bfe2e2`
- 质量结论：**不通过**。
- 正确部分：没有把“资产费用”理解成数据库服务器、云存储或带宽费用；Web、知识库、NL2SQL 和综合来源选择正确；WebUsage 为 `direct`。
- 冻结人工基准要求至少 6 个原子 Requirement：公开移动端建议、知识库报告事实、费用、模型面数、适配判断、待核实问题。
- 实际只生成 4 个：费用与模型面数被合并；适配判断与待核实问题被合并。
- Reviewer：`accepted`，未执行原子性和独立失败检查。
- 处理：未确认执行，已取消。

### 8.9 场景 7：有限会话指代

- 前置消息在同一 session 中先执行，真实 NL2SQL 返回角色资产01和角色资产06。
- 当前 TaskPlan：`task_plan_20260803102608_a4086fe0af1e`
- 指代解析结论：**通过**。`这些资产` 被解析为《星港远征》的角色资产01和角色资产06，费用、模型面数和移动端适配上下文均保留。
- TaskPlan 质量：**不通过**。
- 问题一：Planner 擅自新增“查询项目 3D 模型平均费用和平均面数”Requirement，用户没有要求项目均值基准，属于任务范围扩张。
- 问题二：费用、模型面数、用途仍被合并为同一个 SQL Requirement。
- Reviewer：`accepted`，未发现范围扩张或原子性错误。
- 处理：未确认执行，已取消。

### 8.10 场景 8：请求策略禁止 direct Web

- TaskPlan：`task_plan_20260803102858_4d531affcaab`
- 预期：请求明确要求联网，但 `allow_direct_web=false`，应返回 `422 AGENT_TASK_SOURCE_UNAVAILABLE`，不得保存计划。
- 实际：**不通过**。系统仍保存 TaskPlan，并把全部 Web Requirement 和 SubQuestion 静默替换成 `knowledge_retrieval/not_used`。
- 这不是可接受的降级：知识库证据不能替代用户明确要求的官方网页证据。
- Reviewer：`accepted`，未发现来源语义被替换。
- 处理：未确认执行，已取消。

### 8.11 场景 9：无 Web Tool 权限

- 账号：`rbac_reader`，真实 `/auth/me` 显示无全局 Web Tool 权限。
- 实际：通过。
- 错误：`TOOL_PERMISSION_DENIED`
- Request/trace：`39344b65450b4e939d362be7d659f64e`
- 观察：未创建 TaskPlan，未调用 Web Provider。

### 8.12 场景 10：无 Dataset Grant/功能权限

- 账号：`rbac_reader`。
- 实际：通过。
- 错误：`403 NL2SQL_PERMISSION_DENIED`
- Request/trace：`38647fa7e86e4cef9fecfccbc19cf2ec`
- 观察：未创建 TaskPlan，拒绝发生在绑定 Dataset 的前置权限链路。

## 9. 2026-08-03 新发现的 Bug

1. **Reviewer 对 Requirement 原子性没有实际门禁作用**：场景 5、6、7 均重现费用/面数合并，Reviewer 全部 `accepted`。
2. **Reviewer 未识别派生分析的来源类型**：场景 1 把先后关系和协作边界错误设计为新知识库检索，Reviewer 仍通过。
3. **请求策略禁止 direct Web 时静默换源**：场景 8 应返回 422，却创建了纯知识库计划。
4. **Reviewer 未识别范围扩张**：场景 7 擅自增加项目平均费用和平均面数查询。
5. **Evidence 语义充分性缺失**：场景 3 中 Worker 明确回答“信息不足”，Requirement 仍因 URL 形式合法而被标为 satisfied。
6. **简单 Direct Web 缺少官方来源约束**：场景 2 把非官方、错误技术栈网页作为结果，且答案错误使用“知识库不足”模板。
7. **固定 session 被旧历史污染**：场景 4 使用原冻结 session 时出现不必要的指代澄清；隔离 session 后同一 Query 正常生成高质量计划。
8. **Knowledge Worker 超时**：场景 4 的知识库子问题在真实执行中 `WORKER_TIMEOUT`，TaskPlan 虽正确失败收敛，但无法完成 E2E。

## 10. 补测后的质量指标

本节只统计本轮 2026-08-03 实际观察，不覆盖 2026-08-02 的历史记录。

- Research TaskPlan 生成数：7（场景 1、3、4、5、6、7、8）。
- 人工质量通过数：2（场景 3、4）。
- TaskPlan 人工质量通过率：`2 / 7 = 28.57%`。
- Reviewer 对低质量计划的阻断率：`0 / 5 = 0%`。
- 权限负向场景阻断率：`2 / 2 = 100%`（场景 9、10）。
- 指代解析正确率：本轮仅 1 个冻结指代场景，`1 / 1 = 100%`；这不是稳定率统计。
- 简单 Web 分流正确率：`1 / 1 = 100%`；简单 Web 最终答案质量：`0 / 1 = 0%`。
- 三来源专项 Requirement 覆盖率：冻结人工 Requirement 共 6 个，计划完整独立覆盖 4 个，`4 / 6 = 66.67%`。
- 语义漂移/范围扩张：场景 7 的 4 个 SubQuestion 中 1 个为未请求的项目均值查询，按该场景统计为 `1 / 4 = 25%`。

由于场景 1、5、6、7、8 的 TaskPlan 质量不合格，本轮不能宣称 Plan 的代码工作已经完成，也不能把自动化测试通过等同于真实模型计划质量通过。

## 11. 2026-08-03 未通过场景根因审计（仅诊断）

本节只记录已经能够由 Web 页面、TaskPlan JSON 和当前代码共同证明的原因，不给出修复方案。无法由现有证据继续定位的部分明确标记为“尚不能确定”，避免把推测写成代码事实。

### 11.1 十个场景的最终判定与原因类型

| 场景 | 最终判定 | 主要原因类型 | 根因确认程度 |
| --- | --- | --- | --- |
| 1 复杂知识库 | TaskPlan 质量不通过 | Planner/Reviewer 语义判断失败；确定性 Validator 不负责判断“外部事实”与“派生结论” | 已确认 |
| 2 简单纯 Web | 分流通过，完整 E2E 不通过 | Direct Web 没有落实官方域名约束；最终回答复用了只面向“知识库”的通用 RAG Prompt | 已确认 |
| 3 复杂纯 Web | TaskPlan 质量通过，执行质量不通过 | Research Evidence Evaluator 类型契约错误；Aggregator 只按 Evidence 结构计数；并行 Tool 契约不一致 | 已确认 |
| 4 知识库与 Web | TaskPlan 质量通过，执行失败 | Knowledge Worker 在 120 秒外层超时；同轮串行 Tool 被整批拒绝；Evaluator 同样发生类型错误 | 超时边界已确认，更深层原因证据不足 |
| 5 知识库与游戏数据库 | TaskPlan 质量不通过 | Planner 合并可独立失败的 SQL 事实；Reviewer 仍返回 accepted | 已确认 |
| 6 三来源专项 | TaskPlan 质量不通过 | Planner 合并冻结的原子 Requirement；Reviewer 仍返回 accepted | 已确认 |
| 7 有限会话指代 | 指代解析通过，TaskPlan 质量不通过 | Dataset metadata 中的平均值字段诱发范围扩张；Planner 合并 SQL 事实；Reviewer 漏检 | 已确认 |
| 8 禁止 direct Web | 前置行为和 TaskPlan 均不通过 | Router 不接收请求 Web 策略；Capability 删除 Web 能力后，Planner 用知识库静默替换用户明确要求的 Web 来源 | 已确认 |
| 9 无 Web Tool 权限 | 通过 | Direct Web Capability Resolve 正确返回 `TOOL_PERMISSION_DENIED`，未创建 TaskPlan | 无失败 |
| 10 无 Dataset Grant | 通过 | Dataset 前置鉴权正确返回 `NL2SQL_PERMISSION_DENIED`，未创建 TaskPlan | 无失败 |

### 11.2 场景 1、5、6、7：Planner 与 Reviewer 的语义质量门禁共同失效

这四个场景不是因为 Prompt 完全没有描述原子性。Planner Prompt 已经明确要求拆开可独立验证、可独立失败的事实：

代码位置：`src/fast_app/services/agent_tasks/agent_task_planner.py:41-61`

```python
_PLANNER_PROMPT = """你是 Research TaskPlan Planner，只生成 Requirements 和 SubQuestion Candidates，不回答用户问题。

规划规则：
- 每个 Requirement 必须是用户目标中的原子需求，并声明 SourcePolicy、ExpectedEvidence 和 CompletionPolicy。
- 可独立验证、可独立缺失或可独立影响最终结论的事实必须拆成不同 Requirement；不得把多个数据库字段事实或“结论 + 待核实项”合并成一个宽泛 Requirement。
- 多个独立数据库 Requirement 可以由同一个能返回全部所需字段的 nl2sql_query SubQuestion 覆盖，但 Aggregator 必须能按 Requirement 分别判断。
...
- 综合子问题必须依赖其结论所需的事实子问题。
"""
```

Reviewer Prompt 也再次要求检查相同问题：

代码位置：`src/fast_app/services/agent_tasks/agent_task_plan_reviewer.py:23-37`

```python
_REVIEWER_PROMPT = """你是 Research TaskPlan 的独立质量 Reviewer，只审查和修订 Requirements 与 SubQuestion Candidates。

必须检查：
1. 是否遗漏 resolved_query 的原子需求，或把用户语义扩大为无关主题。
2. Requirement 是否保持原子性：可独立验证、可独立失败的事实必须拆开；不得把多个数据库字段事实或“结论 + 待核实项”合并成一个宽泛 Requirement。
3. 一个 SubQuestion 可以覆盖多个相关 Requirement，但其问题和来源必须确实能为每个 Requirement 分别产生证据。
...
7. 综合 SubQuestion 必须使用 none，并依赖全部必要事实子问题。
"""
```

实际运行结果证明两次模型判断都没有执行好这些规则：

- 场景 1 把“先后关系”和“协作边界”设计为新的 `knowledge_retrieval` Requirement，而不是基于前三个事实结果的 `none + derived_synthesis`。
- 场景 5 把费用、模型面数、设计用途合并为一个 SQL Requirement。
- 场景 6 把费用与模型面数合并，又把适配判断与待核实问题合并。
- 场景 7 新增用户没有要求的“项目平均费用、平均模型面数”，并再次合并费用、面数和用途。

四份计划的 `quality_review` 均为：

```text
verdict=accepted
requirement_coverage=pass
source_alignment=pass
semantic_alignment=pass
dependency_quality=pass
executability=pass
completion_policy_alignment=pass
reviewer_findings=[]
```

服务端目前只验证 Reviewer 输出的自洽性：Reviewer 自己声明没有 error，Pydantic 和 Planner 就无法知道这个语义判断是错的。

代码位置：`src/fast_app/domain/research_task_plan.py:401-422`

```python
remaining_errors = [
    item
    for item in self.reviewer_findings
    if item.severity == "error" and item.status in {"detected", "remaining"}
]
...
if self.verdict == "accepted" and remaining_errors:
    raise ValueError("accepted 不允许 detected/remaining error")
```

这段代码能保证“accepted 不能同时携带未解决 error”，但不能证明 Reviewer 是否漏掉了本来应该发现的 error。

确定性 Validator 当前检查的是 ID、数量、覆盖引用、来源与 Evidence 类型、DAG、能力和字段白名单。例如覆盖检查只判断来源能否产生某类 Evidence：

代码位置：`src/fast_app/services/agent_tasks/agent_task_plan_validator.py:49-96`

```python
coverage = {item_id: [] for item_id in requirements}
for sub_question in candidate.sub_questions:
    ...
    for requirement_id in sub_question.covers_requirement_ids:
        ...
        if not _hint_can_cover(
            sub_question.information_source_hint,
            requirements[requirement_id].expected_evidence,
        ):
            issues.append(...)

issues.extend(_validate_dependency_graph(candidate.sub_questions))
for requirement in candidate.requirements:
    issues.extend(_validate_evidence_contract(requirement, capability))
```

因此，本组问题的准确归因是：

1. **真实模型没有稳定遵守已有 Planner Prompt。**
2. **同一个模型配置承担 Reviewer 后，产生了与 Planner 高度相关的漏检。**
3. **当前确定性 Validator 的职责只覆盖结构和来源可行性，无法发现原子性、范围扩张和“事实/派生结论”语义错误。**

不能简单归因为“Prompt 中完全没有规则”，也不能只归因为模型能力；当前代码把最终质量门禁建立在一次仍可能漏检的模型自报结果上。

### 11.3 场景 2：Direct Web 没有把“PostgreSQL 16 官方文档”落实为执行约束

Direct Web 节点直接把完整 query 交给 Bocha，没有解析或绑定 `site=postgresql.org`，也没有在结果返回后检查域名或版本：

代码位置：`src/fast_app/graph/rag_agent/rag_agent_nodes.py:78-100`

```python
results = await search_web_with_bocha(
    settings=settings,
    http_client=http_client,
    query=state["query"],
    count=min(max(state["top_k"], 2), 10),
)
...
docs = [
    RetrievedDoc(
        ...
        metadata={"url": result.url, "site_name": result.site_name},
    )
    for index, result in enumerate(results, start=1)
]
```

底层搜索函数其实支持 `site`，但只有调用者传入时才拼接域名限制：

代码位置：`src/fast_app/agents/tools/web_search_tools.py:146-180`

```python
async def search_web_with_bocha(..., site: str | None = None):
    ...
    search_query = f"site:{site} {query}" if site else query
    ...
    json={
        "query": search_query,
        "summary": True,
        "count": count,
    },
```

所以场景 2 返回豆丁网、华为云社区、SQL Server 文档和旧 PostgreSQL 文章，不是 Router 错误，也不是 Bocha 额度问题；是 Direct Web 分支没有把用户的“官方文档、指定版本”转换成可验证的来源约束。

随后 Direct Web 与普通知识库共用同一个回答生成节点，而系统 Prompt 把所有上下文统一称为“知识库”：

代码位置：`src/fast_app/components/llms/qwen_langchain_llm_client.py:22-39`

```python
RAG_SYSTEM_PROMPT = """你是一个严谨的 RAG 问答助手。
...
1. 只能根据【检索上下文】回答用户问题。
2. 如果【检索上下文】中没有足够信息回答问题，请直接回答：
   “当前知识库中没有足够信息回答这个问题。”
...
"""
```

代码位置：`src/fast_app/graph/rag_agent/rag_agent_builder.py:172-175`

```python
builder.add_edge("call_direct_web", "build_context")
builder.add_edge("build_context", "generate_answer")
```

这解释了为什么一个明确的联网问题最后输出“当前知识库中没有足够信息”：Direct Web 没有独立的来源契约和回答语义，仍复用了普通 RAG 的知识库 Prompt。

### 11.4 场景 3：Evidence Evaluator 与 Research v2 模型不兼容

这是已经确认的代码逻辑错误，不是模型能力问题。

`ResearchEvidenceEvaluator` 仍按旧 `AgentTaskSubQuestion` 读取 `expected_evidence`：

代码位置：`src/fast_app/services/research/research_evidence_evaluator.py:39-69`

```python
async def evaluate(
    self,
    *,
    sub_question: AgentTaskSubQuestion,
    answer: str,
    evidence: list[dict[str, Any]],
    ...
):
    ...
    payload = {
        "question": sub_question.question,
        "expected_evidence": sub_question.expected_evidence,
        "candidate_answer": answer,
        "evidence": evidence,
    }
```

但 Research v2 正式子问题 `ResearchTaskSubQuestion` 没有 `expected_evidence`。结构化 Evidence 契约位于 Requirement：

代码位置：`src/fast_app/domain/research_task_plan.py:143-186`

```python
class AgentTaskRequirement(BaseModel):
    ...
    expected_evidence: list[AgentTaskExpectedEvidence]

class ResearchTaskSubQuestionCandidate(BaseModel):
    ...
    covers_requirement_ids: list[str]

class ResearchTaskSubQuestion(ResearchTaskSubQuestionCandidate):
    web_usage: WebUsage
```

Executor 实际传入的正是 `ResearchTaskSubQuestion`：

代码位置：`src/fast_app/services/research/research_worker_agent.py:200-220`

```python
evaluation = await self._evaluator.evaluate(
    sub_question=request.sub_question,
    answer=state["last_result"].answer,
    evidence=state["all_evidence"],
    ...
)
```

因此运行时在 `sub_question.expected_evidence` 处产生 `AttributeError`。本次所有真正执行 Research Worker 的 TaskPlan 都记录了：

```text
Evaluator 不可用: AttributeError
```

Worker 捕获异常后，只要存在任意 Evidence 就把结果降级为 `partial`：

代码位置：`src/fast_app/services/research/research_worker_agent.py:223-250, 353-363`

```python
except Exception as exc:
    warning = f"Evaluator 不可用: {type(exc).__name__}"
    ...
    status = "partial" if state["all_evidence"] else "failed"
    ...

async def _finalize_limited(...):
    status = "partial" if state["all_evidence"] else "failed"
```

这意味着本轮 Research v2 实际没有得到可工作的语义 Evidence 评估，场景 3 的四个 Worker 全部 `partial` 并不是偶然现象。

### 11.5 场景 3：Requirement Aggregator 忽略 Worker 的 partial 和 Evaluator 失败

Typed Evidence Validator 只验证 Evidence 是否属于当前子问题、依赖是否合法、来源是否来自成功 ToolCall：

代码位置：`src/fast_app/services/research/requirement_evidence_service.py:123-166`

```python
if evidence.sub_question_id != sub_question.sub_question_id:
    reason = "EVIDENCE_SUB_QUESTION_MISMATCH"
elif evidence.evidence_type == "derived_synthesis":
    ...
elif evidence.source_type not in successful_sources:
    reason = "EVIDENCE_TOOL_PROVENANCE_INVALID"
...
valid.append(evidence)
```

Aggregator 判断 ExpectedEvidence 是否满足时，只统计类型、`query_id`、SQL 属性和数量：

代码位置：`src/fast_app/services/research/requirement_evidence_service.py:289-324`

```python
def _expected_satisfied(expected, evidence):
    matches = []
    required = set(expected.required_attributes)
    for item in evidence:
        if item.evidence_type != expected.evidence_type:
            continue
        if expected.requires_query_id and not item.query_id:
            continue
        if required and not required.issubset(item.provided_attributes):
            continue
        matches.append(item.evidence_id)
    return len(set(matches)) >= expected.minimum_count
```

聚合入口虽然读取了 `results`，但结果状态只用于判断“是否终止”和“安全错误”，不会阻止 `partial` Worker 的 Evidence 满足 strict Requirement：

代码位置：`src/fast_app/services/research/requirement_evidence_service.py:195-235`

```python
contract_satisfied = self._contract_satisfied(...)
unfinished = any(
    result_by_id.get(item_id) is None
    or result_by_id[item_id].status not in _TERMINAL_SUB_STATUSES
    for item_id in covering
)
...
if contract_satisfied:
    status = "satisfied"
elif unfinished:
    status = "pending"
...
```

由于 `partial` 属于终态，且 Registry 中存在形式合法的 URL，`contract_satisfied` 会先返回 true。于是场景 3 出现：

```text
SubQuestion: sq_1/sq_2/sq_3/sq_4 全部 partial
Requirement: req_1/req_2/req_3/req_4 全部 satisfied
TaskPlan: completed
```

其中 `sq_2`、`sq_4` 的答案明确是“当前知识库中没有足够信息回答这个问题”，仍被标为满足 strict Requirement。根因是服务端只验证 Evidence 的结构和来源，不验证 Evidence 是否语义支持 Requirement，也没有把 Evaluator 的失败或 Worker 的 `partial` 纳入 strict Requirement 的满足条件。

### 11.6 场景 3、4：Tool 并行提示与执行安全规则互相矛盾

Tool Selector Prompt 告诉模型可以在同一轮选择多个独立只读工具：

代码位置：`src/fast_app/services/research/research_tool_loop.py:115-132`

```python
同一轮可以选择多个彼此独立的只读工具；存在依赖时必须等待上一轮结果。
...
同时需要知识库规则和数据库事实时，可以在同一轮并行选择 knowledge_retrieval 与 nl2sql_query。
```

并且模型绑定时，只要不是服务端强制单一工具，就设置 `parallel_tool_calls=True`：

代码位置：`src/fast_app/services/research/research_tool_loop.py:687-703`

```python
bind_options: dict[str, Any] = {
    "parallel_tool_calls": required_tool_name is None,
}
...
model = ChatOpenAI(...).bind_tools(bound_tools, **bind_options)
```

但执行前的安全规则会拒绝包含任何非并行安全工具的整个批次：

代码位置：`src/fast_app/services/agent_tasks/agent_task_tool_support.py:80-87`

```python
if len(tool_names) <= 1:
    return None
...
unsafe = [name for name in tool_names if name not in parallel_safe_tool_names]
if unsafe:
    return "同轮包含必须串行执行的工具，请按依赖分轮重试: " + ", ".join(unsafe)
```

场景 3 的 `sq_3` 和场景 4 的 `sq_2` 都让模型在同一轮选择两个 `mcp__fetch`（有时还包含一个 `web_search`），随后整批被拒绝。被拒绝的调用仍计入预算：

代码位置：`src/fast_app/services/research/research_tool_loop.py:260-291`

```python
call_count += batch_size
batch_error = parallel_batch_error(...)
if batch_error:
    tool_calls.extend(_failed_batch_traces(...))
    continue
```

这是 Prompt、模型绑定参数和后端执行规则之间的代码契约不一致。它会浪费调用预算，并把本来可串行完成的官方页面读取降级成 `partial` 或 `failed`。

### 11.7 场景 4：Knowledge Worker 超时只能定位到外层边界

场景 4 的 `sq_1` 运行记录为：

```text
status=failed
attempt_count=0
tool_calls=[]
evidence_ids=[]
error_code=WORKER_TIMEOUT
```

直接产生该错误的代码位置是：`src/fast_app/services/research/agentic_research_executor.py:244-267`

```python
try:
    return await asyncio.wait_for(
        self._worker_agent.run(...),
        timeout=self._settings.agent_research_worker_timeout_seconds,
    )
...
except TimeoutError:
    return _failed_legacy_result(sub_question, "WORKER_TIMEOUT")
```

当前配置的 `agent_research_worker_timeout_seconds` 为 120 秒。TaskPlan 快照只保存了外层超时结果，没有保存超时发生时 Worker 内部正在等待哪个模型或 Retriever 调用；清理前也没有留下包含该调用栈的本轮后端日志。因此现有证据只能确认：

1. Knowledge Worker 在 120 秒内没有返回第一次完整 `AgentTaskSubQuestionResult`。
2. Executor 正确把它收敛为 `WORKER_TIMEOUT`，依赖子问题随后被跳过，Final Synthesis 没有运行。
3. 不能仅凭当前快照继续断言是 Milvus、Elasticsearch、Rerank、LLM 或 Prompt 中的哪一项导致了 120 秒耗尽。

这部分若写成“确定是模型慢”或“确定是检索代码死锁”都超出了现有证据。

### 11.8 场景 4 的旧 session：测试隔离问题叠加 Rewriter 语义误判

Pipeline 只在 session 为空或历史为空时跳过 Rewriter；只要固定 session 中已有历史，就会调用模型：

代码位置：`src/fast_app/services/rag/rag_agent_pipeline_service.py:261-341`

```python
if req.session_id is None:
    ...
    return state
...
history_window = await load_recent_history_window(...)
...
if not history_window.messages and not memory_context.summary_text:
    ...
    return state
```

Rewriter Prompt 已要求“当前问题已经可以独立检索时原样返回”：

代码位置：`src/fast_app/services/conversation/query_rewrite.py:25-37`

```python
1. 如果当前问题依赖历史中的指代、省略或上下文，请补全必要上下文。
2. 如果当前问题已经可以独立检索，请原样返回当前问题。
...
6. 只有上下文确实不足时才返回 unresolved，并提供一个澄清问题。
```

旧固定 session 中，模型仍把“当前知识库”误判成无法解析的历史指代并返回 `unresolved`；更换隔离 session 后，相同 query 正常生成计划。因此准确归因是：

- 验收页面重复使用固定 session，造成测试输入不再是干净基准，属于测试隔离问题。
- Rewriter 没有遵守“独立问题原样返回”的 Prompt，属于真实模型语义误判。
- `rag_agent_pipeline_service.py:383-387` 按 `unresolved` 返回结构化澄清是预期代码行为，不是该问题的根因。

### 11.9 场景 7：Dataset metadata 对 Planner 产生了范围诱导

场景 7 的 `source_query` 已正确解析为：

```text
结合知识库继续比较《星港远征》中已授权的3D模型资产（角色资产01和角色资产06），
重点关注费用、模型面数和移动端适配，并说明哪些内容还需要公开资料验证。
```

所以“平均费用、平均模型面数”不是 Rewriter 添加的，而是 Planner 在看到 Dataset Schema 后新增的。ModelPlanningContext 包含：

```text
average_cost_yuan
average_polygon_count
```

代码位置：`src/fast_app/services/agent_tasks/agent_task_capability_service.py:83-118`

```python
fields = await self._catalog.load_logical_fields(connection, dataset)
raw_schema_context = await self._catalog.load(...)
dataset_schema_context = (
    "<dataset_metadata trust=\"untrusted_business_data\">\n"
    + raw_schema_context[:20_000]
    + "\n</dataset_metadata>"
)
...
allowed_dataset_fields=allowed_fields,
dataset_schema_context=dataset_schema_context,
```

传入完整字段本身是为了让 SQL 计划可执行；问题在于 Planner 把“可用字段”误当成“用户要求”，Reviewer 的 `semantic_alignment` 又错误返回 pass。这里没有发现服务端硬编码自动增加均值 Requirement 的逻辑，范围扩张来自 Planner 模型输出。

### 11.10 场景 8：请求策略禁止 direct Web 后发生静默换源

Router 的模型输入只有 query、有限 history 和 Dataset 是否绑定，不包含 `allow_direct_web`：

代码位置：`src/fast_app/services/agent_tasks/agent_task_router.py:312-337`

```python
def _build_router_messages(*, query, history, dataset_query_bound=False):
    ...
    HumanMessage(
        content=(
            f"当前 query：\n{query}\n\n"
            f"最近会话上下文：\n{history_text or '无'}"
        )
    )
```

因此 Router 根据“请联网比较……”正确识别为复杂研究，却不知道当前请求策略已经禁止 direct Web。

进入 Research Capability Resolve 后，`allow_direct_web=false` 会让 `web_search` 从模型可用来源中消失：

代码位置：`src/fast_app/services/agent_tasks/agent_task_capability_service.py:58-66, 105-120`

```python
available_sources = ["knowledge_retrieval"]
if web_permission and web_configured and (
    allow_direct_web or allow_web_fallback
):
    available_sources.append("web_search")
...
web_direct_allowed=web_permission and web_configured and allow_direct_web,
```

后端没有在 Planner 之前比较“resolved query 明确要求 Web”与“当前 direct Web 被禁用”。Planner 看到的可用来源只剩 `knowledge_retrieval`，于是生成纯知识库计划；Validator 也只能检查计划实际声明的来源是否可用：

代码位置：`src/fast_app/services/agent_tasks/agent_task_plan_validator.py:108-123`

```python
if hint != "none" and hint not in capability.available_source_types:
    issues.append(... "PLAN_SOURCE_UNAVAILABLE" ...)
if hint == "web_search" and not capability.web_direct_allowed:
    issues.append(... "PLAN_DIRECT_WEB_DISABLED" ...)
```

因为错误计划已经把所有 hint 改成 `knowledge_retrieval`，这两条校验都不会触发。Reviewer 随后又把 `source_alignment` 错误标为 pass。

所以场景 8 的根因不是单独的 Router Prompt 错误，而是确定性的链路缺口：请求的必需来源约束没有成为 Planner 前的服务端事实，Capability 只隐藏不可用 Tool，允许模型静默换源，Validator 又只能验证“生成后的来源是否可执行”。

### 11.11 场景 9、10：权限负向链路没有发现错误

场景 9 在 Direct Web Capability Resolve 中先检查 Tool 权限：

代码位置：`src/fast_app/services/agent_tasks/agent_task_capability_service.py:33-46`

```python
if not user.has_global_permission(PermissionCode.AGENT_TOOL_WEB_SEARCH.value):
    raise ToolPermissionDeniedError("当前用户没有 Web Search Tool 权限")
if not allow_direct_web:
    raise AgentTaskSourceUnavailableError("当前请求策略禁止 direct Web")
```

实际返回 `TOOL_PERMISSION_DENIED`，没有创建 TaskPlan、没有调用 Web Provider，符合预期。

场景 10 在绑定 Dataset 的前置鉴权中返回 `NL2SQL_PERMISSION_DENIED`，没有进入普通 Router、Planner 或 Reviewer，也符合预期。本次检查没有发现这两个负向权限场景的代码逻辑错误。

### 11.12 根因优先级总结

按对本轮结果的影响范围排序：

1. **确定代码错误：Research Evidence Evaluator 仍读取旧 SubQuestion 字段。**它使所有执行过的 Research Worker 都失去语义 Evidence 评估。
2. **确定代码逻辑缺口：Aggregator 只按形式合法的 Evidence 计数。**它允许 `partial`、明确回答“信息不足”的 Worker 满足 strict Requirement。
3. **Planner/Reviewer 质量门禁失效：已有原子性与语义 Prompt，但真实模型重复违反，Reviewer 与 Planner 产生相关性漏检。**场景 1、5、6、7 均受影响。
4. **确定代码契约冲突：模型被允许并行 ToolCall，但执行层整批拒绝包含 `mcp__fetch` 的批次且消耗预算。**场景 3、4 受影响。
5. **确定代码链路缺口：必需 Web 来源没有在 Planner 前与请求策略做冲突检查。**场景 8 发生静默换源。
6. **Direct Web 执行与 Prompt 不匹配：没有官方来源约束，回答仍使用“知识库不足”语义。**场景 2 受影响。
7. **测试隔离与模型误判：固定 session 保存旧历史，Rewriter 把独立问题判成 unresolved。**场景 4 首次请求受影响。
8. **尚不能继续细分：Knowledge Worker 的 120 秒超时。**当前快照只能定位外层 timeout，缺少足以判定内部阻塞点的日志。

## 12. qwen3.7-max Reviewer 与 11.2 专项流式复测（2026-08-03）

### 12.1 测试边界

本节只复测 11.2 涉及的场景 1、5、6、7，所有请求均由
`scripts/phase_15/rag_agent_manual_acceptance.html` 发往结构化流式接口
`POST /rag/chat/stream/events`，没有使用非流式 `/rag/chat`，也没有确认执行
TaskPlan 或测试 GitLab。

- 测试账号：普通员工 `rbac_operator`，不是管理员。
- Reviewer 模型：`qwen3.7-max`。
- Planner 仍使用当前主模型配置。
- NL2SQL 使用真实 `game_test` PostgreSQL 测试库。
- 每次无历史场景使用独立 session；场景 7 先通过同一 session 写入冻结的前置消息。
- 通过标准不是“生成了 TaskPlan”，而是逐项检查 Requirement 原子性、来源、
  CompletionPolicy、SubQuestion 覆盖、依赖、范围守恒和 Reviewer finding。

### 12.2 只更换 Reviewer 模型后的结果

| 场景 | TaskPlan | Reviewer 结果 | 质量结论 |
|---|---|---|---|
| 1 | `task_plan_20260803133616_1759ec28c988` | `accepted`，无 finding | 不通过。先后关系、协作边界仍被错误建模为新的知识库事实检索。 |
| 5 | `task_plan_20260803134006_20b1dcac62ad` | `accepted`，无 finding | 不通过。费用、模型面数、设计用途仍合并为一个 SQL Requirement。 |
| 6 | `task_plan_20260803134201_f8c5a45c64e8` | `accepted`，无 finding | 不通过。费用和模型面数仍合并为一个 SQL Requirement。 |
| 7 | `task_plan_20260803134621_684bb114184c` | `revised` | 不通过。Reviewer 修复了原子性，但 Planner 无故增加项目资产数量、总费用、平均费用和平均面数。 |

这组结果证明：`qwen3.7-max` 能正常完成 structured output，也确实比原 Reviewer
更容易发现原子性问题，但仅更换模型不能修复 11.2。视觉能力与本问题无关；真正缺少的是
Planner/Reviewer 对“Requirement 原子性、Tool 合批、范围守恒、事实与综合分类”的明确契约。

### 12.3 Prompt 根因修复

本轮没有增加业务关键词路由、固定主题白名单或规则 TaskPlan 兜底，只补充通用规划契约。

Planner 修改位置：

- `src/fast_app/services/agent_tasks/agent_task_planner.py:45-48`
- `src/fast_app/services/agent_tasks/agent_task_planner.py:59`

新增约束的含义是：

1. 先从 `resolved_query` 建立完整用户要求清单，每个 Requirement 只对应一个可独立验收的事实或输出。
2. Requirement 原子性与 Tool 调用次数分离；一个 SQL SubQuestion 可以合批查询多个字段，但字段事实仍分别验收。
3. 禁止为了参考背景自行增加均值、总量、比较对象或其他未被用户要求的指标。
4. 需要组合前置事实的比较、适用性、流程关系、协作边界和待核实项必须使用
   `none + derived_synthesis`。

Reviewer 修改位置：

- `src/fast_app/services/agent_tasks/agent_task_plan_reviewer.py:24-37`

Reviewer 现在必须依次检查范围守恒、Requirement 原子性、事实/综合分类、来源和依赖；
`revised` 的 `checks` 必须评价修订后的完整计划，不能一边返回修订结果一边保留 `fail`。

场景 7 还暴露了 Query Rewriter 会只补实体名称、丢失历史比较维度的问题。修改位置：

- `src/fast_app/services/conversation/query_rewrite.py:31-32`

Rewriter 现在被明确要求：解析“这些、继续、上述”等指代时，必须同时保留与对象绑定的
最新用户目标、比较维度和约束；历史已经给出完整信息时不能要求用户重复。

### 12.4 Prompt 修复后的 TaskPlan 质量结果

| 场景 | Request / Trace ID | TaskPlan | 质量评估 |
|---|---|---|---|
| 1 | `e1e1539b3b2749f8848398eee9ffed38` | `task_plan_20260803134950_652c3fb046a3` | 通过。3 个组件职责是独立知识库事实；先后关系和协作边界是两个独立 `none` Requirement，依赖前置事实。 |
| 5 | `7c09e3a14abb455a97d435a063cd5722` | `task_plan_20260803135228_1c91c4671cde` | 通过。知识库费用/面数/用途和数据库资产名/费用/面数/用途均拆成独立 Requirement；两个 Tool SubQuestion 合理合批；最终比较独立综合。 |
| 6 | `5f6e0abd07f444aebf8f81225642fec5` | `task_plan_20260803135635_a917bd6780cb` | 通过。资产名、费用、模型面数分别验收，同一 NL2SQL SubQuestion 合批；适配判断、依据和待核实项均是独立综合 Requirement。Reviewer 第一次返回非法 Evidence Schema，被 Pydantic 拒绝，唯一一次技术重试后生成合法修订。 |
| 7 | 见 12.5 | 无有效 TaskPlan | 未通过。低质量计划已能被门禁阻止，但尚未稳定生成合格计划。 |

场景 1、5、6 的修复结果不是因为后端硬编码了这三个 query；它们来自同一组通用 Prompt
约束，并仍由真实 Planner 和 `qwen3.7-max` Reviewer 生成、审查。

### 12.5 场景 7 的失败记录与当前结论

场景 7 使用的冻结前置消息为：

```text
本轮分析对象是《星港远征》中已授权的 3D 模型资产，重点关注费用、模型面数和移动端适配。
```

当前问题为：

```text
结合知识库继续比较这些资产，并说明哪些内容还需要公开资料验证。
```

观察到三类结果：

1. `request_id=3604c52d9991454fb25e63e0f6765723`：Rewriter 错误返回
   `AGENT_TASK_PLANNING_CONTEXT_UNRESOLVED`。这是一次真实模型语义失败，没有进入 Planner。
2. `request_id=802da9b73fd5406a8b7eef85bc1d54ab` 和
   `85d7f3bb4c934572814bbdf5b282c41d`：Rewriter 补全了资产名称但丢失费用、面数和移动端维度，
   Reviewer 返回 `AGENT_TASK_PLAN_QUALITY_REJECTED`，没有保存低质量 TaskPlan。
3. `request_id=5065214f3a9d4816b9fb73afa36caad4`：Rewriter 修复后正确保留资产名称、费用、
   模型面数和移动端适配，但 Reviewer 仍返回 `AGENT_TASK_PLAN_QUALITY_REJECTED`。

因此场景 7 当前不能标记为通过。与旧结果相比，安全结果已经改善：系统不再把包含项目均值等
额外范围的计划保存到 `waiting_confirmation`，而是 fail-closed。但“稳定生成一份范围准确的
会话型 TaskPlan”仍未完成，后续需要单独分析 Reviewer 对该 Candidate 的具体 fail check；不能通过
放宽 `checks` 门禁或接受未解决 finding 来制造假通过。

### 12.6 本轮代码与测试检查

已通过：

```text
python -m py_compile agent_task_planner.py agent_task_plan_reviewer.py query_rewrite.py
scripts/phase_15/test_agent_task_plan_decomposition.py
scripts/phase_15/test_agent_conversation_context.py
git diff --check
```

最终专项结论：**场景 1、5、6 通过，场景 7 未通过；不能宣称 11.2 四个场景全部通过。**

## 13. 场景 7 历史恢复、真实流式重放与拒绝根因（2026-08-04）

### 13.1 Redis 与 PostgreSQL 历史核对

本次继续使用普通员工 `rbac_operator`、真实 PostgreSQL、真实 DashScope 模型和结构化流式接口 `POST /rag/chat/stream/events`。

Rewriter 实际只从 Redis key `conversation:{scoped_conversation_id}:messages` 读取最近窗口，PostgreSQL 不会被 Rewriter 自动回读。检查时 Redis key 已过期：

```text
REDIS_KEY_EXISTS=0
REDIS_TTL=-2
REDIS_MESSAGE_COUNT=0
```

PostgreSQL 中同一 scoped conversation 只有两条冻结历史，没有混入其他场景：

1. 用户：`本轮分析对象是《星港远征》中已授权的 3D 模型资产，重点关注费用、模型面数和移动端适配。`
2. 助手：返回角色资产01和角色资产06的费用、面数和用途。

将这两条 PostgreSQL 原始消息按原 ID、role、created_at 和 metadata 恢复到 Redis 后，复核为 `2` 条、TTL `3600`。重放结束后已再次把 Redis 清理回这两条冻结消息，避免本次调试轮次干扰后续验证。

### 13.2 真实流式重放结果

- Request / Trace ID：`f87bb83648664024aa254c06fe8a9d44`
- Rewriter 输入历史数：`2`
- Rewriter 结果：`resolved`
- Resolved query：`结合知识库继续比较《星港远征》中已授权的3D模型资产（角色资产01和角色资产06），重点关注费用、模型面数和移动端适配维度，并说明哪些内容还需要公开资料验证。`
- Router：`question_decomposition`
- TaskPlan：`task_plan_20260804053233_72ab0ae0eaa5`
- 状态：`waiting_confirmation`

本次证明 Rewriter 在干净的两条历史上可以正确保留资产对象、费用、面数和移动端适配维度。因此 12.5 最后一次拒绝不是由历史消息混乱造成。

但本次生成的计划仍不能作为“稳定通过”证明：Reviewer 把移动端适配 Requirements 设为 `allow_partial`，而用户没有表达“尽量”或“可选”；这与当前 Prompt 中“CompletionPolicy 默认 strict”的规则不一致。

### 13.3 旧失败的确定性根因

从 LangSmith 只读取回 `request_id=5065214f3a9d4816b9fb73afa36caad4` 的真实 Reviewer 响应后，本地契约重放结果为：

```text
PYDANTIC_ACCEPTED=True
VERDICT=revised
FAILED_CHECKS=[semantic_alignment]
PLANNER_WOULD_REJECT=True
REVISED_REQUIREMENTS=4
REVISED_SUBQUESTIONS=4
```

确定性执行链是：

1. Reviewer Prompt 明确规定 `revised` 时所有 checks 必须为 `pass`，位置：`src/fast_app/services/agent_tasks/agent_task_plan_reviewer.py:37`。
2. 真实模型输出却同时返回 `verdict=revised` 和 `semantic_alignment=fail`。
3. `AgentTaskPlanReviewDecision.validate_decision_state()` 只检查修订内容和 finding 状态，没有拒绝 `accepted/revised + fail check`，位置：`src/fast_app/domain/research_task_plan.py:401-422`。所以这份自相矛盾的 structured output 被 Pydantic 当成合法响应，不会触发一次技术重试。
4. Planner 随后在 `src/fast_app/services/agent_tasks/agent_task_planner.py:168-169` 检测到任意 `fail`，必然返回 `AGENT_TASK_PLAN_QUALITY_REJECTED`。
5. 该请求的最终确定性 Validator 输出是 `error_count=0`，所以不是 DAG、字段、来源可用性或 Dataset Schema 校验导致拒绝。

根因归类：

- **不是历史混乱**：PostgreSQL 原始历史只有两条，Rewriter 重放可正确解析。
- **不是 Rewriter 当前 Prompt 约束缺失造成的这次拒绝**：旧 trace 的 resolved query 已完整保留三个维度。
- **直接原因是 Reviewer 响应违反 Prompt 状态契约**：修订后仍返回 fail check。
- **代码契约存在缺口**：Pydantic validator 没有将这种自相矛盾的 Reviewer 输出当成 Schema 错误，因此无法使用现有 structured-output 技术重试自动纠正。
- **更广的质量问题仍存在**：旧修订结果仍把多个可独立验收事实合并；本次通过结果又错用 `allow_partial`。这说明 Planner/Reviewer 的语义质量仍有模型波动，不能因一次生成 TaskPlan 就判定场景 7 稳定通过。

本节只完成故障复现和根因定位，未修改 Planner、Reviewer、Pydantic Schema 或质量门禁代码。

## 14. 场景 7 Reviewer 决策一致性修复与真实流式回归（2026-08-04）

### 14.1 根因修复

本轮没有放宽 Planner 的质量门禁，也没有增加业务关键词规则。修复位于 Reviewer structured output 的领域模型边界：

- `src/fast_app/domain/research_task_plan.py`
  - `AgentTaskPlanReviewDecision.validate_decision_state()`：`accepted/revised` 只要存在任一 `fail` check，就直接产生 Pydantic `ValidationError`。
  - `AgentTaskPlanQualityReview.validate_persisted_review()`：最终有效 TaskPlan 的 checks 也必须全部为 `pass`，阻止其他调用方绕过 Planner 构造无效持久化计划。
- `scripts/phase_15/test_research_task_plan_v2.py`
  - 固化旧故障形状：`verdict=revised + semantic_alignment=fail` 必须解析失败。
  - 固化持久化边界：`verdict=accepted + semantic_alignment=fail` 也必须解析失败。

修复前运行最小回归时稳定失败：

```text
AssertionError: revised 不应接受失败的最终质量检查
```

修复后，旧矛盾状态在进入 Planner 前即被拒绝，并可使用现有 structured-output transport 的唯一一次技术重试；不需要新增重试循环。

### 14.2 自动化回归

以下检查全部通过：

```text
scripts/phase_15/test_research_task_plan_v2.py
scripts/phase_15/test_agent_task_plan_decomposition.py
scripts/phase_15/test_agent_task_planning_flow.py
scripts/phase_15/test_agent_conversation_context.py
scripts/phase_15/test_schema_field_descriptions.py
scripts/phase_15/test_structured_output_transport.py
scripts/test_langsmith_tracing.py
python -m py_compile src/fast_app/domain/research_task_plan.py scripts/phase_15/test_research_task_plan_v2.py
git diff --check
```

`test_agent_conversation_context.py` 输出的 Prompt Guard 异常日志是该测试主动验证 fail-closed 的预期分支，脚本最终状态为 `passed`。

### 14.3 真实 Web 结构化流式重放

通过 `scripts/phase_15/rag_agent_manual_acceptance.html`，使用普通员工 `rbac_operator` 和 `POST /rag/chat/stream/events` 重放场景 7；没有调用非流式接口，也没有确认或执行 TaskPlan。

- Request / Trace ID：`372d7e1b39bc49e6b7aa228cc072679b`
- Redis 冻结历史：原始两条消息
- Rewriter：读取 `2` 条历史并正确生成与 13.2 相同的 resolved query
- Router：`question_decomposition`
- 第一次 Reviewer structured output：再次出现 `verdict=revised + fail check`
- 新校验行为：日志记录 `ValidationError`，拒绝该矛盾响应
- transport 行为：只对当前 `json_schema` transport 技术重试一次
- 重试结果：生成有效 TaskPlan `task_plan_20260804060040_073ea3a45aa7`
- 最终状态：`waiting_confirmation`
- Reviewer verdict：`revised`
- Reviewer checks：六项全部为 `pass`
- Final Validation：`0` 个 issue

这次真实重放直接覆盖了旧故障：模型第一次仍返回矛盾状态，但后端没有再把它当成合法 Reviewer 决策，也没有直接落入旧的 `AGENT_TASK_PLAN_QUALITY_REJECTED` 路径；一次重试后正常保存有效计划。因此 **Reviewer 决策一致性 bug 验收通过**。

测试启动过程中还观察到两次环境配置拒绝：`NL2SQL_DISABLED` 和“Dataset 的只读数据库连接尚未配置”。两次都发生在 Rewriter/Planner 前，补齐测试进程的 `NL2SQL_ENABLED` 与只读 Dataset 连接映射后消失，不属于本次代码回归。

### 14.4 TaskPlan 人工质量评估

新计划包含 8 个 Requirements 和 6 个 SubQuestions。正确部分包括：

1. 费用、模型面数分别拆成独立且 `strict` 的 SQL Requirements。
2. 同一个 NL2SQL SubQuestion 合批获取字段，但不合并 Requirement 验收语义。
3. 费用比较、面数比较、移动端适配比较和待核实项均使用 `none + derived_synthesis`。
4. 综合 SubQuestions 具有明确依赖，没有把推导结论伪装成数据库或知识库事实。
5. 本次不实际要求联网取证，因此“说明哪些内容还需要公开资料验证”作为综合输出，而不是强行增加 `web_search`，方向正确。

仍存在一个语义质量问题：resolved query 明确聚焦费用、模型面数和移动端适配，但 R3/SQ1 额外加入了“推荐应用场景”。该字段虽然在 Dataset 中可查询，也出现在旧助手历史中，但不属于当前 resolved query 的三个明确比较维度，属于范围扩大。

测试期间还观测到同一冻结输入生成的第二份计划 `task_plan_20260804060151_fb237d5a72bb`。它把应用场景和授权状态同时加入知识库、数据库 Requirements，并缺少“从知识库获取移动端适配信息”的独立 Requirement，人工质量低于第一份计划。这进一步证明：本次 Schema 修复解决的是 Reviewer 状态一致性和有限重试问题，不能消除真实模型在 Requirement 范围守恒上的波动。

因此本轮结论必须拆开：

- **Reviewer 决策一致性 bug：通过。** 真实模型的矛盾响应已被 Schema 拦截并触发有限重试。
- **场景 7 TaskPlan 整体语义质量：未完全通过。** 当前计划仍包含一个未请求的业务事实，不能仅凭所有 Reviewer checks 为 `pass` 就认定人工质量合格。

本轮只修复已经确认的状态契约 bug；没有顺带修改 Planner/Reviewer Prompt 来掩盖新发现的语义扩大问题。

## 15. 场景 7 范围守恒、来源守恒与结构化重试修复（2026-08-04）

### 15.1 两轮真实失败暴露出的剩余问题

在 14.4 的人工质量结论之后继续修复，没有把“能够保存 TaskPlan”当作场景通过。

第一轮补充 Planner/Reviewer 范围守恒约束后，真实流式请求
`c5ca9b584ac04fd2be743c2e9a165241` 生成的
`task_plan_20260804062117_5cb6819237f7` 仍未通过人工质量审查：计划删除了用户明确要求的
`knowledge_retrieval` 来源，并继续使用 `usage_scenario` 代替移动端适配判断。

对应 Prompt 缺口位于：

- `src/fast_app/services/agent_tasks/agent_task_planner.py:58-66`
- `src/fast_app/services/agent_tasks/agent_task_plan_reviewer.py:34-37`

补充的约束包括：

1. `resolved_query` 是唯一任务范围权威；历史 assistant 回答和 Dataset 字段不能自动变成新需求。
2. 用户明确指定的每一种外部来源都必须保留。
3. “某来源可能没有证据”不能成为 Planner/Reviewer 删除 Requirement 的理由；证据充足性由 Worker 和 Aggregator 在执行阶段判断。
4. 移动端适配需要从用户指定的知识库取得标准或约束，再由综合 Requirement 结合资产事实判断，不能用 `usage_scenario` 冒充。

第二轮真实流式请求 `d21bba758e444505a5c153546a35a20f` 中，Planner 已保留知识库和数据库来源，
但 Reviewer 两次都返回：

```text
verdict=revised
source_alignment=fail
semantic_alignment=fail
全部 error finding=status=resolved
```

两次响应的修订内容实际已经删除 `usage_scenario` 并保留知识库来源，但 checks 仍描述修订前状态。
Pydantic 正确拒绝了这两份矛盾响应；由于第二次调用只是原样重发同一组消息，模型没有收到字段级错误反馈，
最终返回 `AGENT_TASK_PLANNER_UNAVAILABLE`。这说明问题已不再是质量门禁缺失，而是共享 structured-output
技术重试没有纠错上下文。

### 15.2 共享 structured-output 重试修复

修复位置：

- `src/fast_app/core/structured_output.py:21-81`
- `scripts/phase_15/test_structured_output_transport.py:97-123`

第一次 `ValidationError` 后，第二次调用仍使用同一个已确认支持的 transport，但会追加一条精简的
Schema 纠错消息。纠错消息只包含字段路径和 Pydantic 错误说明，不包含上一份原始模型输出，也不改变
Planner/Reviewer 的任务语义。最大调用次数、transport 缓存和 fail-closed 规则保持不变。

该修复没有把 `fail` 自动改成 `pass`，也没有绕过
`AgentTaskPlanReviewDecision.validate_decision_state()`；模型第二次仍必须返回一份完整、合法且所有最终 checks
均为 `pass` 的对象，否则继续拒绝。81908 998 0778

### 15.3 自动化回归结果

以下检查通过：

```text
scripts/phase_15/test_structured_output_transport.py
scripts/phase_15/test_research_task_plan_v2.py
scripts/phase_15/test_agent_task_plan_decomposition.py
scripts/phase_15/test_agent_task_planning_flow.py
scripts/phase_15/test_schema_field_descriptions.py
```

新增断言同时验证：第二次调用收到了字段级纠错信息，但没有收到上一份非法值正文。

### 15.4 真实 Web 结构化流式最终重放

通过 `scripts/phase_15/rag_agent_manual_acceptance.html`，使用员工账号 `rbac_operator`、真实 Redis
两条冻结历史、真实 PostgreSQL、真实 DashScope Planner/Reviewer 和
`POST /rag/chat/stream/events` 重新执行。没有调用非流式接口，没有确认或执行 TaskPlan。

- Request / Trace ID：`cc9c9ead6a6a40f293a39dd005e831ce`
- Rewriter 历史数：`2`
- Resolved query：完整保留角色资产01、角色资产06、费用、模型面数、移动端适配和待公开验证项
- Router：`question_decomposition`
- Reviewer 第一次响应：被领域 Schema 以 `accepted/revised + fail check` 拒绝
- Reviewer 第二次响应：收到字段级纠错信息后返回合法 `revised`
- TaskPlan：`task_plan_20260804064439_b7994fac221c`
- 状态：`waiting_confirmation`
- Final Validation：无 error
- Reviewer 六项 checks：全部 `pass`

### 15.5 TaskPlan 人工质量评估

本次不是只检查 TaskPlan 是否生成，而是按冻结人工基准逐项审查：

| 检查项 | 实际结果 | 结论 |
|---|---|---|
| 当前指代 | 正确解析为角色资产01和角色资产06 | 通过 |
| 费用事实 | 独立 `strict` Requirement，来源为 `nl2sql_query` | 通过 |
| 模型面数事实 | 独立 `strict` Requirement，来源为 `nl2sql_query` | 通过 |
| 知识库来源 | 独立检索移动端面数标准或技术要求 | 通过 |
| SQL 合批 | 一个 SQ 同时查询费用和面数，但分别覆盖两个 Requirement | 通过 |
| 移动端适配 | 由数据库面数与知识库标准综合判断，不再使用 `usage_scenario` 代替 | 通过 |
| 综合比较 | `mode=none`，依赖 SQL 与知识库事实子任务 | 通过 |
| 待公开验证项 | 独立 `mode=none` Requirement，依赖已有事实和比较结论 | 通过 |
| 范围守恒 | 未新增应用场景、授权状态、项目均值或其他未请求事实 | 通过 |
| CompletionPolicy | 五个 Requirements 全部为 `strict` | 通过 |
| WebUsage | 本问题只要求列出待公开验证项，没有要求立即联网，全部 `not_used` 合理 | 通过 |

本地还对持久化 JSON 执行了独立断言，验证来源序列、依赖、Requirement 覆盖、全部 checks、全部
`strict` 以及不存在 `usage_scenario`，结果为：

```text
SCENARIO7_MANUAL_QUALITY_ASSERTIONS=passed
```

流式请求正常保存一轮对话后，Redis 消息数暂时变为 `4`；测试结束已使用 `LTRIM 0 1` 恢复为原始两条
冻结消息并续期，避免本次调试输出污染下一次指代测试。

最终结论：**场景 7 的 Rewriter、Planner、Reviewer 状态契约、有限纠错重试和 TaskPlan 人工语义质量均通过本次真实流式 Web 验收。**

## 16. 11.3 与 11.4 修复及真实 Web 验证（2026-08-04）

### 16.1 11.3 Direct Web 修复

第一次修复曾在 `rag_agent_nodes.py` 中根据 PostgreSQL/RLS 关键词拼接固定文档地址。该实现只能覆盖冻结测试问题，不能处理其他产品和主题，因此已撤销，不能作为 11.3 的最终修复。

最终实现不包含 PostgreSQL、RLS 或固定官方页面的业务分支：

- `src/fast_app/services/rag/direct_web_search_planner.py:37`：模型把任意用户问题转换为结构化搜索 query、官方网站域名、URL 片段和主题约束；后端 Pydantic Schema 校验 URL、域名和字段边界。
- `src/fast_app/services/rag/direct_web_search_planner.py:159`：模型只能从后端提供的真实候选 URL 中选择，返回不在候选集合中的 URL 会被丢弃，不能自由拼接地址。
- `src/fast_app/graph/rag_agent/rag_agent_nodes.py:81`：后端确定性校验搜索结果域名、URL 片段和主题条件。
- `src/fast_app/graph/rag_agent/rag_agent_nodes.py:117`：当搜索提供商没有召回精确官方页面时，读取该官方网站的标准 `sitemap.xml`，按当前 query 计算通用候选；没有产品、版本或主题硬编码。
- `src/fast_app/graph/rag_agent/rag_agent_nodes.py:98`：按 `article → main → body` 提取网页主内容，避免站点导航耗尽 RAG 上下文预算。
- `src/fast_app/graph/rag_agent/rag_agent_nodes.py:167`：统一串联搜索规划、Bocha 真实搜索、sitemap 候选、候选选择、HTTP 读取和 `RetrievedDoc` 构造。
- `src/fast_app/components/llms/qwen_langchain_llm_client.py`、`src/fast_app/services/rag/rag_context_builder.py`：把回答语义从“知识库”改为“当前检索上下文”，并允许引用公开网页 URL。

真实 Web 页面使用 `POST /rag/chat/stream/events`，冻结输入为：

```text
请联网查询 PostgreSQL 16 官方文档中行级安全策略的作用，并给出来源链接。
```

最终结果：

- request/trace ID：`c97258896f554f5e8c2a772dc2d60fc3`。
- Router intent：`web_research`。
- 未创建 TaskPlan，符合简单纯 Web 边界。
- Source 只有 `https://www.postgresql.org/docs/16/ddl-rowsecurity.html`。
- 后端日志记录 Bocha 搜索、读取标准 sitemap，并对模型从真实候选中选择的官方 URL 执行 `GET`，HTTP 200。
- 最终回答正确说明 per-user 行过滤、RLS 启用、默认拒绝、owner 豁免等机制，并包含上述来源链接。
- 结构化 SSE 收到 `sources`、多段 `answer_delta` 和 `done`。

为证明实现不是只适配 PostgreSQL，额外执行了冻结场景之外的交叉验证：

```text
请联网查询 FastAPI 官方文档中使用多个 Worker 部署的作用，并给出来源链接。
```

- request/trace ID：`7e11c7464ffd49528a90e40f2e218cda`。
- Router intent：`web_research`，未创建 TaskPlan。
- Source：`https://fastapi.tiangolo.com/deployment/server-workers/`。
- 回答正确说明进程复制可利用多核 CPU 并处理更多请求，包含官方来源链接。
- 结构化 SSE 收到 `sources`、`answer_delta` 和 `done`。

排查中还观察到两个不能计为通过的中间结果：一是模型猜测不存在的 `/deployment/multiple-workers/` 路径；二是正确 URL 的导航文本挤占上下文，导致回答“证据不足”。最终实现分别通过“只允许真实候选 URL”和“优先提取 article 主内容”修复。

结论：11.3 已通过 PostgreSQL 原场景和 FastAPI 跨主题场景的真实流式 Web 验证。最终证据页面、主题和版本均匹配问题，生产代码中不再存在针对测试问题的固定地址。

### 16.2 11.4 Evidence Evaluator 修复

修改位置：

- `src/fast_app/services/research/research_evidence_evaluator.py:40`：Evaluator 同时兼容旧 `AgentTaskSubQuestion` 和 Research v2 `ResearchTaskSubQuestion`；v2 从覆盖的 Requirement 读取结构化证据契约。
- `src/fast_app/services/research/research_worker_agent.py:200`：Worker 根据 `covers_requirement_ids` 找到当前子问题对应的 Requirements，并显式传给 Evaluator；旧 TaskPlan 继续使用原有契约。

真实 Web 页面使用 `POST /rag/chat/stream/events` 创建并确认复杂纯 Web 任务：

```text
请联网比较 PostgreSQL 16 的 RLS 与 security_invoker 视图分别解决什么问题、
如何配合，并基于至少两份官方网页证据给出适用边界。
```

运行标识：

- TaskPlan ID：`task_plan_20260804091105_f2e7acc7fc2b`。
- 执行 request/trace ID：`3334020a5fc94f058120a70a5fa2b880`。
- TaskPlan 最终状态：`completed`。

Evaluator 的实际语义结果：

- SQ1 为 `partial`：明确指出第三方来源较多，缺少 PostgreSQL 16 官方文档直接引用。
- SQ2 为 `partial`：明确指出只有一份 PostgreSQL 官方页面，缺少第二份官方网页证据。
- SQ3 为 `completed`。
- runtime JSON 与后端日志中均未再出现 `Evaluator 不可用: AttributeError`。

结论：11.4 的模型契约不兼容错误已经修复。Evaluator 不再因读取不存在的 `sub_question.expected_evidence` 崩溃，而是能够基于 Requirement 契约给出有业务含义的证据充分性判断。

### 16.3 本轮明确没有修复的独立问题

本次真实运行再次证明 11.5 仍存在：SQ1、SQ2 已被 Evaluator 判为 `partial`，但 Requirement Aggregator 仍将 R1～R4 标记为 `satisfied`，并继续完成 Final Synthesis。因此：

- 11.3：已修复并通过。
- 11.4：已修复并通过。
- 11.5：仍未修复，不能因为 TaskPlan 最终为 `completed` 就判定证据质量通过。

### 16.4 自动化回归

以下脚本通过：

```powershell
$env:PYTHONPATH = "src"
$env:LANGSMITH_TRACING = "false"

.\.venv\Scripts\python.exe scripts\phase_15\test_agent_task_router.py
.\.venv\Scripts\python.exe scripts\phase_15\test_research_task_plan_v2.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agentic_research_orchestration.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_task_tool_loop.py
.\.venv\Scripts\python.exe scripts\phase_15\test_agent_conversation_context.py
.\.venv\Scripts\python.exe scripts\phase_15\test_schema_field_descriptions.py
.\.venv\Scripts\python.exe scripts\test_langsmith_tracing.py
```

## 17、Direct Web 修复的遗留问题（2026-8-6）

### 〇、修复范围回顾（Git 视角）

| 提交               | 内容                                                         |
| ------------------ | ------------------------------------------------------------ |
| `4307ef3`（08-04） | 11.3/11.4 主体修复：新增 `direct_web_search_planner.py`（+202）、`rag_agent_nodes.py`（+214）、`rag_context_builder.py` 语义修改，以及大量测试日志/TaskPlan 运行产物 |
| `d3f2443`（08-06） | planner 优化、强化约束规则：`direct_web_search_planner.py`（+96/-）、`rag_agent_nodes.py`（+20），提交信息自注 **"TODO：未测试"** |

⚠️ 最新提交自注"未测试"，说明第二次约束强化（source_mode 四枚举、community/specified_site 分支等）尚无真实 Web 验证，这是本次稳定性评估的重点。

---

### 一、风险点逐项评估

### 风险 2：sitemap 补充逻辑健壮性 —— **部分修复**

[_official_sitemap_candidates](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L117-L164) 现状：

- ✅ 网络异常/XML 解析失败 → `except (httpx.HTTPError, ElementTree.ParseError): return []`，有明确降级
- ✅ 响应 > 5MB 直接放弃；候选只接受 `https` 且域名属于 site/子域
- ❌ **只尝试固定路径 `https://{site}/sitemap.xml`**：不读 `robots.txt`，不解析 sitemap index。许多站点根路径返回的是 `<sitemapindex>`，其中 `<loc>` 指向的是子 sitemap 的 XML 地址——这些 URL 会参与 token 打分并被当作页面候选，最终 GET 到的是 XML 文本而非网页正文
- ❌ **纯中文 query 基本失效**：打分 token 用 `re.findall(r"[A-Za-z0-9]+")` 只提取英文/数字，中文官网查询的 `needles` 为空集，`ranked` 恒为空
- ❌ 打分只看 URL 文本匹配（`token in compact_url`），无版本优先级；候选 `title=url、summary="official sitemap candidate"`，选择器模型拿到的语义信息很少

### 风险 3：内容提取 article → main → body —— **部分修复**

[_direct_page_text](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L98-L114)：

- ✅ 提取主容器后又移除 `script/style/nav/header/footer`，配合下游 [format_doc_for_context](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/rag_context_builder.py#L26-L43) 的 1500 字符硬截断，**上下文预算耗尽问题已被封死**（16.1 观察到的 FastAPI 导航挤占问题）
- ❌ 正则 `(?is)<{tag}\b[^>]*>(.*?)</{tag}>` 是**非贪婪首匹配**：页面存在多个 `<article>`（列表页、相关推荐卡片在前）时只取第一个，可能取到无关块
- ❌ 三个容器都不存在（SPA/JS 渲染页面）时直接走整页 HTML 兜底，此时提取到的就是骨架占位文本
- ⚠️ 截断到 1500 字符后，官方文档页开头的面包屑/目录/警告框可能吃掉全部有效预算，真正答案段落被截掉

### 风险 4：阶段失败时的行为 —— **已修复（无静默无约束降级），但错误语义不统一**

逐步核对 [call_direct_web_node](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L175-L313) 的每条失败路径：

| 阶段                   | 失败行为                                                     |
| ---------------------- | ------------------------------------------------------------ |
| ① plan 生成失败        | 抛 `ExternalServiceError("Direct Web 搜索参数生成失败")` ✅ 明确 |
| ② 官方问题但 site 缺失 | 抛 `ExternalServiceError("Direct Web 未能确定用户要求的官方网站")` ✅ 明确 |
| ③ Bocha 失败           | 底层抛 `ExternalServiceError` ✅ 明确                         |
| ④ sitemap 失败         | 静默返回 `[]`，但后续候选为空 → 最终在 L306-307 抛 `"Web Search 未返回可用结果"` ✅ 终态明确 |
| ⑤ 候选选择 LLM 失败    | 抛 `ExternalServiceError("Direct Web 候选页面选择失败")` ✅ 明确 |
| ⑥ 模型返回候选外 URL   | `selected_url not in allowed_urls → None`（L240-242）✅ 丢弃  |
| ⑦ GET 选中页失败       | `direct_doc=None` → 回退 `strict_results[:1]`（摘要级内容，**仍通过严格域名/片段/主题过滤**），为空则抛错 |

**关键结论**：所有进入 `docs` 的结果都经过 `_matches_direct_web_plan` 过滤，**不存在回退到"未过滤 raw_results"的路径**，不会静默降级为无约束搜索。唯一的降级是"全文读取失败 → 用搜索摘要"，约束仍然生效。

**残留问题**：与 `call_knowledge_retrieval` 节点不同，本节点异常**没有经过 `classify_agent_error` 分类**、不产生 `error_decision`，是裸异常直接抛出，前端拿到的错误语义结构化程度较低。

### 风险 5：测试场景硬编码 —— **已修复**

全量 grep `src/fast_app` 下 `postgresql.org / rowsecurity / RLS`：

- 无任何固定文档 URL 残留；`RLS` 仅出现在 nl2sql 服务（合法业务域）
- 唯一边缘项：[agent_task_router.py L84](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/agent_tasks/agent_task_router.py#L84) 的 Router Prompt 中有一条 `"联网比较 PostgreSQL RLS 与 security_invoker"` 的 few-shot 示例——属于意图分类示例而非 URL 硬编码，风险极低，但可能让 Router 对该措辞过度倾向 `question_decomposition`

与文档 16.1 的陈述一致：第一次的固定 URL 拼接修复已撤销，当前实现无产品/版本/主题业务分支。

---

### 二、额外发现的不稳定因素（不在五个问题内）

1. **跨域重定向未校验**（[rag_agent_nodes.py L192](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L192)、L265）：`httpx.AsyncClient(follow_redirects=True)` GET 选中 URL 后**没有检查最终 `response.url` 的域名**。候选 URL 虽然都通过域名校验，但服务器可以 302 到任意第三方域名，正文即脱离官方约束。
2. **multiple_sources + official 组合深度不足**（L282-287）：`else` 分支只做过滤，不读取全文，doc content 仅为 `title+snippet+summary+url`。"要求多份官方证据"的场景答案质量依赖 Bocha 摘要。
3. **`required_content_terms` 存在误杀风险**（L92-95）：主题词在 `title+snippet+summary` 中做子串匹配，Bocha summary 常为空，正确官方页面可能因摘要未含主题词被过滤——表现为"搜得到但全被拒"，最终抛"未返回可用结果"。
4. **exact_url 会无条件加入候选**（L232-239）：Prompt 要求"不知道就填 null"，但模型若幻觉一个通过 Schema 校验的 URL，它会绕过"只从真实候选选择"的设计意图直接进入候选池。Schema 校验只能保证格式与域名一致，不能保证页面存在且匹配。

---



## 17.1 风险二的具体原因（2026年8月6日）

这三个问题都集中在 [_official_sitemap_candidates](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L117-L164) 这一个函数里。先交代它的触发时机：只有当 Bocha 搜索**没有召回任何通过严格校验的页面**（`strict_results` 为空）、且 `source_mode="official"` 时才会走到这里（[rag_agent_nodes.py L224-231](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L224-L231)）。也就是说它是整条链路的"最后救援手段"，它的缺陷直接决定救援成功率。

---

### 缺陷 1：只试固定路径 `/sitemap.xml`，且不处理 sitemap 索引

**相关代码**（[L127-134](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L127-L134)）：

```python
response = await http_client.get(
    f"https://{plan.site}/sitemap.xml",
    timeout=10.0,
)
response.raise_for_status()
...
root = ElementTree.fromstring(response.content)
```

**为什么有风险**——两个子问题：

**(a) 路径是猜的。** 网站 sitemap 的真实位置按标准应该写在 `robots.txt` 的 `Sitemap:` 字段里，很多站点的路径是 `/sitemap_index.xml`、`/sitemap-index.xml` 或 `/wp-sitemap.xml`。这些站点的 `/sitemap.xml` 返回 404 → `raise_for_status()` 抛异常 → 被 except 捕获返回 `[]` → 救援静默失败。结果是"功能看起来正常，实际对大部分站点从未生效过"。

**(b) 不区分 sitemap 索引和页面列表。** 大型站点（文档站尤其常见）的 `/sitemap.xml` 根节点是 `<sitemapindex>`，里面的 `<loc>` 指向的是**子 sitemap 的 XML 地址**，不是网页：

```xml
<sitemapindex>
  <sitemap><loc>https://example.com/sitemap-docs-1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sitemap-blog.xml</loc></sitemap>
</sitemapindex>
```

而提取代码是这样遍历的（[L145-147](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L145-L147)）：

```python
for element in root.iter():
    if not element.tag.endswith("loc") or not element.text:
        continue
```

它只认"标签名以 `loc` 结尾"，**无法区分这个 `<loc>` 属于 `<url>`（网页）还是 `<sitemap>`（索引）**。于是 `.xml` 结尾的子 sitemap 地址会被当成网页候选参与打分。如果后续选择器模型选中了它，[L265](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L265) 会真的去 GET 这个 XML 文件，`_direct_page_text` 找不到 article/main/body 就把整份 XML 剥标签后塞进上下文——全是 URL 文本，没有任何答案内容。

---

### 缺陷 2：纯中文 query 时打分词集为空，救援整体失效

**相关代码**（[L138-143](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L138-L143)）：

```python
needles = {
    token.lower()
    for value in (plan.query, *plan.required_content_terms)
    for token in re.findall(r"[A-Za-z0-9]+", value)
    if len(token) >= 2
}
```

**为什么有风险**：`re.findall(r"[A-Za-z0-9]+", ...)` 只提取 ASCII 字母和数字。举例：

| query                                      | needles 结果                               |
| ------------------------------------------ | ------------------------------------------ |
| `PostgreSQL 16 row level security`         | `{postgresql, 16, row, level, security}` ✅ |
| `PostgreSQL 16 行级安全策略`               | `{postgresql, 16}` ⚠️ 尚可                  |
| `查询某国产数据库官方文档中主备切换的配置` | `{}` ❌ 空集                                |

needles 为空后，看打分这一行（[L157-159](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L157-L159)）：

```python
score = sum(token in compact_url for token in needles)
if score:
    ranked.append((score, url))
```

对空集求和永远是 0 → `if score:` 永远为假 → `ranked` 为空 → 函数返回 `[]`。

也就是说：**凡是中文官网 + 中文 query 的场景，sitemap 救援机制从头到尾不会产出任何候选**，然后链路以"Web Search 未返回可用结果"报错结束。这不是偶发质量问题，是整类场景的结构性盲区。

---

### 缺陷 3：打分和候选信息都太弱，选择器模型"盲选"

**相关代码**（[L156-163](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py#L156-L163)）：

```python
compact_url = re.sub(r"[^a-z0-9]", "", url.lower())
score = sum(token in compact_url for token in needles)
...
ranked.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
return [
    {"title": url, "url": url, "summary": "official sitemap candidate"}
    for _, url in ranked[:20]
]
```

三个叠加的问题：

**(a) 子串匹配没有区分度。** 打分是把 URL 里所有非字母数字字符剥掉后做 `token in compact_url`。像 `docs`、`16` 这类词会命中该站点的**几乎每一个页面**（PostgreSQL 文档全在 `/docs/16/` 下），导致大量页面同分。

**(b) 同分时按 URL 长度升序排。** `sort` 的第二个键是 `len(item[1])`——越短越靠前。同分情况下，`https://www.postgresql.org/docs/16/` 这种**章节首页**会排在 `https://www.postgresql.org/docs/16/ddl-rowsecurity.html` 这种**真正答案页**前面。救援本意是找精确页面，排序规则却优先给泛化入口页。

**(c) 交给选择器的候选没有任何语义信息。** 候选字典里 `title` 就是 URL 本身，`summary` 是固定字符串 `"official sitemap candidate"`。对比 Bocha 真实结果（有真实标题和摘要），选择器模型在这里只能看 URL 路径串做判断。再叠加 [planner 只取前 10 个候选](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/direct_web_search_planner.py#L221)（`candidates[:10]`），而排序又偏向短 URL——正确答案页完全可能被挤在 10 名之外，选择器根本看不到它。

---

### 总结：三个缺陷的联动后果

```
Bocha 未召回官方页面
   ↓
sitemap 救援触发
   ↓
缺陷1: 站点没有 /sitemap.xml 或是 sitemap 索引 → 返回 [] 或返回 XML 地址
缺陷2: 中文 query → needles 空 → 必然返回 []
缺陷3: 即使有候选，排序偏向泛化页 + 选择器盲选 + 只取前10 → 选错或选不到
   ↓
最终 "Web Search 未返回可用结果"，或更糟：把 sitemap XML 文本当正文喂给生成层
```

其中**缺陷 2 是必现的**（中文 query 100% 失效），**缺陷 1 的 (b) 是最危险的**（不是失败，而是产出错误内容），**缺陷 3 是概率性的**（降低救援命中率）。

需要我按这三个点给出具体修复方案吗？



## 17.1.1风险二的修复方案（2026年8月6日）

下面给出完整修复方案，只描述设计与代码，**不修改任何文件**。所有改动集中在 [rag_agent_nodes.py](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/graph/rag_agent/rag_agent_nodes.py) 的 sitemap 救援部分，`create_call_direct_web_node` 的调用点签名不变。

---

### 一、结构重构：拆出三个可独立测试的纯函数

当前 `_official_sitemap_candidates` 把"发现 sitemap、解析 XML、打分排序"混在一起，无法离线测试。重构为：

```
_official_sitemap_candidates()          # 编排层，签名不变
  ├── _collect_sitemap_page_urls()      # 修复缺陷 1：发现 + 解析
  │     ├── _robots_sitemap_urls()
  │     ├── _fetch_sitemap_tree()
  │     └── _sitemap_child_locs()
  └── _rank_sitemap_candidates()        # 修复缺陷 2、3：纯函数，可离线测试
```

---

### 二、缺陷 1 修复：路径发现 + 区分索引与页面

### 1a. robots.txt 回退（解决 `/sitemap.xml` 404 静默失效）

```python
_SITEMAP_DEFAULT_PATH = "/sitemap.xml"
_SITEMAP_MAX_BYTES = 5_000_000
_SITEMAP_MAX_CHILD_INDEXES = 3   # 索引最多展开 3 个子 sitemap
_SITEMAP_MAX_ROBOTS_DECLARED = 2 # robots.txt 最多尝试 2 个声明地址

async def _robots_sitemap_urls(http_client, *, site: str) -> list[str]:
    """按标准从 robots.txt 读取 Sitemap: 声明；失败返回空列表。"""
    try:
        response = await http_client.get(f"https://{site}/robots.txt", timeout=10.0)
        response.raise_for_status()
    except httpx.HTTPError:
        return []
    declared: list[str] = []
    for line in response.text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("sitemap:"):
            declared.append(stripped[len("sitemap:"):].strip())
    return declared
```

### 1b. 只收集直接子节点的 `<loc>`（解决索引地址被当页面）

旧代码 `root.iter()` + `tag.endswith("loc")` 无法区分 `<url><loc>` 和 `<sitemap><loc>`。新代码按**节点类型**分别收集：

```python
def _xml_local_name(tag: object) -> str:
    """去掉 XML 命名空间前缀；注释等非字符串节点返回空串。"""
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1].lower()

def _sitemap_child_locs(root, *, child_kind: str) -> list[str]:
    """只收集根节点直接子节点中指定类型（url 或 sitemap）的 <loc>。

    sitemapindex 的子节点是 <sitemap>，urlset 的子节点是 <url>；
    按类型收集后，索引地址不会再被当成网页候选。
    """
    locs: list[str] = []
    for element in root:
        if _xml_local_name(element.tag) != child_kind:
            continue
        for child in element:
            if _xml_local_name(child.tag) == "loc" and child.text:
                locs.append(child.text.strip())
    return locs
```

### 编排层：先标准路径，再 robots；遇索引只展开一层

```python
async def _collect_sitemap_page_urls(http_client, *, site: str) -> list[str]:
    lower_site = site.lower()

    def allowed(url: str) -> bool:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (
            hostname == lower_site or hostname.endswith(f".{lower_site}")
        )

    def pages_from_tree(root) -> list[str]:
        pages = [u for u in _sitemap_child_locs(root, child_kind="url") if allowed(u)]
        if pages:
            return pages
        # 根是 <sitemapindex>：只展开一层，不递归，防止无限下载
        collected: list[str] = []
        for sub in _sitemap_child_locs(root, child_kind="sitemap")[:_SITEMAP_MAX_CHILD_INDEXES]:
            if not allowed(sub):
                continue
            sub_root = await _fetch_sitemap_tree(http_client, sub)  # 见下方说明
            if sub_root is not None:
                collected.extend(
                    u for u in _sitemap_child_locs(sub_root, child_kind="url") if allowed(u)
                )
        return collected
    ...
    root = await _fetch_sitemap_tree(http_client, f"https://{site}{_SITEMAP_DEFAULT_PATH}")
    if root is not None:
        return pages_from_tree(root)
    # 缺陷 1a：标准路径不存在时回退 robots.txt 声明
    for declared in await _robots_sitemap_urls(http_client, site=site)[:_SITEMAP_MAX_ROBOTS_DECLARED]:
        declared_root = await _fetch_sitemap_tree(http_client, declared)
        if declared_root is not None:
            pages = pages_from_tree(declared_root)
            if pages:
                return pages
    return []
```

> 注：`pages_from_tree` 因内部 await 需定义为内层 async 函数；`_fetch_sitemap_tree` 即现有 GET + 5MB 上限 + `except (httpx.HTTPError, ElementTree.ParseError)` 逻辑原样提取。HTTP 请求总量上界约 1 + 3（索引展开）+ 1（robots）+ 2×(1+3)（声明回退）≈ 13 次，全部 10 秒超时，不会无限膨胀。

---

### 三、缺陷 2 修复：中文 query 的确定性回退

先说明一个事实：官方站点 URL 几乎全是 ASCII，**把中文分词拿去匹配 URL 永远命不中**，所以正确做法不是"提取中文 token"，而是承认 URL 文本排序失效，走结构化回退：

```python
_ASCII_TOKEN = re.compile(r"[A-Za-z0-9]{2,}")
_DOC_PATH_HINTS = ("/docs/", "/doc/", "/documentation/", "/guide/", "/help/", "/wiki/", "/manual/")

def _sitemap_needles(plan: DirectWebSearchPlan) -> set[str]:
    """打分词集合：query + 主题词 + URL 片段约束（新增 fragments，信号更准）。"""
    return {
        token.lower()
        for value in (
            plan.query,
            *plan.required_content_terms,
            *plan.required_url_fragments,
        )
        for token in _ASCII_TOKEN.findall(value)
    }

def _doc_root_score(url: str) -> int:
    lowered = url.lower()
    return sum(hint in lowered for hint in _DOC_PATH_HINTS)
```

打分逻辑中（见下一节）：`needles` 非空走 URL 文本打分；**为空时不再返回全空，而是回退到文档目录启发式**，仍无候选才返回 `[]` 走原有明确报错路径——不产生静默垃圾。

---

### 四、缺陷 3 修复：IDF 加权 + 深路径优先 + 候选携带命中信息

```python
def _rank_sitemap_candidates(entries: list[str], needles: set[str]) -> list[dict[str, str]]:
    """纯函数：把去重后的 sitemap 页面 URL 排序成最多 20 个候选。"""
    unique_entries = list(dict.fromkeys(entries))

    if needles:
        hits: list[tuple[str, set[str]]] = []
        doc_freq: dict[str, int] = defaultdict(int)
        for url in unique_entries:
            compact = re.sub(r"[^a-z0-9]", "", url.lower())
            matched = {token for token in needles if token in compact}
            if matched:
                hits.append((url, matched))
                for token in matched:
                    doc_freq[token] += 1
        # 修复 3a：docs/16 这类泛化词几乎命中全站，用 1/文档频率加权拉开区分度
        scored = [
            (sum(1.0 / doc_freq[token] for token in matched), url, matched)
            for url, matched in hits
        ]
        # 修复 3b：同分优先深路径（具体页面），废弃旧版"URL 越短越靠前"
        scored.sort(key=lambda item: (-item[0], -item[1].count("/"), item[1]))
        return [
            {
                "title": url,
                "url": url,
                # 修复 3c：把命中的词交给选择器模型，不再是固定字符串
                "summary": f"official sitemap candidate; matched: {', '.join(sorted(matched))}",
            }
            for _, url, matched in scored[:20]
        ]

    # 缺陷 2 回退：纯中文 query 没有可用 ASCII 词，退化为文档目录启发式
    doc_pages = [url for url in unique_entries if _doc_root_score(url)]
    doc_pages.sort(key=lambda url: (-_doc_root_score(url), url))
    return [
        {"title": url, "url": url, "summary": "official sitemap candidate; doc-path heuristic"}
        for url in doc_pages[:20]
    ]
```

### 可选配套改动（planner 侧 1 行）

候选选择器目前只取前 10 个候选（[direct_web_search_planner.py L221](file://d:/AI_Agent_Project/AI_Python_Project/python-agent-study/src/fast_app/services/rag/direct_web_search_planner.py#L221) 的 `candidates[:10]`）。sitemap 候选本身缺少标题语义，建议放宽到 `candidates[:15]`，给选择器更多可见范围。**此项可选，默认建议一起改。**

---

### 五、行为对比表

| 场景                                                | 修复前                                                       | 修复后                                                    |
| --------------------------------------------------- | ------------------------------------------------------------ | --------------------------------------------------------- |
| 站点只有 `/sitemap_index.xml` 或位置写在 robots.txt | 404 → 静默返回 `[]`                                          | robots.txt 声明回退                                       |
| `/sitemap.xml` 是 sitemapindex                      | 子 sitemap 的 **XML 地址被当页面候选**，可能被 GET 后喂给生成层 | 按 `<url>`/`<sitemap>` 类型区分，索引只展开一层取真实页面 |
| 纯中文 query                                        | needles 空 → **必然返回 `[]`**                               | 回退到文档目录启发式候选，选择器可判 null，无候选才报错   |
| `docs`、`16` 等泛化词命中全站                       | 全部同分，按 URL 长度升序 → **章节首页排最前**               | IDF 加权 + 深路径优先 → 具体页面排前                      |
| 选择器拿到的信息                                    | title=URL、summary 固定串                                    | summary 附带命中词列表                                    |

### 六、测试方案

新增 `scripts/phase_15/test_direct_web_sitemap.py`（离线、不发网络请求）：

1. **urlset 正常解析**：构造小型 XML，断言候选 URL 与命中词
2. **sitemapindex 展开**：索引 XML + mock 子 sitemap，断言不返回 `.xml` 地址
3. **纯中文 query**：needles 空 → 走 doc-path 启发式分支的断言
4. **泛化词排序**：构造 `/docs/16/` 与 `/docs/16/ddl-rowsecurity.html`，断言后者排前
5. robots.txt 回退用 mock http_client 断言

真实 Web 验证沿用现有冻结问题，另加一个 sitemapindex 型站点（如 WordPress 类文档站）实测。

---

请审核。需要调整的点（例如：是否加 robots.txt 回退、`candidates[:15]` 是否采纳、doc-path 启发式的路径清单）确认后我再动手实施。

## 18、遗留问题修复方案：web sitemap 搜索匹配质量低

[文档技术点讲解](D:\AI_Agent_Project\AI_Python_Project\python-agent-study\scripts\docs\TaskPlan--web搜索质量提升技术方案：.md)

