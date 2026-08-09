# GitLab 文档变更端到端测试报告

## 1. 测试目标与约束

- 测试日期：2026-07-26
- 测试环境：本地 GitLab CE、FastAPI、PostgreSQL、Elasticsearch、Milvus。
- 知识向量：全部使用真实 Qwen Embedding，不混用历史 Mock Embedding。
- 正式文档来源：GitLab 私有 Project 的 `main` 分支。
- 发布约束：分支和 Merge Request 阶段不得修改 RAG；仅 MR 合并进入 `main` 后由 Webhook 触发同步。
- 账号约束：人工测试账号只分配到 `development` Project，不加入顶层 Group。
- 问题处理：本轮只记录逻辑错误和系统 Bug，不修改业务代码。

## 2. 测试环境与初始基线

### 2.1 工作区

- 工程目录：`D:\AI_Agent_Project\AI_Python_Project\python-agent-study`
- 测试开始时工作区已有 GitLab 接入相关未提交修改；本轮保留这些修改。
- 测试报告是本轮唯一计划新增的工程文件。

### 2.2 服务与数据基线

- GitLab CE：`gitlab-dev`，健康，Web 端口 `8929`，SSH 端口 `2424`。
- PostgreSQL：`pg_vector_db`，健康；初始正式知识版本 `1`。
- Elasticsearch：`es-dev`，初始索引 `python_agent_demo_chunks` 有 `462` 条记录。
- Milvus：`milvus-standalone`，初始 Collection `python_agent_demo_chunks` 有 `260` 条记录。
- GitLab 同步初始状态：4 个成功任务、9 个 GitLab 文档、4 个知识变更事件。
- FastAPI `8000` 和静态验收页 `5173` 在测试开始时未启动。
- PostgreSQL 验收前备份：
  `D:\SoftwareAI\GitlabDev\backups\python_agent_study_pre_gitlab_e2e_20260726_201729.dump`
  （13,172,410 字节）。
- GitLab 未认证访问 `/api/v4/version` 返回 `401`；服务健康状态以后续 Web 页面、
  GitLab 数据库和提交 SHA 共同验证。
- 清理结果：仅删除 ES/Milvus 知识索引和 GitLab/RAG 派生表；13 个用户、
  4 个 GitLab Source 以及部门、角色、权限配置均保留。
- 真实 Qwen 联合 Bootstrap 任务：
  `gitlab_job_2c6a3da9a34a4eb49a0d951cd9f6cf12`，状态 `succeeded`。
- Bootstrap 发布结果：正式版本 `1`，9 个文档、202 个父块、260 个子块；
  ES 共 462 条父子记录，Milvus 共 260 条子块，向量维度为 `1024`。
- 四个 Source 的 `last_synced_sha` 与 `desired_sha` 一致。
- FastAPI `/health` 返回 `200 {"status":"ok"}`；现有 Web 验收页返回 `200`；
  独立真实 Qwen Worker 已启动。

## 3. 测试账号与权限

| 账号 | 模拟身份 | GitLab 范围 | 预期角色 | 状态 |
|---|---|---|---|---|
| `tech-developer-e2e` | 技术部真实员工 | `development` Project（ID 36） | Developer（30） | 已激活并通过 Web 登录验证 |
| `tech-maintainer-e2e` | 技术部部门主管 | `development` Project（ID 36） | Maintainer（40） | 已激活，待审核场景登录验证 |

密码、Token 和 Webhook Secret 不写入本报告。

账号均通过 GitLab Web 注册页创建。GitLab 数据库验证两者只存在
`source_type=Project, source_id=36` 的成员关系，没有加入顶层 Group。

## 4. 场景 1：Developer 修改现有 Markdown 文档

### 4.1 测试目标

Developer 在分支中实质修改 `development/rag-backend-deployment.md`，创建 MR；Maintainer 审核并合并；验证合并前 RAG 不变化，合并后内容和版本正确发布。

### 4.2 测试过程、步骤与结果

1. Developer 在 GitLab Web 打开
   `development/rag-backend-deployment.md`，进入单文件编辑器。
2. 新增“21. GitLab 文档发布链路与运维检查”章节，共增加 26 行，
   包含发布前检查、合并后检查和失败处理，不是单句占位修改。
3. 点击提交时，GitLab 明确提示 Developer
   `You don't have permission to commit to main`，只能填写新分支。
4. Developer 创建分支 `e2e/developer-update-deployment`，
   Commit `31bdb272bcfa6d107a14957f83e0ebeff8fd02b5`，并创建 MR `!1`：
   `docs: add GitLab publication operations checks`。
5. MR 未合并时验证：
   - GitLab `main` SHA 仍为 `42144c592d6ebdabe8f0ea6b732f581c4568c940`。
   - 正式知识版本仍为 `1`。
   - Source 的 `last_synced_sha` 和 `desired_sha` 均仍为 `42144c592d6e`。
   - 同步任务仍只有 Bootstrap 任务，Webhook Delivery 为 `0`。
   - ES 仍为 462 条，Milvus 仍为 260 条。
6. Maintainer 登录后打开 MR Changes，确认只有 1 个文件、增加 26 行，
   勾选 Viewed，点击 Approve，再点击 Merge。
7. GitLab 显示 MR `Merged`，新 `main` SHA 为
   `0a114b3177018cd00dc87b50f26fa980da73cf0e`。
8. Webhook 产生 1 条 Delivery；Worker 增量任务
   `gitlab_job_59ba96ebf16d4fc6a56d7077a38c0090` 成功。
9. 正式知识版本由 `1` 原子切换为 `2`，Source 的两个 SHA 均更新为
   `0a114b317701`；版本 2 通知事件只包含被修改文档。
10. GitLab Raw 文件 SHA-256 与 Manifest `content_hash` 均为
    `32c126635edd3999b9e48a60a28d562c4d5f7be332c3c0e5b280472bba21f73a`，
    且 Raw 内容包含新增标题和唯一关键词“合并后原子发布检查”。
11. 版本 2 为该文档写入 30 个父块和 31 个子块：
    - ES 总量由 462 增至 523；旧 53 条记录 `valid_to_version=2`，
      新 61 条记录 `valid_from_version=2, valid_to_version=0`。
    - Milvus 总量由 260 增至 291；旧 27 个子块关闭于版本 2，
      新增 31 个有效子块；Milvus 中未出现父块。

结果：**通过**。Developer 无法直接写 `main`，MR 阶段 RAG 未变化，
Maintainer 审批合并后才触发一次正式发布，文件内容和父子块版本均一致。

## 5. 场景 2：Developer 新增 Markdown 文档

### 5.1 测试目标

Developer 新建有真实业务价值的 `development/knowledge-publication-operations.md`，创建 MR；Maintainer 审核并合并；验证新增文档正确发布。

### 5.2 测试过程、步骤与结果

1. Developer 在 GitLab Web 新建
   `development/knowledge-publication-operations.md`。
2. 文档共 60 行，包含角色职责、任务状态表、日常发布检查、Webhook/Worker/
   Compare 故障恢复、GitLab Revert 回滚原则和验收清单；唯一检索词为
   “知识发布值班核验标识”。
3. GitLab 再次明确提示 Developer 无权提交到 `main`。
4. Developer 创建分支 `e2e/developer-add-publication-ops`，
   Commit `d25c729939b38e08d8c93d117f3ca8e22174c159`，并创建 MR `!2`：
   `docs: add knowledge publication operations runbook`。
5. MR 未合并时验证：
   - `main` SHA 仍为 `0a114b3177018cd00dc87b50f26fa980da73cf0e`。
   - 正式版本仍为 `2`，Manifest 文档数仍为 9，Webhook Delivery 仍为 1。
   - ES 仍为 523 条，Milvus 仍为 291 条。
6. Maintainer 在 Changes 页面确认仅新增目标文件，并看到文档唯一检索词；
   勾选 Viewed、Approve 后合并。
7. MR `!2` 显示 `Merged`，新 `main` SHA 为
   `74e9752d76095c7aaabb0355222e68eb7eff2299`。
8. Webhook Delivery 增至 2；增量任务
   `gitlab_job_f40cc477cfc34341a81d4ab582c5a4e2` 成功，正式版本由 2
   切换为 3，Manifest 文档数由 9 增至 10。
9. 版本 3 通知事件只包含新文档，`change_type=added`，ACL 为
   `visibility=department, allowed_departments=["development"]`。
10. GitLab Raw 文件和 Manifest 的 SHA-256 均为
    `f197edd05d67cba6544df172f0419594ea4bddf38467644cb4b78b4c88a9ddaf`，
    Raw 内容包含标题和唯一检索词。
11. 新文档在 ES 中有 11 个父块和 11 个子块，均从版本 3 生效；
    Milvus 只有 11 个子块。ES 总量为 545，Milvus 总量为 302。

结果：**通过**。新文档在 MR 阶段未进入 RAG，合并后以单一版本发布，
文档身份、内容哈希、ACL 和父子块存储规则正确。

## 6. 场景 3：Agent 根据用户 Query 创建 Markdown 文档

### 6.1 测试目标

通过现有 Web 验收页发起用户 Query，要求 Agent 创建 `development/gitlab-agent-mr-governance.md`；确认 Agent 只能创建临时分支、Commit 和 MR；Maintainer 合并后验证同步。

### 6.2 测试过程、步骤与结果

1. 在浏览器打开现有验收页
   `http://127.0.0.1:5173/rag_agent_manual_acceptance.html`，
   使用 `tool_manager` 登录，并设置独立会话
   `gitlab-agent-e2e-create-20260726`。
2. 输入真实业务 Query，要求 Agent 综合 GitLab 文档发布、Agent 文档工具和
   权限治理资料，创建
   `development/gitlab-agent-mr-governance.md`，内容必须覆盖机器人账号隔离、
   临时分支、乐观并发、MR 人工审核、main 保护、合并后同步、审计和验收清单。
3. 通过结构化 SSE 接口发起任务，系统成功路由到
   `knowledge_document_management`，生成 TaskPlan
   `task_plan_20260726124322_099b2df31bde`。
4. 真实 Qwen 链路已执行知识库混合检索、文档研究、撰写和审阅等步骤；
   TaskPlan 在运行过程中一度记录 11 个进度事件。
5. 任务运行约 5 分钟后以 `TimeoutError` 失败，未进入
   `waiting_confirmation`，因此网页上的“确认并执行 TaskPlan”不可执行，
   也未生成 GitLab 临时分支、Commit 或 MR。
6. 通过网页“重试 TaskPlan”从完整检查点恢复一次，
   `resume_count` 从 0 变为 1。恢复期间 Qwen 多次正常响应，进度事件重新增长，
   但约 302 秒后仍以 `TimeoutError` 失败，未进入人工确认。
7. 失败后进行副作用核验：正式知识版本仍为 3；技术部 Source 的
   `last_synced_sha` 和 `desired_sha` 均保持
   `74e9752d76095c7aaabb0355222e68eb7eff2299`；Webhook Delivery 仍为 2；
   `gitlab_change_requests` 总数及该 TaskPlan 对应记录均为 0。

