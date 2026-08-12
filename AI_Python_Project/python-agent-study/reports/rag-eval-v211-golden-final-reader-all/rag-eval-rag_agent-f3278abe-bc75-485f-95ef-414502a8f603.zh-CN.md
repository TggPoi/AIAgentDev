# 轻量流式 RAG Eval 中文报告

## 一、运行概览

| 项目 | 结果 |
|---|---|
| 运行 ID | `f3278abe-bc75-485f-95ef-414502a8f603` |
| 流水线 | `rag_agent` |
| 运行状态 | `partial`（部分完成） |
| 数据集 | `stage11_acl_rag_eval@2.1.1` |
| 数据集内容哈希 | `ddd0983fbd2653fb9204fb116528bf460bec0c1109c7dff81d2ae200972da573` |
| 知识源版本 | `sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723` |
| 被测模型 | `qwen:qwen3.7-plus` |
| 评判模型 | `qwen3.7-max` |
| Case 数量 | 12 |
| Case 执行结果 | 已评测 12，路由失败 0，跳过 0 |
| 总耗时 | 3,481,114.65 毫秒，约 58 分 1 秒 |
| 基线报告 | 未提供，本次不计算相对基线变化 |

本报告状态为 `partial`，原因是部分生成指标的评判过程发生超时或输出格式错误。12 条 RAG Case 本身均已进入 `simple_rag -> knowledge_retrieval`，没有 Case 级路由失败。

## 二、八项指标汇总

所有指标的通过阈值均为 `0.5`。平均分只统计状态为“已评测”的结果，不把“跳过”或“错误”按零分计入。

| 层级 | 指标 | 中文含义 | 平均分 | 已评测 | 通过 | 跳过 | 错误 | 判断 |
|---|---|---|---:|---:|---:|---:|---:|---|
| 检索层 | `retrieval_recall_at_k` | 召回率@K | 0.8889 | 9 | 9 | 3 | 0 | 较好，相关块基本能够被召回 |
| 检索层 | `retrieval_precision_at_k` | 精确率@K | 0.2889 | 9 | 1 | 3 | 0 | 偏低，返回结果中包含较多非 Golden 块 |
| 检索层 | `retrieval_hit_rate_at_k` | 命中率@K | 1.0000 | 9 | 9 | 3 | 0 | 很好，所有可回答 Case 均至少命中一个相关块 |
| 检索层 | `retrieval_mrr` | 平均倒数排名 | 0.7222 | 9 | 7 | 3 | 0 | 整体尚可，个别正确块排名靠后 |
| 生成层 | `generation_faithfulness` | 忠实度 | 1.0000 | 9 | 9 | 0 | 3 | 成功评判的答案均忠于上下文，但有 3 项未得到有效分数 |
| 生成层 | `generation_answer_relevance` | 答案相关性 | 0.8977 | 10 | 10 | 0 | 2 | 成功评判的答案与问题高度相关 |
| 生成层 | `generation_answer_completeness` | 答案完整性 | 0.2857 | 7 | 2 | 3 | 2 | 原始分数保留，但受已确认的 GEval 分制冲突影响，不能用于判断答案完整性 |
| 生成层 | `generation_context_utilization` | 上下文利用率 | 1.0000 | 10 | 10 | 0 | 2 | 原始分数保留，但与完整性使用相同的错误分制指令，需修复后重测 |

## 三、总体结论

1. 检索层的“能否找到相关内容”表现较好：可回答 Case 的命中率为 1.0，平均召回率为 0.8889。
2. 检索结果的纯度不足：精确率只有 0.2889。多数 Case 返回 5 个结果但只有 1 个 Golden Chunk，因此常见精确率为 0.2。
3. 排序质量仍有优化空间：平均倒数排名为 0.7222，其中父子块扩展 Case 和 Webhook 多来源 Case 的首个 Golden Chunk 排名较后，MRR 均为 0.25。
4. 忠实度和答案相关性在成功评判的样本中表现较好；上下文利用率虽然原始分数为 1.0，但因 GEval 分制冲突暂不能作为可靠结论。
5. 原报告中“答案完整性明显不足”的结论经代码核查后撤回。完整性评判步骤要求 `0–1` 分，但 DeepEval 4.1.3 实际要求 `0–10` 原始分并再次归一化，现有 0.1、0.5、1.0 分数均需在修复后重测。
6. 本次生成层数据还受到 Worker 总超时和 Judge 非法结构化输出影响。因此不能把缺失分数解释为模型得分为零，也不能将本次生成层结果视为最终稳定基线。

