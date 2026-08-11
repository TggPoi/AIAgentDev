# 交接文档：RAG 评测集 V2.1.0 构建（第4步审核 + 第5步验收）

> 交接时间：2026-08-11。前序工作由 Lingma 完成；本文档供 Codex 接手剩余工作。
> 先读 `AGENTS.md` 全文，再读本文件。代码与文档冲突时以代码为准。

## 1. 任务总览（五步计划）

| 步骤 | 状态 |
|---|---|
| 第0步：rbac_reader / rbac_operator 创建 API Key 并注入运行脚本 | ✅ 完成 |
| 第1步：盘点 274 个有效 markdown_child + 权限矩阵 | ✅ 完成 |
| 第2步：case 设计（15 条，覆盖 7 个场景标签） | ✅ 完成 |
| 第3步：candidate 数据集生成 + 试跑验证 | ✅ 完成（最终哈希 f1967310…） |
| **第4步：用户人工审核 + 晋升 golden** | ⏳ **待执行（接手点）** |
| **第5步：rag_agent 链路验收** | ⏳ 待执行 |

## 2. 关键产物与文件

- 数据集：`src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.0.json`
  - lifecycle=candidate，15 条 case
  - content_sha256=`f1967310c6ad10b01f635196487209c94e1852a9691be9ed5c262ed86a547116`
  - source_revision=`sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`，knowledge_version=6
  - annotated_by=`lingma-agent:v2.1-candidate-builder`
  - 旧数据集 `stage11_rag_eval_cases.v2.0.0.json` 原样保留，禁止改动
- 审核材料（已交付用户）：`reports/eval-dataset-v2.1.0-review.md`（15 条 case 清单、试跑汇总、风险、晋升说明）
- 构建脚本：`.tmp/build_eval_dataset_v2_1.py`（重跑可复现相同哈希；含场景矩阵自检 + seal + 回读校验）
- 检索诊断脚本：`.tmp/debug_retrieval_case.py`（用法：`python .tmp\debug_retrieval_case.py <case_id> <rbac_reader|rbac_operator>`）
- 报告汇总脚本：`.tmp/summarize_eval_report.py`（用法：`python -X utf8 .tmp\summarize_eval_report.py reports\<目录>`）
- 知识库盘点：`.tmp/knowledge_inventory.json`、`.tmp/knowledge_digest.txt`
- 凭据（均已 gitignore，禁止提交、禁止打印到输出）：
  - `.tmp/rag_eval_api_keys.json`（rbac_reader / rbac_operator 的 api_key 与 user_id）
  - `run_rag_eval_local.ps1`（本地评测启动器，内含凭据）

## 3. 本阶段已完成的代码改动（均已试跑验证）

1. `src/fast_app/rag_eval/runner.py`：`LightweightRagEvalRunner` 新增 `allow_candidate: bool = False`；`run()` 门禁改为 `lifecycle != "golden" and not self.allow_candidate`。正式回归测试（`scripts/tests/evaluation/test_eval_dataset_v2.py`，走 `load_golden_eval_dataset`）不受影响。
2. `scripts/run_streaming_rag_eval.py`：构造 runner 时传 `allow_candidate=dataset.lifecycle != "golden"`。
3. `src/fast_app/evaluation/pipeline/snapshot_capture.py`：snapshot 逻辑身份兼容真实写入链路的 `logical_record_id`（原先只读历史 mock 键名 `logical_chunk_id`，导致检索指标恒为 0）。
4. `.gitignore`：追加 `.tmp/rag_eval_api_keys.json`。

## 4. 第3步试跑最终结论（基于哈希 f1967310…）

- reader 全量（reports\rag-eval-v21-reader-final2）：11/12 evaluated；recall 均值 0.875、hit_rate 1.0、mrr 0.781。唯一失败 `reader_milvus_index_check` 是 Router 概率性降级（clarification_required），单条复跑（reports\rag-eval-v21-milvus3）recall=1.0 通过。
- operator 全量（reports\rag-eval-v21-operator-final2）：3/3 evaluated；recall 均值 0.75、hit_rate 1.0。
- 单条修复复验：reports\rag-eval-v21-visibility2（reader_visibility_positive recall=0.50）、reports\rag-eval-v21-visibility（operator_art_visible_scope_multi recall=0.50）。
- 15 条 case 全部验证过正确路由 `simple_rag -> knowledge_retrieval`。