结果：**失败**。安全边界正确，失败任务没有越过人工确认，也没有污染
GitLab 或正式知识库；但 Agent 在真实模型环境下无法在运行时限内生成可确认
预览，场景 3 无法继续完成 MR、Maintainer 合并和同步验收。

## 7. 场景 4：Agent 根据用户 Query 修改 Markdown 文档

### 7.1 测试目标

通过现有 Web 验收页发起用户 Query，要求 Agent 实质更新 `development/rag-deployment-checklist.md`；确认 Agent 只能提交 MR；Maintainer 合并后验证同步。

### 7.2 测试过程、步骤与结果

1. 在同一 Web 验收页设置独立会话
   `gitlab-agent-e2e-update-20260726`。
2. 输入真实业务 Query，要求先读取
   `development/rag-deployment-checklist.md`，保留原结构并补充完整的
   “GitLab 文档源与发布版本验收”章节，覆盖分支与 MR、main 保护、Webhook、
   独立 Worker、`publication_version`、ES/Milvus 父子块、ACL 和回滚检查。
3. 系统正确路由到 `knowledge_document_management`，TaskPlan
   `task_plan_20260726125202_0e6c31e664df` 的 deliverable 操作为 `update`，
   `target_hint` 为用户指定路径。
4. 真实链路完成知识库混合检索，但 GitLab Raw File API 实际读取的是
   `development/rag-backend-deployment.md`，未观察到读取明确指定的
   `development/rag-deployment-checklist.md`。
5. 后续一个 Qwen 调用连续发生单次 60 秒超时和自动重试，任务最终以
   `APITimeoutError: Request timed out.` 失败，没有进入人工确认，
   也没有创建 GitLab 分支、Commit 或 MR。
6. 通过网页“重试 TaskPlan”从检查点恢复一次，
   `resume_count` 从 0 变为 1；恢复仍停在同一模型步骤，约 184 秒后返回
   `failed`。
7. 最终副作用核验：知识版本仍为 3，ES 仍为 545 条，Milvus 仍为
   302 条，技术部 Source SHA 未变化，Webhook Delivery 仍为 2，
   `gitlab_change_requests` 仍为 0。

结果：**失败**。失败及重试均没有越过人工确认或污染正式数据，但 Agent
修改路径未能生成可审核预览，无法继续验证 MR、Maintainer 合并和同步。

## 8. 总体验收结果

- 场景 0：**通过**。新建 Developer 和 Maintainer 均已激活，仅授权技术部
  Project，角色分别为 Developer 和 Maintainer。
- 场景 1：**通过**。Developer 实质修改文档，MR 合并前 RAG 不变；
  Maintainer 合并后发布知识版本 2，修改内容和父子块正确同步。
- 场景 2：**通过**。Developer 创建真实文档，MR 合并前 RAG 不变；
  Maintainer 合并后发布知识版本 3，新文档内容和父子块正确同步。
- 场景 3：**失败**。Agent 创建文档及一次检查点恢复均在人工确认前超时，
  未创建 MR。
- 场景 4：**失败**。Agent 修改文档及一次检查点恢复均在人工确认前失败，
  未创建 MR。

结论：GitLab 人工文档变更、权限隔离、Webhook、Worker、版本发布以及
ES/Milvus 同步主链路已通过；Agent 到 GitLab MR 的端到端链路当前不可验收，
需要先修复本报告中的 Agent 运行与状态问题后复测场景 3、4。

## 9. 逻辑错误记录

### LOGIC-001：修改任务没有优先读取用户明确指定的目标文件

- 发生场景：场景 4。
- 现象：TaskPlan 的 `target_hint` 正确指向
  `development/rag-deployment-checklist.md`，但实际 GitLab Raw File
  请求读取了 `development/rag-backend-deployment.md`；任务失败前未观察到
  读取目标文件。
- 影响：即使后续模型调用成功，也存在基于错误原文生成修改预览的风险，
  无法保证“保留原有结构和内容”。
- 本轮处理：只记录，不修改 Agent 工具选择或目标文件约束。

## 10. 系统 Bug 记录

### BUG-001：真实 Agent 文档工作流被固定超时中断

- 发生场景：场景 3，Agent 创建 Markdown 文档。
- TaskPlan：`task_plan_20260726124322_099b2df31bde`。
- 现象：研究、撰写和审阅链路均已执行，但约 5 分钟后 TaskPlan 以
  `TimeoutError` 失败，无法进入人工确认和 GitLab MR 阶段。
- 证据：API 记录 `pipeline_stream_events` 耗时 `334735.77 ms`，
  最终原因是 `agent_task_failed`；TaskPlan `error` 为 `TimeoutError`。
- 影响：真实复杂文档创建请求无法端到端完成，场景 3 阻塞。
- 补充复测：从检查点恢复一次后 Qwen 调用正常、进度继续增长，但约
  `302412.18 ms` 后仍以 `TimeoutError` 失败。
- 根因复核：
  - 当前 `LLM_TIMEOUT_SECONDS=60`，
    `AGENT_DOCUMENT_WORKER_TIMEOUT_SECONDS=300`；
    Coordinator 模型调用上限为 12，三个 SubAgent 的模型调用上限各为 12，
    理论总预算可达到 48 次模型调用。
  - 首次执行共记录 45 次模型调用开始、44 次正常结束，没有发生 DashScope
    SDK 重试；44 次已完成调用的累计耗时约 290 秒，中位数约 2.5 秒，
    最长约 51.4 秒。
  - 检查点恢复再次记录 45 次模型调用开始、44 次正常结束，最后仍撞上
    300 秒总墙钟限制。
- 归因：主要原因是 Agent 多轮编排没有在总墙钟预算内收敛，模型调用数量预算
  与 300 秒总超时不匹配；不是某一次 DashScope 连接失败，也不是 VPN 代理节点
  延迟。
- 本轮处理：只记录，不修改超时配置、循环上限或业务代码。

### BUG-002：长任务的结构化 SSE 未实时显示中间事件

- 发生场景：场景 3。
- 现象：任务运行期间 Web 页持续显示“无 TaskPlan”，日志区只有
  “请求 /rag/chat/stream/events ...”；任务结束后，TaskPlan 创建、子 Agent
  启动、失败和 `done` 等事件才一次性显示。
- 影响：React 用户在数分钟运行期间无法看到 TaskPlan ID 和实际进度，
  不符合结构化 SSE 作为实时前端主链路的预期。
- 本轮处理：只记录，尚未定位是 Pipeline 产出时机、SSE 响应缓冲还是验收页
  消费逻辑导致。

### BUG-003：失败后的 TaskPlan 进度快照内部状态不一致

- 发生场景：场景 3。
- 现象：运行中 TaskPlan 曾保存 11 个进度事件，并出现 writer/reviewer
  完成事件；失败后的最终文件只保留 2 个事件，同时顶层状态为 `failed`，
  `document_progress.stage` 仍为 `deep_agent_running`，
  deliverable 状态仍为 `running`。
- 影响：失败审计信息丢失，管理端可能同时展示“任务失败”和“交付物运行中”。
- 本轮处理：只记录，不修改持久化或状态收敛逻辑。

### BUG-004：TaskPlan 重试接口同步阻塞且运行期间前端保留旧状态

- 发生场景：场景 3、场景 4。
- 现象：`POST /agent/task-plans/{task_plan_id}/retry` 分别阻塞约
  `302412.18 ms` 和 `184194.64 ms` 才返回；请求运行期间验收页仍显示旧的
  `failed` 或 `manual_selected`，没有显示后端已恢复为 `running`。
- 影响：React 控制请求会长时间占用连接，用户无法可靠判断重试是否已受理，
  也不适合企业环境中的任务状态页。
- 本轮处理：只记录，不改为异步受理或轮询/SSE 状态模型。

### BUG-005：修改任务中的特定模型步骤连续触发 60 秒读取超时

- 发生场景：场景 4。
- 现象：首次执行前 8 次模型调用均正常完成；第 9 次调用在两次 SDK 自动重试后
  以 `APITimeoutError` 失败。从检查点恢复后，同一个步骤再次经过两次重试，
  约 184 秒后仍失败。
- 网络复核：对应时段 Clash Verge 对
  `dashscope.aliyuncs.com:443` 的连接均显示 `DIRECT`，没有 DashScope
  `dial error`；当前短请求和 19,200 字符长请求也均能稳定完成。
- 归因：更符合特定 Agent 上下文或结构化输出请求在 60 秒内没有收到模型响应，
  而不是 TUN 路由错误。仅凭客户端日志无法完全区分 DashScope 服务端生成超时
  与极低概率的已建立连接静默丢包，后续应使用同一 checkpoint 做关闭 TUN 的
  对照复测。
- 本轮处理：只记录，不修改模型请求、SDK 重试或超时配置。

## 11. 环境与操作异常

### ENV-001：GitLab 19.1.1 审批服务签名变化

- 发生阶段：场景 0，测试账号审批。
- 现象：按旧调用方式执行
  `Users::ApproveService.new(user, admin).execute` 时返回
  `wrong number of arguments (given 2, expected 1)`。
- 核对结果：当前容器源码定义为
  `Users::ApproveService.new(current_user).execute(user)`。
- 处理：改用当前版本真实签名完成审批；未修改工程代码。
- 影响：第一次审批命令未改变账号和权限，随后账号均成功激活并正确授权。

### ENV-002：PowerShell 首次未加载 `System.Net.Http`

- 发生阶段：场景 1，计算 GitLab Raw 文件 SHA-256。
- 现象：首次使用 `[System.Net.Http.HttpClient]` 时提示找不到类型。
- 处理：显式执行 `Add-Type -AssemblyName System.Net.Http` 后重试成功。
- 影响：只影响验收辅助命令，未影响 GitLab、Webhook、Worker 或发布数据。

### ENV-003：LangSmith Trace 上传超时

- 发生阶段：场景 3 检查点恢复。
- 现象：向 `https://api.smith.langchain.com/runs/multipart` 上传 Trace 时多次
  发生 3 秒读取超时。
- 影响：业务模型调用仍返回 200，TaskPlan 继续运行；影响可观测性数据完整性
  和日志可读性，不是本轮 Agent 失败的直接原因。
- 本轮处理：只记录，未修改 LangSmith 配置。

## 12. Agent 超时与 VPN TUN 专项诊断

### 12.1 当前真实配置与代码边界

- 模型：`qwen3.7-plus`。
- 模型地址：
  `https://dashscope.aliyuncs.com/compatible-mode/v1`。
- 单次模型调用超时：`LLM_TIMEOUT_SECONDS=60`。
- Deep Agent 整体超时：
  `AGENT_DOCUMENT_WORKER_TIMEOUT_SECONDS=300`。
- Coordinator 模型调用上限：`AGENT_MAX_TOOL_CALLS=12`。
- 每个 Researcher/Writer/Reviewer 模型调用上限：
  `AGENT_DOCUMENT_SUBAGENT_MAX_STEPS=12`。
- Deep Agent 整体调用由
  `asyncio.wait_for(graph.ainvoke(...), timeout=300)` 约束；每个
  `ChatOpenAI` 调用另受 60 秒超时约束。