## 四、Case 执行明细

| Case ID | 查询问题 | 是否应可回答 | 实际路由 | Case 状态 | 耗时（毫秒） |
|---|---|---|---|---|---:|
| `reader_es_milvus_parent_child_expansion` | 部署验收文档中的“ES 父子块与 Milvus 子块校验”章节规定了哪些检查要求？ | 是 | `simple_rag -> knowledge_retrieval` | 已评测 | 120,086.66 |
| `reader_ue5_perfect_block` | UE5 战斗系统设计中完美格挡成功后的效果与时间窗口控制方式 | 是 | `simple_rag -> knowledge_retrieval` | 已评测 | 90,026.19 |
| `reader_gitlab_rollback_authoritative` | 知识库文档发布出问题需要回滚时的正确回滚方式 | 是 | `simple_rag -> knowledge_retrieval` | 已评测 | 153,045.48 |
| `reader_webhook_worker_multi_source` | GitLab MR 合并后文档发布任务是如何处理的？ | 是 | `simple_rag -> knowledge_retrieval` | 已评测 | 141,994.25 |
| `reader_milvus_index_check` | RAG 后端文档导入后检查 Milvus collection 需要确认哪些内容？ | 是 | `simple_rag -> knowledge_retrieval` | 已评测 | 102,242.76 |
| `reader_art_acl_negative` | 角色美术规范是否包含“月光披风规则”和“女巫帽轮廓标准”这两个内部测试关键词？ | 否 | `simple_rag -> knowledge_retrieval` | 已评测 | 66,263.69 |
| `reader_visibility_positive` | 权限过滤规则中 development 用户应能检索到哪些文档，以及不应检索到哪些文档？ | 是 | `simple_rag -> knowledge_retrieval` | 已评测 | 53,173.62 |
| `reader_incremental_input_buffer` | 增量更新验收规则中输入缓存窗口的建议值 | 是 | `simple_rag -> knowledge_retrieval` | 已评测 | 47,473.83 |
| `reader_unanswerable_audio_middleware` | 知识库中是否有关于 Wwise 音频中间件 Profiler 接入战斗系统性能分析的资料？ | 否 | `simple_rag -> knowledge_retrieval` | 已评测 | 21,096.06 |
| `reader_agent_tool_acceptance_underfilled` | Agent Tool Acceptance 文档用于哪个阶段的 HTTP 验收？ | 是 | `simple_rag -> knowledge_retrieval` | 已评测 | 23,714.79 |
| `reader_worker_failure_recovery` | 知识发布任务 Worker 失败后的恢复处理方式 | 是 | `simple_rag -> knowledge_retrieval` | 已评测 | 113,602.90 |
| `reader_no_result_backup_schedule` | 知识库文档冷备策略的执行时间与备份文件存放的存储桶位置 | 否 | `simple_rag -> knowledge_retrieval` | 已评测 | 25,491.01 |

## 五、检索层逐 Case 得分

“不适用”表示该 Case 被标记为不可回答，没有 Golden 相关逻辑 Chunk，因此检索指标按规则跳过。

| Case ID | 召回率@K | 精确率@K | 命中率@K | 倒数排名 | 结果说明 |
|---|---:|---:|---:|---:|---|
| `reader_es_milvus_parent_child_expansion` | 1.0000 | 0.2000 | 1.0000 | 0.2500 | 已召回，但首个相关结果排名靠后 |
| `reader_ue5_perfect_block` | 1.0000 | 0.2000 | 1.0000 | 1.0000 | 首位命中，返回集合纯度偏低 |
| `reader_gitlab_rollback_authoritative` | 1.0000 | 0.2000 | 1.0000 | 0.5000 | 第二位命中，返回集合纯度偏低 |
| `reader_webhook_worker_multi_source` | 0.5000 | 0.2000 | 1.0000 | 0.2500 | 只召回一半 Golden Chunk，首个相关结果排名靠后 |
| `reader_milvus_index_check` | 1.0000 | 0.2000 | 1.0000 | 1.0000 | 首位命中，返回集合纯度偏低 |
| `reader_art_acl_negative` | 不适用 | 不适用 | 不适用 | 不适用 | 不可回答 Case，按规则跳过 |
| `reader_visibility_positive` | 0.5000 | 0.2000 | 1.0000 | 1.0000 | 首位命中，但只召回一半 Golden Chunk |
| `reader_incremental_input_buffer` | 1.0000 | 0.2000 | 1.0000 | 1.0000 | 首位命中，返回集合纯度偏低 |
| `reader_unanswerable_audio_middleware` | 不适用 | 不适用 | 不适用 | 不适用 | 不可回答 Case，按规则跳过 |
| `reader_agent_tool_acceptance_underfilled` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | Underfilled 场景下检索结果完全正确 |
| `reader_worker_failure_recovery` | 1.0000 | 0.2000 | 1.0000 | 0.5000 | 第二位命中，返回集合纯度偏低 |
| `reader_no_result_backup_schedule` | 不适用 | 不适用 | 不适用 | 不适用 | 不可回答 Case，按规则跳过 |

