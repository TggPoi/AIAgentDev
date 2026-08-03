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