### 12.2 原测试日志统计

| 执行 | 模型调用开始 | 正常结束 | DashScope 200 | SDK 重试 | 结论 |
| --- | ---: | ---: | ---: | ---: | --- |
| 场景 3 首次 | 45 | 44 | 49 | 0 | 多轮正常调用累计耗尽 300 秒 |
| 场景 3恢复 | 45 | 44 | 44 | 1 | 再次未在 300 秒内收敛 |
| 场景 4 首次 | 9 | 8 | 12 | 3 | 一个较早步骤重试后成功，最终步骤连续超时 |
| 场景 4 恢复 | 1 | 0 | 0 | 2 | 同一 checkpoint 模型步骤再次超时 |

说明：场景 4 首次的 3 次重试中，1 次属于前一个最终成功的模型调用，
后 2 次属于最终失败调用。

### 12.3 TUN 与 DashScope 连接核验

1. 系统 DNS 将 `dashscope.aliyuncs.com` 映射为 `198.18.0.130`，
   Windows TCP 连接使用 `Mihomo` 接口和 `198.18.0.1` 源地址。这是 Clash
   fake-IP/TUN 模式的正常入口。
2. Clash 在原始测试时段共记录 17 次 DashScope 新连接，全部为
   `using DIRECT`，DashScope `dial error` 数量为 0。日志实际显示的是
   `match GeoIP(cn) using DIRECT`，说明即使不依赖新增域名规则，国内 GeoIP
   规则也已将该地址直连。
3. WinHTTP 没有配置显式系统代理。
4. 连续 8 次未鉴权 HTTPS 请求都在约 0.23–0.57 秒返回预期的 401。
5. 连续 8 次真实最小 Qwen 请求全部成功，耗时范围为 0.81–1.35 秒。
6. 两次包含约 19,200 字符输入、要求 JSON 输出的真实 Qwen 请求全部成功，
   分别耗时约 12.46 秒和 10.85 秒。
7. DashScope 四个真实国内 A 记录的 HTTPS 请求也均成功，约
   0.23–0.26 秒返回 401。

### 12.4 `mtalk.google.com:5228` 判断

`mtalk.google.com` 的 5228 端口用于 Google Firebase Cloud Messaging
推送长连接。Clash 日志显示它按 Google 规则使用代理节点，与
`dashscope.aliyuncs.com:443` 的模型请求不是同一目标、端口或规则。
其多次出现通常是客户端维持或重连推送通道，不能作为 Agent 模型请求超时的
证据。

### 12.5 最终判断

- **场景 3：高置信度排除 VPN/TUN 为主因。** 根因是 Deep Agent 允许的
  多角色模型调用总量过大，实际产生约 45 次调用，累计耗尽 300 秒总时限。
- **场景 4：VPN/TUN 为低概率因素。** 已确认规则为 DIRECT、无拨号错误，
  且当前短请求和相近体量长请求稳定；更可能是 checkpoint 中的特定模型请求
  上下文或结构化输出生成超过 60 秒。
- 目前没有证据表明 `mtalk.google.com:5228` 导致 DashScope 超时。
- 若需要完全排除 TUN，只需保持同一 TaskPlan checkpoint 和模型配置，
  在关闭 TUN 后重试一次并比较；不要同时调整超时、Prompt 或模型，否则无法
  形成有效 A/B 对照。

### 12.6 场景 3 的 45 次模型调用为何出现

结论：**45 次虽然没有超过当前配置允许的理论上限，但对单个文档创建任务并不
正常。** 这是多层 Agent 循环预算叠加并实际未收敛，不是业务本身需要 45 次
模型推理。

当前一次交付物的链路不是四次固定调用，而是四个各自带循环的 Agent：

```text
Coordinator 决策
  → Researcher：模型 → 检索/文件工具 → 模型 → … → 结构化结果
  → Coordinator 再决策
  → Writer：模型 → 文件工具 → 模型 → … → 结构化结果
  → Coordinator 再决策
  → Reviewer：模型 → 文件工具 → 模型 → … → 结构化结果
  → Coordinator 再决策
  → revision_required 时重新启动 Writer/Reviewer 循环
```

本次日志可按每次模型请求携带的工具数量还原为下列分组。日志 Middleware 没有
直接记录 Agent 名称，因此角色名称是结合工具数量、Prompt 编排顺序和
SubAgent 进度事件得到的高置信度推断：

| 调用序号 | 工具数 | 推断角色/阶段 | 调用次数 |
| --- | ---: | --- | ---: |
| 1–2 | 8 | Coordinator 初始化与派发 Researcher | 2 |
| 3–10 | 9 | Researcher 内部检索、文件写入与结果收敛 | 8 |
| 11–12 | 8 | Coordinator 接收研究结果并派发 Writer | 2 |
| 13–17 | 7 | 第一轮 Writer | 5 |
| 18–19 | 8 | Coordinator 接收草稿并派发 Reviewer | 2 |
| 20–26 | 7 | 第一轮 Reviewer | 7 |
| 27–28 | 8 | Coordinator 处理审查结果并派发返工 | 2 |
| 29–40 | 7 | 返工 Writer，恰好跑满 SubAgent 的 12 次上限 | 12 |
| 41–43 | 8 | Coordinator 继续处理返工结果 | 3 |
| 44–45 | 7 | 后续 Writer/Reviewer 阶段，第 45 次被 300 秒总超时中断 | 2 |

其中最明确的异常信号是第 29–40 次：一个没有真实业务工具、只需读写虚拟草稿
的 Writer/Reviewer 调用连续执行 12 次，恰好耗尽
`AGENT_DOCUMENT_SUBAGENT_MAX_STEPS=12`，说明它没有按 Prompt 中的“立即返回”
自行收敛，而是依赖硬上限终止。

导致放大的代码原因：

1. Coordinator 和每次 SubAgent 调用各自拥有独立的模型调用预算，不存在覆盖
   Coordinator、所有 SubAgent 和所有返工轮次的全局调用预算。
2. Deep Agents 的 `task` SubAgent 是临时、无状态调用；每次返工都会用新的
   `HumanMessage` 启动一次新的 Agent 循环，也会重新获得 12 次预算。
3. `AGENT_DOCUMENT_MAX_REVISION_ROUNDS=2` 当前只被写入 Coordinator 的输入和
   Prompt，工程代码没有确定性的返工计数器强制执行该上限。
4. Writer/Reviewer 即使没有业务工具，仍拥有 Deep Agents 内置虚拟文件工具，
   因而一次角色执行并不等于一次模型调用。
5. 现有真实模型测试只断言调用数不超过
   `12 + 3 × 12 = 48`，因此 45 次会被视为“未超预算”，测试没有校验实际
   收敛次数或总耗时。
6. 外层 PostgreSQL checkpoint 只能在 SubAgent `task` 返回后收到结果；
   SubAgent 内部循环没有使用该外层 checkpointer。若总超时发生在一次
   SubAgent 调用内部，恢复时至少会重新执行该完整 SubAgent 调用，可能再次
   触发返工链路。

因此，本问题应记录为**工作流收敛与预算设计缺陷**：“48 次是保险丝上限”
被误当成了正常可接受路径。仅把 300 秒调大只能延后失败，不能消除 45 次调用
或检查点恢复后的重复消耗。本轮继续只记录诊断，不修改业务代码。

## 13. Agent 调用未收敛修复记录

### 13.1 Checkpoint 复核得到的直接证据

修复前读取 TaskPlan
`task_plan_20260726124322_099b2df31bde` 的加密 PostgreSQL checkpoint，
恢复出 32 条 Coordinator 外层消息。与本问题直接相关的派发顺序为：

```text
Researcher
→ Writer
→ Reviewer
→ Writer（返工，模型调用预算耗尽）
→ Writer（完全相同任务重试，再次耗尽）
→ Writer（完全相同任务再次重试）
→ Reviewer
→ Writer（第二轮返工，随后整体超时）
```

前三次返工 Writer 的 task 描述 SHA 完全相同：
`14dda150851d`。前两次 ToolMessage 已明确返回
`SUBAGENT_MODEL_CALL_LIMIT_EXCEEDED`，但 Coordinator 仍继续重试。这证明
“不得重试”和“最多返工两轮”此前都只是 Prompt 约定，没有服务端强制执行。

同时，返工 task 没有提供上一版草稿的确定路径；Writer Prompt 只要求在
`/workspace/drafts` 中处理文件，使临时 SubAgent 需要自行寻找草稿，增加了
文件工具循环不收敛的概率。

### 13.2 已实施修复

1. 草稿路径统一为
   `/workspace/drafts/{deliverable_id}.md`。Writer 返工和 Reviewer 审查必须
   使用该路径，并禁止使用 `ls`、`glob`、`grep` 扫描工作区。
2. Coordinator 的 `write_todos` 只允许初始调用一次，不再在每个角色完成后
   反复更新 Todo。
3. Middleware 从可恢复的 Coordinator 消息中还原历史 task 派发：
   - 同一交付物的 Researcher 最多一次；
   - Writer/Reviewer 最多 `1 + max_revision_rounds` 次；
   - 已返回 `SUBAGENT_MODEL_CALL_LIMIT_EXCEEDED` 的完全相同任务禁止重试；
   - 这些限制读取 checkpoint 历史，因此 `/retry` 后不会重新获得派发次数。
4. 单个 SubAgent 默认模型调用上限从 12 收紧为 8。
5. 增加 `AGENT_DOCUMENT_MAX_TOTAL_MODEL_CALLS=32`，一次执行中的 Coordinator、
   Researcher、Writer、Reviewer 共享该总预算，不再各自叠加出 48 次理论上限。
6. 模型预算失败 ToolMessage 现在明确设置 `name=task`、`status=error` 和稳定
   `error_code`，避免 Coordinator 将失败结果误判为成功工具返回。

### 13.3 回归结果

| 检查 | 结果 |
| --- | --- |
| Python `py_compile` | 通过 |
| `test_deep_document_agent_workflow.py` 离线回归 | 通过 |
| PostgreSQL checkpoint 恢复回归 | 通过 |
| Schema 字段描述回归 | 通过 |
| Prompt Guard 文档并行回归 | 通过 |
| 隔离式真实 Qwen Deep Document Agent 回归 | 通过 |
| 修复后真实模型调用数 | **17 次** |

真实模型回归在同一个 Researcher → Writer → Reviewer 主链路中成功生成
`approved_changes`，调用数从问题现场的 45 次下降到 17 次，且没有触发
300 秒整体超时。

旧 TaskPlan 的 checkpoint 已包含多次违规返工历史，修复后会被确定性限制拒绝，
不适合作为“修复后成功生成文档”的验收样本。场景 3、4 的完整 GitLab MR、
Maintainer 合并和数据库同步仍应使用新 TaskPlan 重新执行。

补充：`test_llm_document_management_task.py` 当前在 direct Tool Loop 的既有
ToolMessage 状态断言处失败；该路径不经过本次 Deep Document Agent 修改，
作为独立问题保留，不在本次收敛修复中扩大范围。

## 14. 场景 3、4 修复后重新验收

### 14.1 重新验收环境