## 六、生成层逐 Case 得分

“错误”表示 Judge 没有产生有效指标结果；“不适用”表示不可回答 Case 没有 `required_key_facts`，因此完整性指标按规则跳过。表中保留本次运行的原始数值，但完整性和上下文利用率均受 GEval 分制冲突影响，不能直接解释为真实质量。

| Case ID | 忠实度 | 答案相关性 | 答案完整性 | 上下文利用率 | 结果说明 |
|---|---:|---:|---:|---:|---|
| `reader_es_milvus_parent_child_expansion` | 错误 | 1.0000 | 0.1000 | 1.0000 | 忠实度 Judge 输出格式错误；两个 GEval 原始分待修复后重测 |
| `reader_ue5_perfect_block` | 1.0000 | 1.0000 | 0.1000 | 1.0000 | 两个 GEval 原始分待修复后重测 |
| `reader_gitlab_rollback_authoritative` | 1.0000 | 1.0000 | 0.1000 | 1.0000 | 两个 GEval 原始分待修复后重测 |
| `reader_webhook_worker_multi_source` | 错误 | 错误 | 错误 | 错误 | DeepEval Worker 超过 300 秒 |
| `reader_milvus_index_check` | 错误 | 错误 | 错误 | 错误 | DeepEval Worker 超过 300 秒 |
| `reader_art_acl_negative` | 1.0000 | 0.7273 | 不适用 | 1.0000 | 不可回答 Case，完整性不适用 |
| `reader_visibility_positive` | 1.0000 | 0.7500 | 0.1000 | 1.0000 | 两个 GEval 原始分待修复后重测 |
| `reader_incremental_input_buffer` | 1.0000 | 1.0000 | 0.5000 | 1.0000 | 两个 GEval 原始分达到阈值，但仍需修复后重测 |
| `reader_unanswerable_audio_middleware` | 1.0000 | 1.0000 | 不适用 | 1.0000 | 不可回答 Case，完整性不适用 |
| `reader_agent_tool_acceptance_underfilled` | 1.0000 | 0.5000 | 1.0000 | 1.0000 | 相关性恰好达到阈值；两个 GEval 原始分待修复后重测 |
| `reader_worker_failure_recovery` | 1.0000 | 1.0000 | 0.1000 | 1.0000 | 两个 GEval 原始分待修复后重测 |
| `reader_no_result_backup_schedule` | 1.0000 | 1.0000 | 不适用 | 1.0000 | 不可回答 Case，完整性不适用 |

## 七、低分原因与代码归因

### 7.1 归因结论

本节以报告 JSON、Golden V2.1.1 数据集、当前工程源码和本地安装的 DeepEval 4.1.3 源码为证据。没有重新调用被测模型或 Judge。

