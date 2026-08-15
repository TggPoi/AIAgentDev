# 问题十二：Agent TaskPlan 多 Worker 一致性 —— 真实压力测试方案（含时间与 Token 成本估算）

> 前置状态：一致性改造已完成并通过功能验收（8 场景 PG 原子回归 / 双进程互斥 / 4 Worker 争抢 19+1 / 10 人冒烟 0 个 5xx）。**本方案针对的是"容量与性能"验收**——功能正确性已闭环，这里要回答的是"在 10–15 人真实负载下，延迟、错误率、资源水位和成本是否达标"。
> 模型链路：全部为阿里 DashScope qwen 系列（`LLM_PROVIDER=qwen`）。所有 Token 估算基于本工程真实配置与实测延迟，价格请以 [DashScope 模型调用计费页](https://help.aliyun.com/zh/model-studio/model-pricing) 为准（本方案不给虚构单价，给公式与决策方法）。

---

## 一、压测目标与验收口径

| 项 | 内容 |
|---|---|
| 目标 1 | 普通 RAG：15 个真实身份、多档并发下，成功率、P50/P95/P99 延迟达标，零 5xx |
| 目标 2 | 复杂 Agent：Research/Document 全链路在全局容量槽（默认 2/1）下的真实吞吐、单任务时长与成本 |
| 目标 3 | 容量保护：超出容量槽的请求精确返回 429 + Retry-After，无超发 |
| 目标 4 | 一致性加固：压测全程监控 `AGENT_TASK_PLAN_BUSY / LEASE_LOST / VERSION_CONFLICT / CAPACITY_EXCEEDED` 计数与 TaskPlan 终态，确认改造在负载下无回归 |
| 非目标 | 不承诺"支持 N 人"的销售数字；结论必须注明机器规格与外部配额（见 §七） |

**SLO 门槛（跑之前书面确认，跑完不许挪门槛）**：
- 普通 RAG：成功率 ≥ 99%；P95 ≤ 30s（真实模型链路实测 40–69s/请求，若业务接受以 LLM 链为主导的延迟，可书面放宽到 90s，但必须**跑前**定）；5xx = 0。
- 容量保护：429 只来自 `AGENT_CAPACITY_EXCEEDED`，数量与槽位配置严格一致。
- 一致性：压测结束后抽查全部 TaskPlan 终态、command 行数、fence token，不允许出现"双执行者"证据。

---

## 二、前置条件（Docker 环境已就绪 ✅）

| 项 | 状态 / 要求 |
|---|---|
| PostgreSQL / Redis / Elasticsearch | ✅ 容器已运行（5432/6379/9200） |
| Milvus standalone | ✅ 容器 healthy（19530）——**压测期间必须保持健康，否则检索降级会污染数据** |
| 服务部署 | `uvicorn fast_app.main:app --workers 4`（与验收时一致） |
| 测试身份 | **需要你提供 15 个真实用户的 JWT**（上次用 8 个现有用户 + 2 个临时用户凑了 10 个；本次建议直接用 15 个真实账号，写入 `.tmp/agent-load-users.json` 的 `token_env`） |
| 知识库 | 用现有 `docs/knowledge-base-acl-test` 即可；确认库内有可被检索命中的内容，避免空检索干扰延迟统计 |
| 费用上限 | **需要你给一个"总预算上限"数字**，压测脚本按阶段累计用量，触顶即停（§六） |
| 监控采集 | PostgreSQL 活跃连接/等待事件、`asyncio.to_thread` 排队、事件循环延迟、DashScope 429/5xx、每模型 Token 用量（DashScope 用量页或 LangSmith usage） |

---

## 三、模型调用地图（决定成本的核心）

压测中**每一类请求实际会调哪些模型**（来自当前 `.env` 与代码）：

| 环节 | 模型 | 触发条件 |
|---|---|---|
| Query Rewrite | qwen3.7-plus | 每轮对话（`QUERY_REWRITE_ENABLED=true`） |
| Router 意图 | qwen3.6-flash-2026-04-16 | 每次 RAG 请求 |
| 向量 Embedding | text-embedding-v4 | 检索（query 侧，量小） |
| Rerank | qwen3-rerank | 每次检索（top_k=5） |
| Prompt Guard | qwen3.6-flash | 查询 + 输出分句（`PROMPT_GUARD_MODE=hybrid`） |
| 答案生成 | **qwen3.7-plus** | 每次 RAG（父块上下文预算 3000 tokens） |
| 摘要记忆 | qwen3.6-plus | 历史超 12 条时（分摊到长会话） |
| Research 计划 | qwen3.7-plus + Reviewer **qwen3.7-max** | 每次研究任务创建 |
| Research 执行 | qwen3.7-plus（Worker/Evaluator） | 子问题×工具×纠正轮 |
| Document 多 Agent | qwen3.7-plus（Coordinator/Researcher/Writer/Reviewer） | 文档任务全流程（**成本大头**） |

**成本集中点**：普通 RAG 的 qwen3.7-plus 与 Document 多 Agent 的长上下文调用（单任务 `AGENT_DOCUMENT_MAX_TOTAL_DRAFT_CHARS=400000`，全流程可能 50 万–150 万 tokens——压测时建议临时调低，见 §四 P3）。

---

## 四、压测阶段划分（P0–P5，含预计时间与 Token）

> Token 估算口径：单次普通 RAG ≈ **11k–20k tokens**（跨全部模型合计，中值 15k；依据：实测请求 40–69s、父块预算 3000 tokens、rewrite/rerank/guard 的输入规模）。复杂任务为区间估算。**所有数字都会在 P0 校准后被真实用量替换**（§五）。

### P0 · 校准批（0.5–1 小时，≈ 0.4M–0.6M tokens）
- 目的：拿到"单请求真实 token 数"，把本方案所有估算换成实测。
- 动作：单用户串行 20 次普通 RAG + 1 个**最小** Research 任务（`AGENT_RESEARCH_MAX_SUB_QUESTIONS=2` 临时改小）。
- 产出：从 DashScope 用量页（或 LangSmith 的 usage 字段）读出分模型 token 数 → 回填 §五 的校准列。

### P1 · 控制面（30 分钟，≈ <0.1M tokens，几乎不花钱）
- 目的：排除"压测脚本/契约问题"对后续 LLM 花费的干扰。
- 动作：GET 详情 × 200；20 并发 confirm 争抢（复用验收脚本）；cancel 同键重放 × 50。这些路径不触发大模型调用。
- 通过门槛：与功能验收结果一致（19×409 + 唯一执行者；GET P95 < 100ms）。

### P2 · 普通 RAG 阶梯（1–1.5 小时，≈ 2.5M–4M tokens）
- 动作：并发 1 → 3 → 5 → 10 → 15，每档 5 分钟 + 冷却 2 分钟，`accept_agent_task_plan_load.py`（controls 为空）。
- 预计请求数：Σ(并发 ÷ 48s × 300s) ≈ **210 请求**（48s 为上次实测均值）。
- 通过门槛：每档记录成功率/P50/P95/P99/连接池等待；任何一档出现 5xx 即停，先修再继续。

### P3 · 复杂 Agent 容量保护（1–2 小时，≈ 3.5M–5M tokens，**成本大头**）
- 动作（对齐修订版场景 C）：把 `AGENT_RESEARCH_GLOBAL_CONCURRENCY=2`、`AGENT_DOCUMENT_GLOBAL_CONCURRENCY=2` 写入测试环境变量；同时发起 3 个全新 Research confirm + 3 个全新 Document confirm + 背景 5 并发 RAG（10 分钟）。
- 预期：4 个被受理、2 个返回 429 `AGENT_CAPACITY_EXCEEDED`。
- **省钱开关（强烈建议）**：测试期间临时调低 `AGENT_DOCUMENT_MAX_TOTAL_DRAFT_CHARS`（如 40000）与 `AGENT_DOCUMENT_MAX_DELIVERABLES`（如 2），把单文档任务从"百万级 tokens"压到"10 万级"；容量保护验证的是**槽位与 429**，不需要真实长文。
- 时间：Document 单任务超时上限 480s，全批预计 20–40 分钟。

### P4 · 混合长稳 30 分钟（1 小时含准备，≈ 2M–3.5M tokens）
- 动作：场景 A——15 身份、并发 5、持续 30 分钟，`--duration-seconds 1800`；controls 放 1 个全新 Research confirm 作长稳期间的一致性观察点。

### P5 · 峰值冲刺（可选，0.5 小时，≈ 3M tokens）
- 动作：场景 B——15 身份、并发 15、10 分钟。用于看连接池/外部 429 的行为，**不作为容量承诺依据**。

| 阶段 | 执行时长 | 预计请求/任务 | 预计 Token |
|---|---|---|---|
| P0 校准 | 0.5–1 h | 20 RAG + 1 小 Research | 0.4M–0.6M |
| P1 控制面 | 0.5 h | 270 次控制面调用 | <0.1M |
| P2 阶梯 | 1–1.5 h | ~210 RAG | 2.5M–4M |
| P3 容量保护 | 1–2 h | 3R+3D+背景 RAG | 3.5M–5M（不降配则可能 8M+） |
| P4 长稳 | 1 h | ~190 RAG + 1 Research | 2M–3.5M |
| P5 峰值（可选） | 0.5 h | ~190 RAG | ~3M |
| **合计** | **5–7 h 执行 + 2–4 h 分析** | — | **≈ 10M–20M tokens（按 P3 降配估算）** |

> 时间说明：执行总时长 5–7 小时，建议排两个半天（P0–P2 半天，P3–P5 半天 + 分析）。普通 RAG 的墙钟时间受真实模型延迟主导（实测 48s 均值），无法通过本地并发显著缩短。

---

## 五、Token 估算方法（校准一次，全局套用）

**单请求估算表（区间，P0 校准后替换）**：

| 环节 | 模型 | 输入 tokens | 输出 tokens |
|---|---|---|---|
| Query Rewrite | qwen3.7-plus | 1.5k–2.5k | 40–80 |
| Router | qwen3.6-flash | 0.8k–1.2k | 150–300 |
| Embedding | text-embedding-v4 | 100–300 | — |
| Rerank | qwen3-rerank | 2k–5k | — |
| Prompt Guard | qwen3.6-flash | 1k–2k | 100–300 |
| 答案生成 | qwen3.7-plus | 5k–8k | 300–800 |
| 摘要记忆（分摊） | qwen3.6-plus | ~300 | ~200 |
| **普通 RAG 单请求合计** | — | **≈ 11k–20k** | — |
| Research 计划创建 | plus+max | 25k–50k | — |
| Research 执行（单任务） | plus 为主 | 250k–500k | — |
| Document 全流程（单任务，默认 40 万字符上限） | plus 为主 | 500k–1.5M | — |

**校准步骤（P0 必做）**：
1. 跑 P0 的 20 个 RAG 请求；
2. 打开 [DashScope 用量明细](https://bailian.console.aliyun.com)（或 LangSmith run 的 usage 字段，工程已开 tracing）按模型导出 token 数；
3. 用 `实测单请求 tokens × 各阶段请求数` 重算 §四 的 Token 列——**只有这一步之后才能做购买决策**。

---

## 六、成本换算与"套餐 vs 余额"决策

**成本公式**（不给虚构单价，你从官网价格页填入即可）：

```
阶段成本 = Σ模型 ( 该模型输入tokens × 输入单价 + 该模型输出tokens × 输出单价 )
总预算   = Σ各阶段成本
```

价格依据（跑前自行核对当前价）：
- [模型调用计费（按量，每百万 tokens）](https://help.aliyun.com/zh/model-studio/model-pricing)
- [千问各系列价格对比与套餐选择（第三方整理，含免费额度说明）](https://github.com/pmfyh4/qwen-model-pricing)
- [TokenPlan 2026 升级说明（Credits 计费、支持模型范围）](https://developer.aliyun.com/article/1749589)

**决策建议**：

| 场景 | 建议 | 理由 |
|---|---|---|
| 只跑这一次全量验收（≈10M–20M tokens） | **充值余额（按量）** | 总量有限且一次性；余额按 token 计费更透明，跑完还能剩 |
| 每月都跑性能门禁 / CI 回归 | **TokenPlan 套餐** | 若套餐额度能覆盖月用量（10M–20M+）且包含你用的全部模型（重点确认 **qwen3.7-max 与 qwen3-rerank 是否在套餐内**），月费可能更划算 |
| 不确定 | **先按量充值小额（够跑 P0+P1）→ 校准后精算总量 → 再决定** | 用 0.5M tokens 的实测单价反推总预算，误差最小；注意新用户有 90 天有效期免费额度，优先用掉 |

**决策树**：
```
P0 校准（按量，<0.1 元量级）
   → 拿到单请求真实 token
      → 全量总预算 = 单请求token × 各阶段请求数（§四已列请求数）
         → 预算 < 套餐额度且模型全覆盖 且 后续每月复跑 → 套餐
         → 否则 → 余额按量
```

**熔断与预算保护**：给压测脚本增加累计 Token 预算检查（DashScope 用量 API 或脚本本地计数），达到预算 80% 告警、100% 停止；任何阶段 5xx > 1% 立即停止。

---

## 七、必须同时采集的系统证据（否则结论无效）

按修订版方案附录 C.4，每个报告旁边保存同一时间窗口的：
- Uvicorn Worker 数、应用 commit、**测试机 CPU/内存规格**（本次必须补上）；
- PostgreSQL 活跃连接、等待事件、事务时长、连接池等待/超时；
- Redis / Elasticsearch / Milvus 错误率与延迟；
- DashScope 429/5xx、首 token 延迟、分模型 Token 用量；
- `AGENT_TASK_PLAN_BUSY / AGENT_CAPACITY_EXCEEDED / AGENT_TASK_PLAN_LEASE_LOST / VERSION_CONFLICT` 计数；
- 每个 TaskPlan 的 command 行数、fence token、终态（一致性在负载下的证据）。

---

## 八、需要你提供的输入清单

1. **15 个真实用户 JWT**（写入 `.tmp/agent-load-users.json` 的 `token_env` 环境变量）；
2. **费用上限**（数字，触发熔断）；
3. **SLO 书面确认**（§一 的 P95 门槛按业务要求定死）；
4. 一个可 confirm 的全新 Research TaskPlan 与 Document TaskPlan 的来源（正常走一次真实 Planner 产出，或测试辅助脚本生成）；
5. 机器规格信息（跑在哪台机器、几核几 G）。

---

## 九、可直接抄的命令清单

```powershell
# 前置：确认全栈健康
docker ps   # milvus-standalone / agent_redis / pg_vector_db / es-dev 全部 Up

# P1 控制面（不花钱）
$env:PYTHONPATH="src;scripts\tests\document_security"
.\.venv\Scripts\python.exe -B scripts\tests\document_security\accept_agent_task_plan_http_contention.py `
  --task-plan-id "task_plan_XXX" --token-env LOAD_USER_01_TOKEN

# P2 阶梯（每档 5 分钟，示例为并发 5）
.\.venv\Scripts\python.exe -B scripts\tests\document_security\accept_agent_task_plan_load.py `
  --config .tmp/agent-load-users.json --base-url http://127.0.0.1:8000 `
  --duration-seconds 300 --concurrency 5 --min-success-rate 0.99 `
  --max-p95-ms 90000 --report reports/p2-concurrency-5.json

# P3 容量保护（先临时调小文档任务上限省钱）
$env:AGENT_RESEARCH_GLOBAL_CONCURRENCY="2"
$env:AGENT_DOCUMENT_GLOBAL_CONCURRENCY="2"
$env:AGENT_DOCUMENT_MAX_TOTAL_DRAFT_CHARS="40000"
$env:AGENT_DOCUMENT_MAX_DELIVERABLES="2"
# 6 个全新任务同时 confirm，预期 4 受理 + 2×429 AGENT_CAPACITY_EXCEEDED

# P4 长稳 30 分钟
.\.venv\Scripts\python.exe -B scripts\tests\document_security\accept_agent_task_plan_load.py `
  --config .tmp/agent-load-users.json --duration-seconds 1800 --concurrency 5 `
  --report reports/p4-long-stability.json
```

---

*引用：本方案的场景框架来自修订版方案附录 C（场景 A/B/C）与附录 F（压测脚本）；Token 估算口径基于当前 `.env` 模型配置与 2026-08 实测（普通 RAG 均值 48s、14/14 成功）。价格与套餐规则请以 DashScope 官网为准。*