- 验收时间：2026-07-26 22:02—22:15（Asia/Shanghai）。
- FastAPI：使用当前工作区代码重新启动，并从服务器外网络环境直连
  DashScope；GitLab、PostgreSQL、Elasticsearch、Milvus 和独立 Worker
  均保持运行。
- 浏览器：使用 Codex 内置浏览器操作人工验收页和 GitLab Web 页面。
- GitLab 审核账号：`tech-maintainer-e2e`。
- 知识库初始正式版本：`3`。
- Development Source 初始 SHA：
  `74e9752d76095c7aaabb0355222e68eb7eff2299`。

以下两个准备阶段产生的 TaskPlan 不计入正式结论：

1. `task_plan_20260726135452_2973fd34dd33`：旧 FastAPI 进程仍加载修复前的
   单角色 12 次预算，发现后终止。
2. `task_plan_20260726140012_bd104ab64e0f`：在受限沙箱中启动的 FastAPI
   无法建立 DashScope 网络连接，出现 Windows `10013`，随后改为服务器外
   网络环境重新启动。

### 14.2 场景 3：Agent 创建 Markdown 文档

正式 TaskPlan：
`task_plan_20260726140204_3fc098496a49`。

测试 Query 要求 Agent 创建
`development/gitlab-agent-mr-governance.md`，并生成可用于技术部真实工作的
GitLab MR 治理说明，不使用单句或占位内容。

执行过程和结果：

1. 22:02:04 创建全新 TaskPlan，从零开始执行 Deep Document Agent。
2. DashScope 请求均返回 HTTP 200，未观察到 VPN/TUN 或单次模型读取超时。
3. 22:05:43 工作流由共享预算保险丝确定性终止，总耗时约 219.5 秒。
4. 最终错误为
   `SharedModelCallBudgetExceededError: 文档 Agent 总模型调用预算已耗尽（32/32）`。
5. TaskPlan 状态为 `failed`，只保留
   `Researcher started` 之前的两个进度事件；交付物状态仍为 `running`，
   checkpoint 标记为 `resumable`。
6. 人工确认页只显示通用 `INTERNAL_SERVER_ERROR`，并显示“无 TaskPlan”。
7. 数据库确认该 TaskPlan 没有 `gitlab_change_requests`；目标文档没有进入
   `gitlab_documents`，GitLab 中没有创建 MR，也没有对正式知识库产生副作用。

场景 3 结论：**失败**。修复已经把原来的约 45 次重复调用和 300 秒超时
替换为 32 次共享预算的确定性终止，但真实创建任务仍未收敛到预览和人工确认，
因此不能判定“调用未收敛问题已经完全解决”。

### 14.3 场景 4：Agent 修改 Markdown 文档

正式 TaskPlan：
`task_plan_20260726140639_34f53633ecc8`。

测试 Query 要求 Agent 修改
`development/rag-deployment-checklist.md`，新增完整的
“GitLab 文档源与发布版本验收”章节，覆盖分支、MR、Maintainer、Webhook、
Worker、正式版本、ES/Milvus、ACL 和失败处理。

执行过程和结果：

1. Agent 从 Development Project 的固定 SHA
   `74e9752d76095c7aaabb0355222e68eb7eff2299` 读取指定文件，未改读其他文档。
2. 约 136.7 秒后生成预览，新增 233 行；预览统计为 29 个父块、
   32 个子块，目标 `doc_id` 为
   `192e4c24ec0092cc53dd4e443f133df3f290828409c8f9bb5142158f55a1c32b`。
3. 人工确认前，GitLab `main`、ES 和 Milvus 均未发生变化。
4. 在人工验收页确认后，Agent 使用专用机器人账号创建：
   - 分支：
     `agent/task_plan_20260726140639_34f53633ecc8-dfdb81ab`
   - Commit：
     `b9ec0353a736b7acd937dac0a70a7389856e4b43`
   - Merge Request：
     `http://localhost:8929/rag-kb-dev/rag-development-docs/-/merge_requests/3`
5. 使用 `tech-maintainer-e2e` 在 GitLab Web 页面检查 1 个文件、233 行新增，
   点击 Approve 后合并到 `main`；合并 Commit 为
   `1ca37f12a66b447dab52667f783702c9b411a3ae`。
6. GitLab 向
   `/integrations/gitlab/webhooks/gitlab-development` 推送事件，后端返回
   `202 Accepted`；分支事件未发布知识，`main` 事件登记增量同步任务。
7. Worker 任务
   `gitlab_job_bac56ce32ee648a0baf7112676643377`
   一次执行成功，状态为 `succeeded/published`。
8. PostgreSQL 正式版本从 `3` 原子切换到 `4`，
   `last_synced_sha == desired_sha == 1ca37f12...`；Manifest 的
   `content_hash` 与 Agent 预览的
   `c88a0bf008e2bc23c6c79575f727252141b0457565a98171240b4d68f3b7f171`
   一致，策略为 `markdown_parent_child_v1`。
9. 发布事件 `knowledge_change_events.id=19` 正确记录该文档为
   `modified`，ACL 为 `development` 部门可见。
10. Elasticsearch 当前版本包含 29 个父块和 32 个子块，均为
    `valid_from_version=4, valid_to_version=0`；旧版本的 16 个父块和
    16 个子块均更新为 `valid_to_version=4`。
11. Milvus 当前版本包含 32 个 `markdown_child`，全部具有
    `logical_parent_id` 和 `physical_parent_id`；旧 16 个子块均更新为
    `valid_to_version=4`。
12. GitLab `main`、ES 和 Milvus 中都能检出
    “GitLab 文档源与发布版本验收”和 `Webhook` 内容。

场景 4 结论：**GitLab MR、人工审核、合并、Webhook、Worker 和版本化同步
链路通过**。但本任务走的是现有 direct Document Tool Loop，不是场景 3 的
Deep Document Agent 监督式 Researcher/Writer/Reviewer 链路，因此它不能
单独证明 Deep Document Agent 已收敛。

### 14.4 重新验收总评

| 检查项 | 结果 |
| --- | --- |
| 原 45 次重复返工被服务端限制 | 通过 |
| 不再依赖 300 秒总超时终止 | 通过 |
| 真实 Deep Document Agent 创建任务成功收敛 | **失败（32/32）** |
| direct Document Tool Loop 修改任务 | 通过 |
| Agent 只创建分支、Commit 和 MR | 通过 |
| Maintainer Web 审核与合并 | 通过 |
| 合并前不写 ES/Milvus | 通过 |
| 合并后 Webhook + Worker 增量发布 | 通过 |
| PostgreSQL、ES、Milvus 版本和内容一致 | 通过 |

最终结论：**修复有效限制了失控调用，但没有完全解决 Deep Document Agent
的业务收敛问题。** 17 次真实模型隔离回归只能证明固定测试输入可以成功；
更接近真实业务的场景 3 仍耗尽 32 次共享预算并失败。

## 15. 本轮新增逻辑错误与系统 Bug

### LOGIC-002：场景 4 的 Agent 生成内容包含与当前实现不一致的验收项

- 发生场景：场景 4。
- 证据：合并后的文档包含 `Merge events`、`Redis/PostgreSQL` 队列和
  `system_config` 等描述。
- 当前实现：GitLab 合并后由 `main` Push Webhook 触发；当前队列使用
  PostgreSQL；正式版本指针保存于 `knowledge_publication_state`。
- 影响：Agent 能完成文档变更链路，但生成内容没有完全以当前工程代码为
  事实来源，人工审核应能识别并阻止此类不准确内容。
- 本轮处理：按既定测试步骤完成合并并记录问题，暂不修改文档或 Agent。

### BUG-006：共享总预算只限制失控，没有保证真实创建任务收敛

- 发生场景：场景 3。
- 证据：全新 TaskPlan 在 32 次模型调用后触发
  `SharedModelCallBudgetExceededError`，没有生成预览。
- 改善：相比修复前的约 45 次调用和 300 秒超时，失败边界更早且可预测。
- 未解决部分：真实创建任务仍不能到达 `waiting_confirmation`，说明
  Coordinator/角色任务本身仍存在过多调用或返工。
- 本轮处理：只记录，不继续提高预算或总超时。

### BUG-007：模型预算失败没有以结构化 TaskPlan 错误呈现给前端

- 发生场景：场景 3。
- 证据：磁盘 TaskPlan 状态为 `failed`，但人工验收页显示通用
  `INTERNAL_SERVER_ERROR` 和“无 TaskPlan”。
- 同时存在的状态问题：`document_progress.stage` 仍为
  `deep_agent_running`，交付物仍为 `running`，与顶层 `failed` 冲突。
- 影响：React 无法展示可理解的预算耗尽原因，也无法可靠提供重试或检查点
  恢复操作。
- 本轮处理：只记录，不修改 SSE、异常映射或 TaskPlan 状态收敛。

### BUG-008：MR 合并后 `gitlab_change_requests.status` 仍为 `opened`

- 发生场景：场景 4。
- 证据：GitLab MR `!3` 已显示 `Merged`，知识版本也已发布为 `4`，但
  `gitlab_change_requests.id=gitlab_cr_4c53035db9c74a2fad2a93f9c8691fc0`
  的状态仍为 `opened`。
- 影响：管理接口或 React 前端读取数据库时会把已合并 MR 错误显示为待处理。
- 本轮处理：只记录，不增加 MR 状态同步逻辑。

## 16. 场景 3 的 32 次模型调用还原

### 16.1 证据来源

本节读取全新 TaskPlan
`task_plan_20260726140204_3fc098496a49` 的加密 PostgreSQL checkpoint。
最外层 Coordinator checkpoint 保存 9 次模型调用；同一 thread 下还存在
5 个 `tools:*` 子命名空间，分别对应一次 Researcher、两次 Writer 和两次
Reviewer。各 checkpoint 的 `thread_model_call_count` 合计：

```text
9 + 8 + 2 + 3 + 8 + 2 = 32
```

这说明 32 次不是同一个模型连续生成 32 次正文，而是模型每次决定调用工具、
读取工具结果、派发 SubAgent、修订或返回结构化结果都占用一次调用。

### 16.2 完整调用序列