| 现象 | 直接原因 | 是否属于代码问题 | 置信度 |
|---|---|---|---|
| 8 条 Precision@K 为 0.2 | 每条最终返回 5 个去重 Chunk，其中命中 1 个 Golden Chunk，按 `1 / 5` 得到 0.2 | 指标公式本身正确；统一 0.5 阈值与稀疏 Golden 标注的组合需要校准 | 高 |
| 两条 MRR 为 0.25 | 首个 Golden Chunk 位于最终 rerank 第 4 名，按 `1 / 4` 得到 0.25 | 只能确认排序结果不理想，不能仅凭稳定报告判定 reranker 代码缺陷 | 高 |
| 两条 Recall@K 为 0.5 | Case 各有 2 个 Golden Chunk，最终只命中 1 个，按 `1 / 2` 得到 0.5 | 只能确认漏召回；无法区分召回、查询改写、rerank 或标注覆盖问题 | 高 |
| 5 条完整性为 0.1 | 本地步骤要求 `0–1`，DeepEval 实际要求 `0–10` 原始分后再归一化 | **已确认的 Eval 实现缺陷** | 高 |
| 上下文利用率均为 1.0 | 使用了与完整性相同的错误 `0–1` 分制指令，但 Judge 本次可能遵循 DeepEval 模板给出 10 | **已确认存在分制冲突；现有高分同样不可靠** | 高 |
| 两个 Case 的 8 个生成指标为错误 | 4 个指标在同一 Worker 中串行执行，却共享 300 秒进程总超时 | **已确认的 Eval 执行可靠性问题** | 高 |
| 一项忠实度为非法输出 | Qwen Judge 的三种结构化输出尝试均未得到合法 Schema | 属于 Judge/Adapter 边界异常；单次样本不足以判定生产 RAG 代码质量 | 中 |
| 相关性出现 0.5、0.7273、0.75 | 本次未启用 Judge 长理由，稳定报告也不保存答案正文 | 证据不足，不能归因到具体生产代码 | 高 |

### 7.2 Precision@K：分数计算正确，但通过口径需要校准

当前检索指标按照最终 rerank 的去重逻辑 Chunk 计算。相关实现位于 `src/fast_app/rag_eval/retrieval.py`：

```python
returned_count = len(ranked)
hit_count = len(matched)
scores = {
    "retrieval_recall_at_k": hit_count / len(gold),
    "retrieval_precision_at_k": (
        hit_count / min(k, returned_count) if returned_count else 0.0
    ),
    "retrieval_hit_rate_at_k": 1.0 if hit_count else 0.0,
    "retrieval_mrr": 1.0 / first_rank if first_rank is not None else 0.0,
}
```

本次 8 条普通可回答 Case 的 `top_k=5`，报告同时给出 Recall=1 或 0.5、Precision=0.2，据公式可以确定每条均返回 5 个去重结果并命中 1 个 Golden Chunk。因此 0.2 是正确算术结果，不是 Precision 实现 Bug。

问题在于所有检索指标统一使用 0.5 阈值：

```python
DEFAULT_RETRIEVAL_THRESHOLDS = {
    name: 0.5 for name in RETRIEVAL_METRIC_NAMES
}
```

当一个 Case 只标注 1 个 Golden Chunk、系统按设计返回 5 条时，即使命中该 Golden Chunk，Precision@5 的上限仍只有 0.2。除非 Golden 集合穷举了其他同样相关的 Chunk，否则“低于 0.5”不能直接等价为生产检索代码质量差。需要先明确 Precision 的目标是“严格只返回 Golden”还是“返回的其他证据也由人工判为相关”，再决定补充相关性标注、调整 K 或为 Precision 单独设置阈值。

### 7.3 MRR 和 Recall：确认结果不理想，但不能越过证据归因代码

MRR=0.25 可确定首个 Golden Chunk 排第 4；Recall=0.5 可确定两个 Golden Chunk 只命中一个。当前稳定报告只保留 Case 指标、`snapshot_id` 和 `snapshot_hash`，不包含最终 rerank ID 列表、查询改写文本或 rerank 是否走过降级路径。因此本次材料无法继续判断是：

- 混合召回没有把目标块送入候选集；
- 查询改写改变了检索重点；
- rerank 模型把目标块排低；
- 父子块逻辑身份映射影响了排名；
- Golden 相关性集合没有覆盖其他实际相关结果。

所以报告只能提出“针对两个 MRR=0.25 和两个 Recall=0.5 Case 做定向诊断”，不能把它写成某个生产函数的代码缺陷。

### 7.4 完整性和上下文利用率：已确认 GEval 分制冲突

首次运行时，`src/fast_app/rag_eval/generation_worker.py` 向两个 GEval 指标明确要求输出 `0–1` 分。以下是缺陷修复前的代码：

```python
COMPLETENESS_STEPS = [
    "逐条读取 expected output 中编号的 required key facts。",
    "判断 actual output 是否明确表达了每条事实的核心语义，不要求逐字相同。",
    "仅按覆盖比例给出 0 到 1 的分数；不要因文风、长度或额外正确信息加分。",
]

CONTEXT_UTILIZATION_STEPS = [
    # ...
    "综合有效使用与无依据内容比例给出 0 到 1 的分数。",
]
```

但本地 DeepEval 4.1.3 的 `deepeval/metrics/g_eval/utils.py` 默认原始分制是 `0–10`：