### 已知系统性风险（写进了审核材料，回归判断时必须记住）

1. **Router LLM 概率性波动**：任何 case 有小概率降级为 `clarification_required`（router_low_confidence，阈值 0.75，见 `fast_app/core/config.py`）或误判 `question_decomposition`（Router prompt 规定"综合多个方面→decomposition"）。遇到单条 route_mismatch 先复跑确认，不要立即判数据集问题。
2. **Precision@K 天然偏低**：黄金 chunk 1-2 个而 top_k=5-8，precision 0.2-0.4 未过 0.5 阈值属预期。主指标看 Recall/HitRate。
3. **多来源 case recall=0.5**：两个黄金 chunk 语义相近时 rerank 常只保其一，属检索能力现状，不是标注错误。

## 5. 第4步剩余工作（接手点）

1. 等用户对 `reports/eval-dataset-v2.1.0-review.md` 给出审核结论；若用户提出个别 case 修改意见，改 `.tmp/build_eval_dataset_v2_1.py` 对应条目后重跑该脚本重新生成数据集（哈希会变，需重新试跑受影响 case 确认）。
2. 用户审核通过后执行晋升（可由 Codex 代改文件，但 reviewed_by 必须向用户要真实标识）：
   - `lifecycle`: `candidate` → `golden`
   - 每条 case `review_status`: `pending_review` → `approved`
   - 补 `reviewed_by`：必须 ≠ `lingma-agent:v2.1-candidate-builder`
   - 重算 `content_sha256`：复用 `fast_app` 的 seal 逻辑（`seal_eval_dataset_payload`，构建脚本里已 import），sha256 覆盖除自身外的全部数据集内容
3. 晋升后验证：确认 `scripts/tests/evaluation/test_eval_dataset_v2.py` 的 `load_golden_eval_dataset` 门禁能加载该数据集（注意：`.venv` 无 pytest、`.venv-rag-eval` 无 langchain，测试环境不完整——可用 `.venv\Scripts\python.exe` 直接 import loader 调用 `load_golden_eval_dataset()` 验证，不必跑 pytest）。

## 6. 第5步：rag_agent 链路验收

用户已确认只验收 rag_agent 链路（数据集问句、黄金标注、预期路由全部按 rag_agent 校准；classic/langgraph 无 Router route_intent，不纳入本次验收）。在 golden 状态下用 rag_agent provider 跑全量（reader 与 operator 分开跑，一次运行只能一个身份）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File run_rag_eval_local.ps1 `
  -EvalUser rbac_reader --pipeline-provider rag_agent --mode retrieval `
  --dataset src\fast_app\evaluation\datasets\stage11_rag_eval_cases.v2.1.0.json `
  --eval-principal user_rp-iYI84UD1vMXH039AGHYQz `
  --output-dir reports\<新目录名>
```

- operator 身份：`-EvalUser rbac_operator --eval-principal user_MBeEmT7K2eGguofW4CZ1aGTp`。
- 验收通过标准参考第3步试跑结论：路由全部 `simple_rag -> knowledge_retrieval`，answerable case 的 Recall/HitRate 达标；预期差异（概率性路由波动、precision 偏低、多来源 recall=0.5）按第4节风险条目判断。
- 每跑完用 `.tmp\summarize_eval_report.py` 汇总，产出验收报告交用户。

## 7. 运行环境注意事项

- 主虚拟环境：`.venv\Scripts\python.exe`，需 `$env:PYTHONPATH="src"`。
- PowerShell 5.1：不支持 `&&`，用 `;`；python 内联带中文/引号命令易被 PS 解析破坏，写成 `.tmp` 脚本文件再执行；控制台 GBK 编码问题用 `python -X utf8`。
- 评测走进程内 httpx.ASGITransport 打真实 `/rag/chat/stream/events`，需要本地 Docker 的 Milvus / ES / Redis / PostgreSQL 在运行。
- LangSmith 已启用（project=python-agent-study-phase-final-3），无需改动。

## 8. 禁止事项

- 禁止提交任何含凭据的文件（`run_rag_eval_local.ps1`、`.tmp/rag_eval_api_keys.json` 已 gitignore）。
- 禁止改动旧数据集 v2.0.0 与 `src/app` 学习代码。
- 禁止在 candidate 未晋升前把它当 golden 用于正式回归。