| 全局序号 | 角色 | 本段调用 | 实际动作与结果 |
| --- | --- | ---: | --- |
| 1 | Coordinator | 1 | 首次调用 `write_todos`，创建 Research/Write/Review/Finalize 计划 |
| 2 | Coordinator | 1 | 派发 `document-researcher` |
| 3—10 | Researcher | 8 | 两次检索成功；第三次重复检索被限流；读取一份全文成功；两次继续读取第二份文档均被限流；两次调用 `write_todos`；未写入 `source.md/summary.md`，也未返回 `DocumentResearchResult` |
| 11 | Coordinator | 1 | Researcher 已失败，仍尝试第二次 `write_todos` 并错误地把 Research 标为 completed；该调用被工具上限拒绝 |
| 12 | Coordinator | 1 | 没有研究证据仍派发首轮 Writer，并明确让 Writer 改用“通用知识” |
| 13—14 | 首轮 Writer | 2 | 一次 `write_file` 写完整草稿，一次返回 `DocumentDraftResult` |
| 15 | Coordinator | 1 | 派发首轮 Reviewer |
| 16—18 | 首轮 Reviewer | 3 | 分两页读取草稿，返回 `revision_required`；指出 `If-Match` 错误，并要求补充 Secrets Detection、Agent 监控和分支清理说明 |
| 19 | Coordinator | 1 | 派发返工 Writer |
| 20—27 | 返工 Writer | 8 | 分两页读取草稿，连续执行 5 次 `edit_file`，最后返回 `DocumentDraftResult`；返回值错误地使用 `operation=update` 且 `content=null` |
| 28—29 | Coordinator | 2 | 因返工 Writer 没有返回正文，Coordinator 自己分两页读取修订后的草稿 |
| 30 | Coordinator | 1 | 派发第二轮 Reviewer |
| 31—32 | 第二轮 Reviewer | 2 | 第一次同时读取草稿和研究摘要，发现 `summary.md` 不存在；第二次读取草稿后半段 |
| 第 33 次尝试 | 第二轮 Reviewer | 未执行 | 准备生成最终审查结论前，共享预算已是 `32/32`，由 `SharedModelCallBudgetExceededError` 阻止 |

### 16.3 哪些调用是不必要消耗

至少有 12 次可以明确认定为非业务复杂度所必需：

1. Researcher 在工具已经返回上限错误后，仍重复检索或读取 3 次。
2. Researcher 调用了 2 次与职责无关、Prompt 明确禁止的 `write_todos`。
3. Coordinator 在首次 Todo 后又调用 1 次 `write_todos`。
4. 返工 Writer 将一次可整体覆盖的修改拆成 5 次 `edit_file`，至少多消耗
   4 次模型调用。
5. 返工 Writer 返回 `content=null` 后，Coordinator 又用 2 次调用读取草稿。

更关键的是，Researcher 在第 10 次全局调用结束时已经失败。按 Coordinator
Prompt，唯一交付物应进入 `failed_deliverables` 并立即结束；实际工作流却继续
执行 Writer、Reviewer 和返工，因此第 11—32 次整体上都建立在“缺少研究证据”
的错误前提上。

### 16.4 是否因为 Query 太复杂

结论：**Query 有一定内容复杂度，但不是 32 次耗尽的主因。**

增加合理调用量的因素：

- 要求综合三类内部资料；
- 要求一份完整规范包含十余项主题；
- Reviewer 确实发现事实错误，因此一次返工是合理的；
- 长草稿需要分页读取。

但该 Query 只有一个 `create` 交付物、没有交付物依赖、禁用 Web Search，
目标路径和章节要求都很明确，属于 Deep Document Agent 设计上应当支持的
常规单文档复杂任务，不应耗尽 32 次调用。失败的直接原因依次是：

1. Researcher 不遵守工具错误和“不要创建 Todo”的约束，8 次调用后仍没有
   形成研究结果。
2. `knowledge_document_read=1` 与本次“三类资料综合”的需求存在容量冲突；
   第二份全文读取被硬限制。
3. Coordinator 没有对 Researcher 失败执行确定性的 fail-fast，反而让 Writer
   在无证据状态下继续生成。
4. 无证据草稿产生事实问题，触发 Reviewer 返工。
5. 返工 Writer 使用 5 次细粒度编辑并返回缺少正文的错误结构，使
   Coordinator 额外读取文件。
6. 第二轮 Reviewer 已完成草稿读取，但在输出最终 verdict 前耗尽共享预算。

因此，32 次共享预算现在只是有效保险丝；真正仍需修复的是角色工具白名单、
研究阶段容量、失败后的确定性状态转换，以及 Writer 返工输出契约。

## 17. Researcher 失败传播修复记录

修复日期：2026-07-26。

本轮针对第 16 章定位出的主因完成以下修改：

1. Coordinator 中间件从真实 `task` ToolMessage 恢复每个交付物的
   Researcher 状态，不再仅依赖 Prompt 要求模型自行判断。
2. Researcher 返回 `failed` 后，Writer 和 Reviewer 的派发会被服务端以
   `UPSTREAM_RESEARCH_FAILED` 拒绝，禁止改用通用知识继续生成。
3. 单交付物 Researcher 失败时直接生成 `failed_deliverables` 并跳到图结束，
   不再产生后续 Coordinator、Writer 或 Reviewer 模型调用。
4. 多交付物场景只清除失败交付物的研究、草稿、审查和批准结果，其他独立
   交付物仍可继续。
5. `partial/completed` 研究结果必须同时存在结构化 `evidence` 和固定路径
   `summary.md`，否则 Writer/Reviewer 不准入。
6. `knowledge_document_read` 单次 Researcher 上限从 1 调整为 3；
   `knowledge_retrieval` 保持 2，共享模型预算保持 32。
7. Researcher 的内置 `write_todos` 已从模型可见工具中移除，不再只是依赖
   Prompt 禁止。

本地回归结果：

- `test_deep_document_agent_workflow.py`：通过；
- `test_deep_document_checkpoint_runtime.py`：通过；
- `py_compile`：通过；
- `git diff --check`：通过，仅有工作区既有 CRLF 提示。

BUG-006、BUG-007 当前状态：**代码已修复，等待使用全新 TaskPlan 重新执行
场景 3 的真实模型、MR、合并和 GitLab 同步验收后关闭。**

## 18. 场景 3 第二次重新验收

### 18.1 测试环境与新 TaskPlan

- 验收时间：2026-07-26 22:50—22:51（Asia/Shanghai）。
- 操作入口：Codex 内置浏览器中的 RAG Agent 手工验收页面。
- RAG 用户：`tool_manager`。
- Session ID：`gitlab-s3-retest-20260726-2250`。
- 新 TaskPlan：
  `task_plan_20260726145057_54eea293abb7`。
- TaskPlan 创建时间：
  `2026-07-26T14:50:57.989611Z`。
- 检查点证据：
  `resume_count=0`、`resumed_from_checkpoint=false`。

本次重新提交了完整的场景 3 Query，仍要求创建
`development/gitlab-agent-mr-governance.md`，综合 GitLab 文档发布、
Agent 文档操作和权限治理资料，并输出可供真实研发团队使用的规范及不少于
10 项上线验收清单。没有加载、重试或恢复此前的
`task_plan_20260726140204_3fc098496a49`。

### 18.2 测试步骤

1. 使用当前工作区代码重新启动 FastAPI，确认 `/health` 返回正常。
2. 在内置浏览器重新登录 RAG 手工验收页面并确认当前用户身份。
3. 填写新的 Session ID 和完整创建文档 Query。
4. 点击 `POST /rag/chat/stream/events` 对应的结构化流式请求按钮。
5. 从 FastAPI 日志取得服务端新建的 TaskPlan ID，并检查 TaskPlan 持久化状态。
6. 在 GitLab Web 页面分别检查 Development Project 的开放 MR、分支和
   `main` 中的目标文件。
7. 查询 PostgreSQL 的 change request、目标文档、正式版本、Source SHA 和
   最近同步任务，确认失败没有产生正式知识副作用。

### 18.3 实际执行轨迹

本次请求观察到 3 次 DashScope HTTP 200：

1. 前两次用于 RAG 请求边界内的模型判断和 Query 改写。
2. 第三次由 Deep Document Agent Coordinator 生成任务派发。
3. Coordinator 已派发 `document-researcher`，TaskPlan 因而记录
   `agent_task_document_subagent_started`。
4. Researcher 自身第一次模型调用前，Coordinator 的
   `_DocumentCoordinatorProgressMiddleware.before_model` 节点立即抛出
   `TypeError`。
5. Researcher 实际模型调用为 0 次；Writer 和 Reviewer 均为 0 次。

最终错误：

```text
TypeError: _DocumentCoordinatorProgressMiddleware.before_model()
missing 1 required positional argument: '_runtime'
```

TaskPlan 顶层状态为 `failed`，没有生成文档预览，也没有进入
`waiting_confirmation`。前端收到通用
`INTERNAL_SERVER_ERROR`，页面仍显示“无 TaskPlan”。

### 18.4 GitLab 与后端副作用检查

| 检查项 | 实际结果 |
| --- | --- |
| 新 TaskPlan | 已创建，未复用旧计划 |
| checkpoint 恢复 | 未发生 |
| 文档预览 | 未生成 |
| 人工确认 | 未进入 |
| GitLab 开放 MR | `0` |
| GitLab 分支 | 只有 `main` |
| 目标文件 | GitLab Web 明确提示在 `main` 中不存在 |
| `gitlab_change_requests` | 当前 TaskPlan 对应记录为 `0` |
| `gitlab_documents` | 目标路径对应记录为 `0` |
| 正式知识版本 | 仍为 `4` |
| Development Source | `last_synced_sha == desired_sha == 1ca37f12...` |
| 新发布任务 | 未产生 |

因此，本次异常没有创建分支、Commit 或 MR，也没有修改 PostgreSQL 文档
Manifest、ES、Milvus 或正式版本。

### 18.5 场景结论

场景 3 第二次重新验收：**失败，且失败发生在 Researcher 第一次模型调用前。**

本次不能验证 Researcher 读取上限、工具白名单或失败后的确定性
fail-fast 是否在真实图中生效，也不能继续 MR、Maintainer 合并和同步验收。
但已确认新 TaskPlan 和新 checkpoint 均正确创建，未复用任何旧 TaskPlan，
并且 MR 前无副作用边界仍然成立。

BUG-006、BUG-007 不能关闭，需先修复下述 BUG-009，再使用另一个全新
TaskPlan 重新执行完整场景 3。

## 19. 本轮新增系统 Bug

### BUG-009：Coordinator `before_model` 的运行时参数无法被 LangGraph 注入

- 发生场景：场景 3 第二次重新验收。
- 代码位置：
  `src/fast_app/services/agent_tasks/deep_document_agent.py` 的
  `_DocumentCoordinatorProgressMiddleware.before_model`。
- 当前签名：
  `def before_model(self, state, _runtime)`。
- 根因：LangGraph `RunnableCallable` 只按约定参数名 `runtime` 注入运行时；
  `_runtime` 不在其注入参数表中。节点执行时只传入了 `state`，导致缺少第二个
  必填参数。
- 影响：所有进入 Deep Document Agent 的任务都会在第一次 SubAgent 模型调用
  前失败，Researcher、Writer、Reviewer 和 fail-fast 逻辑都无法真实运行。
- 测试为何遗漏：现有回归直接调用
  `middleware.before_model(failed_state, None)`，手工提供了第二个参数，
  没有通过 LangGraph 编译后的真实 `RunnableCallable` 节点执行。
- 前端表现：结构化 SSE 只返回通用 `INTERNAL_SERVER_ERROR`，没有返回
  TaskPlan ID 和具体错误。
- 本轮处理：遵守“测试发现 Bug 后先记录、检查后再修复”的约定，不修改代码。

## 20. BUG-009 修复记录

修复时间：2026-07-26。

本轮只修改 BUG-009 的真实根因：

1. 将 `_DocumentCoordinatorProgressMiddleware.before_model` 的第二个参数从
   `_runtime` 改为 LangGraph 约定的 `runtime`。