```python
def get_score_range(rubric):
    if rubric is None:
        return (0, 10)
```

随后 `deepeval/metrics/g_eval/g_eval.py` 再将原始分除以 10 归一化：

```python
self.score = (
    (float(g_score) - self.score_range[0]) / self.score_range_span
    if not self.strict_mode
    else int(g_score)
)
```

DeepEval 自带模板同时要求 Judge 返回 `0–10` 整数。于是本地步骤要求的“满分 1”可能被 DeepEval 再归一化为 0.1，恰好解释了 5 条一致的 0.1。这个冲突也影响上下文利用率：本次 Judge 可能优先遵循 DeepEval 模板而给出 10，最终得到 1.0，但不能保证每次都如此。

因此，首次运行中的所有完整性和上下文利用率原始分数都必须标记为“不可靠”，不能据此评价被测答案。当前代码已经统一为 DeepEval 的 `0–10` 原始分制，并增加了无需真实模型的分制契约测试；修复后的定向重测结果见第九章。

### 7.5 Worker 超时：四个串行指标共享一个 300 秒总预算

`src/fast_app/rag_eval/generation_worker.py` 在一个子进程内顺序等待所选生成指标：

```python
for name in request.metrics:
    # 构造对应 DeepEval metric
    await metric.a_measure(test_case)
```

父进程 `src/fast_app/rag_eval/generation.py` 对整个子进程只提供一个固定总超时：

```python
def __init__(self, *, timeout_seconds: float = 300.0, ...):
    self.timeout_seconds = timeout_seconds

stdout, stderr = await asyncio.wait_for(
    process.communicate(payload),
    timeout=self.timeout_seconds,
)
```

Faithfulness 等指标内部可能包含多次 Judge 调用。四项串行总耗时一旦超过 300 秒，父进程会杀死整个 Worker，Runner 随后把该 Case 的四项生成指标全部记为 `generation_worker_failed`。这解释了为什么两个 Case 一次产生 8 个错误项。它是 Eval 的预算粒度和失败隔离不足，不代表被测 RAG 的四项生成质量都失败。

### 7.6 当前证据边界

本次运行没有启用 `--include-judge-reason`，指标结果只保存通用的阈值比较短语；稳定报告也有意不包含完整答案、完整上下文和最终排序文档列表。因此：

- 可以从公式和分数反推出命中数、返回数及首个相关排名；
- 可以确认 GEval 分制冲突和 Worker 总超时问题；
- 不能逐事实判断答案究竟漏了什么；
- 不能仅根据现有报告定位某个召回器、查询改写器或 reranker 函数有缺陷。

修复 Eval 问题后，应使用 `--include-judge-reason` 定向重跑，并在不泄露完整上下文的前提下保留足够的逻辑 Chunk 排名诊断信息。

## 八、评测异常

| Case ID | 受影响指标 | 错误码 | 说明 |
|---|---|---|---|
| `reader_es_milvus_parent_child_expansion` | 忠实度 | `judge_invalid_output` | Judge 未返回符合 JSON Schema 的合法结构化输出 |
| `reader_webhook_worker_multi_source` | 全部 4 项生成指标 | `generation_worker_failed` | DeepEval Worker 超过 300 秒 |
| `reader_milvus_index_check` | 全部 4 项生成指标 | `generation_worker_failed` | DeepEval Worker 超过 300 秒 |

这些异常属于生成指标评判链路失败，而不是 Case 路由失败，也不能等同于对应指标得分为 0。

## 九、分制修复后的定向重测

### 9.1 重测身份

| 项目 | 结果 |
|---|---|
| 运行 ID | `ec7fbf3f-db46-43b7-bd87-ef7136709b2d` |
| 运行状态 | `completed` |
| Provider | `rag_agent` |
| 数据集哈希 | `ddd0983fbd2653fb9204fb116528bf460bec0c1109c7dff81d2ae200972da573` |
| 被测模型 | `qwen:qwen3.7-plus` |
| Judge 模型 | `qwen3.7-max` |
| 选择的指标 | 答案完整性、上下文利用率 |
| Case | 12 条，已评测 12，Case 失败 0，跳过 0 |
| 实际路由 | 12 条均为 `simple_rag -> knowledge_retrieval` |
| 总耗时 | 约 22.20 分钟 |

修复后的代码将两个 GEval 本地步骤统一为 DeepEval 的 `0–10` 原始分制：