2. 将原先直接调用
   `middleware.before_model(failed_state, None)` 的测试改为：
   - 创建真实 `StateGraph`；
   - 把 `middleware.before_model` 注册为节点；
   - 编译 Graph；
   - 通过 `ainvoke()` 执行节点并验证结构化终态。

这项测试会经过 LangGraph 内部真实使用的 `RunnableCallable` 参数注入路径，
能够防止再次把 `runtime` 错写成其他参数名。

回归结果：

- `test_deep_document_agent_workflow.py`：通过；
- `test_deep_document_checkpoint_runtime.py`：通过；
- `py_compile`：通过；
- `git diff --check`：通过，仅有工作区既有 CRLF 提示。

BUG-009 当前状态：**已修复并通过真实编译节点回归。**

## 21. 场景 3 第三次重新验收

### 21.1 新 TaskPlan

- 验收时间：2026-07-26 22:59—23:03（Asia/Shanghai）。
- 操作入口：Codex 内置浏览器中的 RAG Agent 手工验收页面。
- Session ID：`gitlab-s3-retest-20260726-2259`。
- TaskPlan：
  `task_plan_20260726145925_9c2dd4cf7247`。
- 创建时间：
  `2026-07-26T14:59:25.951000Z`。
- checkpoint：
  `resume_count=0`、`resumed_from_checkpoint=false`、
  `record_version=6`。

本次再次完整提交场景 3 Query，没有加载、重试或恢复任何旧 TaskPlan。

### 21.2 BUG-009 验证结果

修复后的真实工作流已经越过此前的 `before_model` 异常：

1. Coordinator 第一次模型调用创建初始 Todo。
2. Coordinator 第二次模型调用派发
   `document-researcher`。
3. Researcher 第一次模型调用发起一次
   `knowledge_retrieval`。
4. Researcher 第二次模型调用读取两份 GitLab 正式文档：
   - `development/rag-backend-deployment.md`；
   - `development/rag-deployment-checklist.md`。
5. Researcher 没有调用 `write_todos`。

因此已确认：

- LangGraph 能够正确向 `before_model` 注入 `runtime`；
- Researcher 工具白名单真实生效；
- `knowledge_document_read` 从 1 调整到 3 后，至少允许本次连续读取两份全文；
- BUG-009 在真实请求中没有再现。

### 21.3 新的失败位置

读取两份全文后，Researcher 的第三次逻辑模型调用等待响应：

1. 第一次请求约 60 秒后读取超时；
2. SDK 第一次重试约 60 秒后再次读取超时；
3. SDK 第二次重试约 60 秒后仍读取超时；
4. TaskPlan 最终错误为：
   `APITimeoutError: Request timed out.`。

Deep Document Agent 本次共进入 5 次逻辑模型调用：

```text
Coordinator 2 次
Researcher 3 次（第 3 次包含 3 个 HTTP 尝试且最终超时）
Writer 0 次
Reviewer 0 次
```

整个 `/rag/chat/stream/events` 请求耗时约 `241.1` 秒。所有已完成的
DashScope 请求均返回 HTTP 200；失败集中在 Researcher 读取两份完整文档后的
单次模型响应，不是 32 次共享预算耗尽，也不是 BUG-009。

TaskPlan 最终状态为 `failed`，前端能够显示新 TaskPlan ID，并在 Markdown
审查视图中展示 `APITimeoutError`，没有只显示通用 500。

### 21.4 无副作用检查

| 检查项 | 实际结果 |
| --- | --- |
| GitLab 开放 MR | `0` |
| `gitlab_change_requests` | 当前 TaskPlan 对应记录为 `0` |
| 目标文档 Manifest | `0` |
| 正式知识版本 | 仍为 `4` |
| Development `last_synced_sha` | `1ca37f12...` |
| Development `desired_sha` | `1ca37f12...` |
| 新文档发布任务 | 未产生 |

测试期间周期性 reconcile 创建了一个 `no_changes` 任务
`gitlab_job_d377ca20b8c249c7ae6de2edff023adf`，目标仍是原 SHA，
`change_counts_json={}`；它不是本次 Agent TaskPlan 产生的发布任务。

因此没有创建分支、Commit 或 MR，也没有修改 PostgreSQL 文档 Manifest、
ES、Milvus 或正式版本。

### 21.5 本轮结论

- BUG-009：**关闭**。
- Researcher `write_todos` 禁止规则：**真实请求验证通过**。
- Researcher 两份全文读取：**真实请求验证通过**。
- Coordinator 对 Researcher 模型预算失败的 fail-fast：**本次未触发，
  仍待验证**。
- 场景 3：**仍失败，阻塞于 BUG-005 的 60 秒模型读取超时复现**。
- MR、Maintainer 合并、Webhook、Worker 和数据库同步：**本次无法继续**。

下一步应单独检查 Researcher 第三次请求的输入规模、模型输出要求和
OpenAI-compatible 客户端 read timeout 配置，再决定是缩小 Researcher
上下文、减少一次返回内容，还是只对该角色调整合理的读取超时。不能通过恢复
本次失败 checkpoint 绕过问题；修复后仍需创建另一个全新 TaskPlan 验收。

## 22. Researcher 第三次请求超时原因检查

### 22.1 检查对象

- 失败 TaskPlan：
  `task_plan_20260726145925_9c2dd4cf7247`。
- 模型：`qwen3.7-plus`。
- 单次 LLM 请求超时：`60` 秒。
- OpenAI-compatible SDK 自动重试：`2` 次，即一次逻辑模型调用最多产生
  3 次 HTTP 尝试。
- Deep Document Agent 外层 Worker 超时：`300` 秒。

### 22.2 Checkpoint 输入规模

解密读取失败 TaskPlan 的最新 checkpoint，只统计消息数量和字符数，不输出
正文：

| Namespace | 消息数 | 消息字符数 | 已完成逻辑模型调用 |
| --- | ---: | ---: | ---: |
| Coordinator | 4 | 1,769 | 2 |
| Researcher | 6 | 34,774 | 2 |

Researcher 第三次模型请求前已经携带：

1. 用户任务上下文；
2. 一次知识库检索结果；
3. 两份 GitLab 正式文档全文；
4. 前两次 Researcher 模型回复和 ToolCall/ToolMessage。

因此第三次请求在加入系统 Prompt、工具 Schema 前，消息正文已约
`34.8k` 字符。服务端没有返回上下文超限、请求格式、结构化输出或工具参数
错误，而是在读取模型响应时连续达到 60 秒超时。

### 22.3 原因判断

本次证据不支持 BUG-009 或新的 Python 控制流错误：

- Coordinator 正常派发一次 Researcher；
- Researcher 的检索和两次文档读取均成功；
- `write_todos` 不在 Researcher 可见工具中；
- Writer、Reviewer 没有在 Researcher 失败后被错误派发；
- 失败类型稳定为 `APITimeoutError`，不是模型调用预算、工具上限或
  LangGraph Hook 参数错误。

结论：这是 **Researcher 长上下文综合请求与当前 60 秒读取超时配置不匹配**
的问题。它属于系统配置/性能设计缺陷，仍归入 BUG-005；不是本轮已修复的
Coordinator/Researcher 业务控制流再次出错。由于同一期间检索、GitLab Raw
读取和其他 DashScope 短请求均成功，VPN/TUN 不是主要原因。

## 23. 场景 3 第四次重新验收（唯一复测）

### 23.1 新 TaskPlan

- 验收时间：2026-07-26 23:09—23:12（Asia/Shanghai）。
- 操作入口：Codex 内置浏览器中的 RAG Agent 手工验收页面。
- Session ID：`gitlab-s3-retry-once-20260726-2308`。
- 新 TaskPlan：
  `task_plan_20260726150910_d81d769b15b1`。
- checkpoint：
  `resume_count=0`、`resumed_from_checkpoint=false`、
  `record_version=6`。

本次重新提交完整场景 3 Query，没有加载、恢复或重试旧 TaskPlan；按本轮要求
只执行这一次重新测试。

### 23.2 执行轨迹

1. Coordinator 两次模型调用均成功，创建 Todo 并派发一次 Researcher。
2. Researcher 第一次模型调用成功完成知识库检索。
3. Researcher 第二次模型调用成功读取：
   - `development/rag-backend-deployment.md`；
   - `development/rag-deployment-checklist.md`。
4. Researcher 第三次逻辑模型调用携带 6 条消息，消息正文合计
   `36,248` 字符。
5. 第三次逻辑调用的第一次 HTTP 尝试约 60 秒后读取超时；
   SDK 第一次重试再次约 60 秒超时；
   SDK 第二次重试仍在约 60 秒后超时。
6. TaskPlan 最终状态为 `failed`，错误为
   `APITimeoutError: Request timed out.`。
7. Writer 和 Reviewer 均未启动，证明 Researcher 失败后没有继续低质量写作。

整个 `/rag/chat/stream/events` 请求耗时约 `243.5` 秒。前端能够显示失败的
新 TaskPlan ID，并在 Markdown 审查视图中显示具体超时错误。

### 23.3 无副作用检查

| 检查项 | 实际结果 |
| --- | --- |
| `gitlab_change_requests` | 当前 TaskPlan 对应记录为 `0` |
| 目标文档 Manifest | `0` |
| 正式知识版本 | 仍为 `4` |
| GitLab 分支、Commit、MR | 未进入创建代码路径 |
| ES、Milvus | 未进入写入或发布代码路径 |

### 23.4 复测结论

- BUG-009：**未复现，保持关闭**。
- Researcher 读取两份全文：**再次验证通过**。
- Researcher 失败后的确定性 fail-fast：**真实请求验证通过**，Writer 和
  Reviewer 均未启动。
- BUG-005：**稳定复现**。同一逻辑位置、相近输入规模和相同 60 秒阈值下，
  两个全新 TaskPlan 都失败，因此不能再判断为一次偶发网络抖动。
- 场景 3：**仍失败**，尚未进入预览、确认、MR、Maintainer 合并和同步阶段。

本轮不继续创建第三个 TaskPlan，也不通过旧 checkpoint 重试。下一步修复应
只针对 Researcher 长上下文模型调用的超时边界和输入规模，不应再次修改
BUG-009 的 Hook 签名或放宽 Writer/Reviewer 的准入规则。

## 24. BUG-005 与 Deep Document Agent 未收敛修复过程

修复及真实复测时间：2026-07-26 23:28—2026-07-27 01:55
（Asia/Shanghai）。

### 24.1 根因与修复边界

本轮没有继续单纯放大所有模型预算，而是按真实失败位置逐项收敛：

1. Researcher、Writer、Reviewer 和 Coordinator 的长内容请求改为流式接收，
   并关闭 SDK 对同一长请求的自动重放。
2. Researcher 使用独立的 120 秒超时和 12 次模型调用上限；create 任务不再
   暴露全文读取工具，避免把参考文档全文加入后续上下文。
3. Coordinator、Researcher、Writer、Reviewer 共享 36 次总模型调用预算；
   Writer/Reviewer 单次子任务上限为 10。
4. Researcher 不再看到 `write_todos`；Coordinator 只允许一次
   `write_todos`。
5. 任一 SubAgent 模型预算耗尽后，当前交付物确定性失败；Coordinator 不得以
   改写描述的方式重复派发，也不得让 Writer 在 Researcher 失败后继续写作。
6. Coordinator 不能使用虚拟文件工具接管 Writer 的草稿。
7. Writer/Reviewer 对固定文件使用 `offset=0, limit=1000` 一次完整读取；
   Writer 返工时并行读取研究摘要和草稿，并批量发出互不依赖的编辑调用。
8. 全部 Reviewer 批准后，服务端直接复用最终草稿和审查结果组装
   `DocumentWorkflowResult`，不再要求 Coordinator 在最后一次模型调用中
   重写整份正文 JSON。
9. 外层文档 Worker 超时从 300 秒调整为 480 秒，覆盖真实复杂单文档任务，
   但仍保留有限上限。

### 24.2 修复期间的新 TaskPlan 轨迹

所有任务均使用完整场景 3 Query，且 `resume_count=0`，没有恢复或复用旧
TaskPlan。

| TaskPlan | 结果 | 暴露的问题与后续处理 |
| --- | --- | --- |
| `task_plan_20260726152826_1fa8ab25408d` | 失败 | Researcher 第三次长请求超时；启用角色专用流式响应与超时。 |
| `task_plan_20260726153342_2bf64a127612` | 失败 | 8 次调用后仍重复；检查工具和 Todo 消耗。 |
| `task_plan_20260726153814_fdf5594b78ef` | 失败 | Researcher 仍被注入 Todo Prompt；从可见工具移除。 |
| `task_plan_20260726154434_4cae159f5576` | 失败 | create 任务读取参考全文，整体达到 300 秒；create 隐藏全文读取。 |
| `task_plan_20260726155309_d1c87529093e` | 失败 | Writer 非流式长输出超时并重试；Writer 改为流式且不自动重试。 |
| `task_plan_20260726155916_b755c9e6df95` | 失败 | Researcher 重复纠错；工具边界由专用 Middleware 确定性限制。 |
| `task_plan_20260726160344_cc4fd59e71a0` | 失败 | 动态隐藏工具方式没有真正改变模型可见工具；改为模型调用前过滤。 |
| `task_plan_20260726160852_a6a2df9731ea` | 失败 | Researcher 边界结果被通用 ToolCallLimit 的 after-model 拦截；由专用边界接管。 |
| `task_plan_20260726161210_73d45d3f8e81` | 失败 | 两次检索不能覆盖用户要求的五类主题；Researcher 有效检索上限调整为 5。 |
| `task_plan_20260726161829_fdf17eb6965b` | 失败 | 多 Agent 正常完成但约 311 秒，证明 300 秒外层上限过短。 |
| `task_plan_20260726162634_a7daf1e1e2b0` | 失败 | 32 次共享预算在第二轮 Writer 前耗尽；先减少无效读取和返工调用。 |
| `task_plan_20260726163517_cc249b5e35f1` | 失败 | Writer 修订耗尽 8 次后，Coordinator 越权使用文件工具继续修改；隐藏 Coordinator 文件工具并增加通用 SubAgent fail-fast。 |
| `task_plan_20260726164730_44bea46cd19b` | 失败 | 控制流已正确但初稿生成较慢，360 秒仍不足；外层上限调整为 480 秒。 |
| `task_plan_20260726165532_e82c74496e9e` | 失败 | Writer 反复按默认 100 行分页读取约 300 行草稿；固定 `limit=1000`。 |
| `task_plan_20260726170354_dddf4813b043` | 失败 | Reviewer 后的 Coordinator 长上下文非流式请求达到 60 秒；Coordinator/Reviewer 改为流式。 |
| `task_plan_20260726171216_8827d7932a38` | 失败 | Writer 把多处独立修改拆成多轮；要求批量编辑。 |
| `task_plan_20260726172028_691850d8273b` | 失败 | Writer 修订降到 7 次，但最终 Coordinator 结构化正文输出仍达到 60 秒。 |
| `task_plan_20260726172833_aadb8a3bec74` | 失败 | 即使 Coordinator 超时放宽到 120 秒，最终完整正文 JSON 仍占用外层 480 秒；改为服务端确定性组装批准结果。 |
| `task_plan_20260726173935_c8324be541fa` | 失败 | 不再超时，但 Writer 把 Supervisor 的 create 错写成 update，触发服务端范围校验；见 BUG-010。 |
| `task_plan_20260726175005_8acd72b40d07` | 成功到待确认 | 正确生成 create 预览并进入 `waiting_confirmation`。 |

这些轨迹表明最初的约 45 次调用不是单一模型请求过慢，而是 Todo、重复检索、
全文上下文、分页读取、串行返工和 Coordinator 最终重复生成正文共同造成的
未收敛。VPN/TUN 不是主要原因。

## 25. 场景 3 最终修复验收

### 25.1 测试环境与步骤

- 内置浏览器 Session ID：
  `gitlab-s3-supervisor-identity-fix-20260727-0022`。
- 全新 TaskPlan：
  `task_plan_20260726175005_8acd72b40d07`。
- 用户：`tool_manager`。
- 请求入口：`POST /rag/chat/stream/events`。
- 请求耗时：约 `320.0` 秒。

步骤：

1. 重启 FastAPI，加载最终修复代码。
2. 在内置浏览器提交完整场景 3 Query。
3. 观察 Researcher、Writer、Reviewer 和 Coordinator 事件。
4. 等待页面生成 TaskPlan 和候选正文。
5. 不点击确认按钮，只检查预览和数据库副作用。

### 25.2 最终结果

| 检查项 | 实际结果 |
| --- | --- |
| TaskPlan 状态 | `waiting_confirmation` |
| 动作数 | `1` |
| 操作 | `create` |
| 目标路径 | `development/gitlab-agent-mr-governance.md` |
| 文档正文 | 3,738 字符 |
| 二级章节 | 12 |
| 上线验收项 | 12 |
| Reviewer | `approved`，置信度 `0.92` |
| 权限决定 | `confirmation_required` |
| 目标权限 | `development` 部门可见 |
| checkpoint | `released`，`resumed_from_checkpoint=false` |
| GitLab change request | `0` |
| 目标 Manifest | `0` |
| 正式知识版本 | `4`，未变化 |

页面正确展示了：

- `agent_task_document_subagent_completed`；
- `agent_task_document_draft_created`，operation 为 `create`；
- `agent_task_document_review_completed`；
- `agent_task_document_action_prepared`；
- `agent_task_waiting_confirmation`；
- 确认接口
  `/agent/task-plans/task_plan_20260726175005_8acd72b40d07/confirm`。

本轮按用户授权边界停在人工确认前，没有调用确认接口，因此没有创建 GitLab
分支、Commit 或 MR，也没有写入 ES、Milvus 或推进
`publication_version`。这证明“预览前只读、确认后才创建 MR”的边界仍成立。

### 25.3 回归检查

- `test_deep_document_agent_workflow.py`：通过。
- `test_deep_document_checkpoint_runtime.py`：通过。
- `test_schema_field_descriptions.py`：通过。
- `py_compile`：通过。
- `git diff --check`：本轮修改文件没有新增空白错误；命令仍因工作区既有
  `scripts/docs/NL2SQL实现方案：.md:2685` 行尾空格而返回非零，并输出既有
  CRLF 转换提示。

场景 3 当前结论：**Deep Document Agent 未收敛问题已修复，已真实生成可审查
TaskPlan 并进入人工确认。** MR、Maintainer 合并、Webhook、Worker 和数据库
同步属于确认后的后半段，本轮未获授权执行，仍待后续继续验收。

## 26. 本轮新增系统 Bug 记录

### BUG-010：Writer 把 Supervisor 的 create 身份改写为 update

- 首次发生 TaskPlan：
  `task_plan_20260726173935_c8324be541fa`。
- 表现：Supervisor 明确生成 `operation=create`，
  `target_hint=development/gitlab-agent-mr-governance.md`；Writer 却把一份
  检索参考文档的 `doc_id`、路径和 SHA 填入最终草稿，并返回
  `operation=update`。
- 安全校验结果：`_validate_agentic_workflow_result` 正确拒绝该提案，错误为
  `DeepDocumentAgent 变更建议超出 Supervisor 操作范围`，没有产生 GitLab
  或知识库副作用。
- 根因：Writer 结构化输出仍被当成操作身份来源；检索到的参考文档身份污染了
  create 草稿。Prompt 约束不能替代服务端事实。
- 修复：批准结果组装时，operation 始终继承 Supervisor
  `DocumentDeliverable`；create 同时清空候选 `doc_id`、source path 和
  base SHA，只取 `target_hint` 的文件名，真实目录继续由
  `_create_target_path()` 按当前用户部门生成。
- 回归：新增“Writer 返回伪造 update 身份、Supervisor 要求 create”的测试，
  断言最终提案和最终草稿均收敛为 `create`，目标文件名为
  `damage-update.md`，候选 `doc_id` 为空。
- 真实复测：`task_plan_20260726175005_8acd72b40d07` 已通过，目标正确收敛为
  `development/gitlab-agent-mr-governance.md`。
- 当前状态：**已修复并通过离线回归和内置浏览器真实请求验证。**

## 27. 场景 3 人工确认后的 GitLab 端到端验收

验收时间：2026-07-27 02:03—02:10（Asia/Shanghai）。

### 27.1 人工确认与 Agent 提交结果

在用户完成 TaskPlan 预览检查并授权继续后，通过内置浏览器点击
“确认并执行 TaskPlan”。服务端没有直接修改 `main`，而是生成了以下 GitLab
变更：

| 项目 | 实际结果 |
| --- | --- |
| TaskPlan | `task_plan_20260726175005_8acd72b40d07` |
| 确认后状态 | `completed_with_warnings` |
| GitLab Source | `gitlab-development` |
| 临时分支 | `agent/task_plan_20260726175005_8acd72b40d07-0608c3da` |
| Agent Commit | `67ada47ec72ff8e9909fbbbd7735de5e83b6eef6` |
| Merge Request | `!4` |
| MR 创建者 | Project Access Token 机器人 `rag-agent` |
| MR 初始状态 | `opened` |

确认接口返回的说明明确指出：`main` 合并前不会修改 Elasticsearch 或
Milvus。该边界在 MR 创建后仍然成立。

### 27.2 Maintainer 审核与合并

使用内置浏览器中的 `tech-maintainer-e2e` Maintainer 账号完成审核：

1. 打开 MR `!4`，检查标题、目标分支、提交数和变更文件。
2. 点击 Approve，页面显示 `Approved by you`。
3. 点击 Merge，将 MR 合并到 `main`。
4. GitLab 页面显示 `Merged`，合并人为 `Tech Maintainer E2E`。
5. 合并 Commit 为
   `95d1c4c76f71d33cd1f46cde279f8926a4c09c1c`。
6. GitLab 页面显示 `Deleted the source branch`；API 查询临时分支返回不存在。

因此“Agent 只能创建临时分支、Commit 和 MR，Maintainer 人工批准后才能进入
`main`”的 GitLab 控制链路通过。