```python
COMPLETENESS_STEPS = [
    "逐条读取 expected output 中编号的 required key facts。",
    "判断 actual output 是否明确表达了每条事实的核心语义，不要求逐字相同。",
    "仅按覆盖比例给出 0 到 10 的整数分数；不要因文风、长度或额外正确信息加分。",
]

CONTEXT_UTILIZATION_STEPS = [
    # ...
    "综合有效使用与无依据内容比例给出 0 到 10 的整数分数。",
]
```

### 9.2 重测汇总

| 指标 | 平均分 | 已评测 | 通过 | 跳过 | 错误 | 结论 |
|---|---:|---:|---:|---:|---:|---|
| 答案完整性 | 0.9444 | 9 | 9 | 3 | 0 | 9 条可回答 Case 全部达到 0.5 阈值 |
| 上下文利用率 | 0.9833 | 12 | 12 | 0 | 0 | 12 条 Case 全部达到 0.5 阈值 |

### 9.3 重测逐 Case 结果

| Case ID | 答案完整性 | 上下文利用率 | 说明 |
|---|---:|---:|---|
| `reader_es_milvus_parent_child_expansion` | 1.0000 | 1.0000 | 两项通过 |
| `reader_ue5_perfect_block` | 1.0000 | 1.0000 | 两项通过 |
| `reader_gitlab_rollback_authoritative` | 1.0000 | 1.0000 | 两项通过 |
| `reader_webhook_worker_multi_source` | 1.0000 | 1.0000 | 两项通过，未再发生 Worker 超时 |
| `reader_milvus_index_check` | 1.0000 | 1.0000 | 两项通过，未再发生 Worker 超时 |
| `reader_art_acl_negative` | 不适用 | 1.0000 | no-answer Case 没有 `required_key_facts` |
| `reader_visibility_positive` | 1.0000 | 1.0000 | 两项通过 |
| `reader_incremental_input_buffer` | 0.5000 | 0.9000 | 完整性恰好达到阈值 |
| `reader_unanswerable_audio_middleware` | 不适用 | 1.0000 | no-answer Case 没有 `required_key_facts` |
| `reader_agent_tool_acceptance_underfilled` | 1.0000 | 1.0000 | 两项通过 |
| `reader_worker_failure_recovery` | 1.0000 | 0.9000 | 两项通过 |
| `reader_no_result_backup_schedule` | 不适用 | 1.0000 | no-answer Case 没有 `required_key_facts` |

### 9.4 与首次运行的关系

首次运行的完整性均值为 0.2857，分制修复后为 0.9444；5 条旧的 0.1 在新运行中均变为 1.0。这个结果与已确认的“Judge 给出 1，却被 DeepEval 再除以 10”故障模式一致，说明旧完整性低分主要由 Eval 分制缺陷造成。

本次重测重新执行了真实 RAG，因此生成答案和上下文不是首次运行的冻结副本。新结果不能与首次运行的另外六项指标拼接成同一个原子运行报告；两份报告必须分别保留各自的 Run ID。修复后报告是两个 GEval 指标的新有效证据，首次报告仍用于保存当时的检索、忠实度和答案相关性结果。

定向重测原始报告：

- JSON：`reports/rag-eval-v211-golden-reader-geval-scale-fixed/rag-eval-rag_agent-ec7fbf3f-db46-43b7-bd87-ef7136709b2d.json`
- Markdown：`reports/rag-eval-v211-golden-reader-geval-scale-fixed/rag-eval-rag_agent-ec7fbf3f-db46-43b7-bd87-ef7136709b2d.md`

## 十、后续建议

1. 两个 GEval 指标的分制冲突已修复并完成定向重测，不再沿用首次运行中的 GEval 分数。
2. 仍需将 Worker 的 300 秒总预算改为与指标粒度匹配的超时和失败隔离；本次只选择两个指标所以未超时，不能证明四指标同跑的超时问题已经解决。
3. 定向重跑首次失败的忠实度和答案相关性指标，补齐生成层缺失结果。
4. 对 MRR=0.25 和 Recall=0.5 的 Case 保存并核对最终逻辑 Chunk 排名，再决定是否调整召回、查询改写或 rerank。
5. 明确 Precision@K 的相关性标注口径，之后再选择补全 Golden 相关块、调整 K 或设置独立阈值。
6. 所有 Judge 异常清零后，再执行一次同一 Run 内的八指标评测，形成可用于版本对比的原子稳定基线。