### 27.3 GitLab main 文件检查

合并后在内置浏览器打开：

`rag-kb-dev/rag-development-docs/-/blob/main/gitlab-agent-mr-governance.md`

页面能够正确渲染标题“GitLab Agent 文档变更治理规范”、角色职责、临时分支、
MR 审核、Webhook、Worker、原子发布、异常回滚和 12 项上线验收清单。文件大小
约 6.71 KiB，内容与人工确认时的候选文档一致。

但是文件实际位于 Repository 根目录：

```text
gitlab-agent-mr-governance.md
```

而 TaskPlan、dry-run 和权限预览中的目标路径为：

```text
development/gitlab-agent-mr-governance.md
```

该路径差异直接导致后续权限规则校验失败，详见 BUG-011。

### 27.4 Webhook 与 Worker 执行结果

GitLab 合并后，FastAPI Webhook 接口返回 `202`，PostgreSQL 保存了新的
Delivery：

| 字段 | 实际值 |
| --- | --- |
| Event UUID | `26e4f686-83e5-4215-95ca-bdd73fee1ec7` |
| Event Type | `Push Hook` |
| before SHA | `1ca37f12a66b447dab52667f783702c9b411a3ae` |
| after SHA | `95d1c4c76f71d33cd1f46cde279f8926a4c09c1c` |

Webhook 正确把 Development Source 的 `desired_sha` 推进到合并 Commit，并创建
增量同步任务：

```text
gitlab_job_28c784997488475c83cf6201612a2af5
```

Worker 能够领取任务并执行 Compare；Compare 返回一个新增文件：

```text
new_path=gitlab-agent-mr-governance.md
new_file=true
```

随后任务在 ACL 解析阶段失败。任务最终状态如下：

| 字段 | 实际值 |
| --- | --- |
| mode | `incremental` |
| status / phase | `failed / failed` |
| attempt_count | `3` |
| candidate_version | `null` |
| document / parent / child count | `0 / 0 / 0` |
| error_code | `ValueError` |
| error | `GitLab 文档权限规则不能扩大 Project 安全边界` |

Repository 根目录的 `.permission-rules.json` 只为 `development/`、
`art/`、`product_planning/` 和 `public/` 配置了显式规则；根目录未命中规则时
使用 `public` 默认值。Development Project 的安全边界是 `development`，因此
同步服务正确拒绝把根目录文档按 public 权限发布。

### 27.5 PostgreSQL、ES、Milvus 与版本检查

失败后的数据状态：

| 检查项 | 实际结果 |
| --- | --- |
| Development `desired_sha` | `95d1c4c7...` |
| Development `last_synced_sha` | 仍为 `1ca37f12...` |
| 正式 `publication_version` | 仍为 `4` |
| 候选版本 | 未创建 |
| 新 `knowledge_change_events` | 未创建 |
| 目标 `gitlab_documents` Manifest | `0` |
| ES 目标文档父子记录 | `0` |
| Milvus 目标文档子块记录 | `0` |

同时检查了根目录路径和预览路径对应的两个稳定 `doc_id`，ES 与 Milvus 均为
零记录。因此失败任务没有部分写入，也没有推进正式版本；旧版本仍可继续提供
检索。原子发布和失败隔离通过。

### 27.6 场景 3 最终结论

场景 3 当前结果：**部分通过，完整端到端同步失败。**

通过的部分：

- Deep Document Agent 能收敛并生成新 TaskPlan。
- 人工确认后，机器人只能创建临时分支、Commit 和 MR。
- Maintainer 能审核、批准并合并；临时分支已删除。
- `main` 合并能触发 Webhook、Delivery、增量任务和独立 Worker。
- 同步失败时不会污染 PostgreSQL Manifest、ES、Milvus 或正式版本。

失败的部分：

- Agent create 的 Repository Path 与 TaskPlan/权限路径不一致。
- 新文档不能通过 ACL 校验，未进入 RAG 正式知识版本。
- 因此本轮不能判定“新增文档可被 RAG 正确检索”为通过。

## 28. 本轮新增系统 Bug 记录

### BUG-011：Agent create 错误剥离部门目录，导致合并后同步失败

- 发生 TaskPlan：
  `task_plan_20260726175005_8acd72b40d07`。
- 预期路径：`development/gitlab-agent-mr-governance.md`。
- 实际 GitLab 路径：`gitlab-agent-mr-governance.md`。
- 直接原因：
  `GitLabAgentChangeService._resolve_location()` 在新文档不存在且按部门定位
  Source 时，把路径首段 `development` 删除后再创建 Commit。
- 冲突边界：当前真实 Repository 和 `.permission-rules.json` 都保留
  `development/` 目录；删除首段后，新文件无法命中部门规则，只能落入
  `public` 默认规则。
- 后果：MR 可以正常合并，但 Worker 在 ACL 阶段确定性失败，RAG 永远无法追上
  当前 `main` SHA。
- 当前状态：**已修复并通过离线回归、真实 MR 与知识库发布验收，见第 29 节。**

### BUG-012：MR 已合并，但 `gitlab_change_requests.status` 仍为 opened

- GitLab UI 状态：`Merged`。
- GitLab 合并 Commit：`95d1c4c76f71d33cd1f46cde279f8926a4c09c1c`。
- PostgreSQL 状态：对应 TaskPlan 的
  `gitlab_change_requests.status='opened'`，`updated_at` 仍停留在 MR 创建时间。
- 根因范围：当前代码只在创建 MR 时写入 change request；未找到消费 Merge
  Request 状态事件或主动对账 MR 状态的逻辑。
- 后果：React 管理页或审计接口读取数据库时会把已合并 MR 错误显示为 opened。
- 当前状态：**已修复；原 TaskPlan 对应记录已从 `opened` 对账为 `merged`，见第
  29 节。**

### BUG-013：确定性 ACL 校验错误被 Worker 无效重试三次

- 失败类型：本地确定性 `ValueError`，并非网络错误、GitLab `429/5xx` 或临时
  存储故障。
- 实际行为：Worker 捕获所有 `Exception` 后统一调用
  `mark_job_failed()`；Repository 在耗尽 `max_attempts=3` 前把任务放回
  `retry_wait`。
- 后果：相同权限错误被完整执行三次，增加日志噪声和无意义负载，且不能自行
  恢复。
- 期望：权限、路径、文件格式等确定性业务校验错误直接进入 `failed`；只对明确
  可恢复的外部服务或租约类错误重试。
- 当前状态：**已修复；确定性 `ValueError` 首次失败即终止，见第 29 节。**

## 29. BUG-011、BUG-012、BUG-013 修复与真实回归

验收时间：2026-07-27（Asia/Shanghai）。

### 29.1 修复内容

| Bug | 根因修复 |
| --- | --- |
| BUG-011 | `GitLabAgentChangeService._resolve_location()` 不再删除 TaskPlan 已确定的部门目录前缀；dry-run path 与 Commit path 使用同一个规范化路径。 |
| BUG-012 | Worker 在处理 Source 同步任务前，使用现有 GitLab MR 查询接口对账该 Source 的本地 `opened` change request，并保存 GitLab 返回的终态。 |
| BUG-013 | `mark_job_failed()` 增加明确的 `retryable` 输入；Worker 将本地确定性 `ValueError` 直接标记为 `failed`，外部临时错误继续沿用现有重试机制。 |

没有新增消息队列、Webhook 类型或状态同步服务；现有 Worker 对账点已经覆盖
“`main` 合并后同步”这条真实路径。

### 29.2 离线回归

`scripts/tests/integrations/test_gitlab_enterprise_sync.py` 新增并通过以下断言：

1. create 操作的 Commit path 保持
   `development/gitlab-agent-mr-governance.md`，不会剥离首段。
2. GitLab 返回 MR `merged` 时，本地 change request 从 `opened` 更新为
   `merged`。
3. 不可重试失败首次即进入 `failed`；`ValueError` 与临时
   `RuntimeError` 的分类结果符合预期。

同时通过：

- `py_compile`；
- 本轮修改文件的 `git diff --check`。

### 29.3 真实 GitLab 修复 MR

为修复已经合入 `main` 的错误路径，使用 Project Access Token 机器人创建修复
MR，没有使用 `root`、`tgg` 或员工 Token：

| 项目 | 实际结果 |
| --- | --- |
| 分支 | `agent/bug-011-restore-development-path` |
| Commit | `afa4d2b8fb241659d4eb434e2dc1200e8cb17044` |
| MR | `!5` |
| 变更 | `gitlab-agent-mr-governance.md` 原样重命名为 `development/gitlab-agent-mr-governance.md`，内容 `+0/-0` |
| 审核 | `tech-maintainer-e2e` 已 Approve |
| GitLab 终态 | `merged` |
| `main` SHA | `049c22ae7853e9318018e2e4a32ca49b71ed451d` |

### 29.4 Webhook、Worker 与知识存储验收

MR 合并后，FastAPI 收到两个 GitLab Push Webhook，均返回 `202`。Worker
完成 Archive 对账并发布版本 5：

| 检查项 | 实际结果 |
| --- | --- |
| 发布任务 | `gitlab_job_5556c9a8f1644ac6a77271045c079675` |
| status / phase | `succeeded / published` |
| attempt_count | `1` |
| candidate / active version | `5 / 5` |
| `desired_sha` / `last_synced_sha` | 均为 `049c22ae7853e9318018e2e4a32ca49b71ed451d` |
| Manifest path | `development/gitlab-agent-mr-governance.md` |
| Manifest ACL | `visibility=department`，`allowed_departments=["development"]` |
| 稳定 `doc_id` | `787f44904efba65722db4a6b252c8ddcc35862f71b7ec084e28456791ca13aca` |
| ES | 38 条有效记录：18 个父块、20 个子块 |
| Milvus | 20 条有效记录，全部为子块 |
| source revision | ES、Milvus 和 Manifest 均为 `049c22ae...` |
| 通知事件 | `knowledge_change_events.id=20`，`publication_version=5`，路径和 ACL 正确 |

原错误路径没有活动 Manifest；修复后的路径、ACL、父子块数量和版本完全一致。
随后周期性 reconcile 生成的任务为 `succeeded / no_changes`，说明 Source 已经
追平 `main`。

### 29.5 BUG-012 与 BUG-013 针对性真实验证

- 重新领取原场景 3 的同步任务时，Worker 先把
  `task_plan_20260726175005_8acd72b40d07` 对应 change request 对账为
  `merged`。
- 同一任务仍会读取旧错误 SHA 并触发 ACL `ValueError`，但新 Worker 在
  `attempt_count=1` 时直接进入 `failed`，没有进入 `retry_wait`，也没有再执行
  第二、第三次无效重试。

### 29.6 最终结论

BUG-011、BUG-012、BUG-013 均已关闭。场景 3 的 GitLab 后半链路现在完整通过：

```text
TaskPlan 路径
→ Agent 临时分支、Commit、MR
→ Maintainer 审核合并
→ main Webhook 202
→ 独立 Worker
→ Manifest、ES、Milvus
→ publication_version=5
```
