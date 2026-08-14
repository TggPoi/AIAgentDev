# 评测集 V2.1.2 Golden 人工审核记录

## 1. 版本身份

- 文件：`src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.2.json`
- 状态：`golden`
- Case：15 条
- `knowledge_version`：6
- `content_sha256`：`71bb897a278b6501067d33e6e7aff933e56d4aa3ece8567d5f3343d0bb34ec7d`
- `source_revision`：`sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- 构建脚本：`.tmp/build_eval_dataset_v2_1_2.py`
- 契约测试：`scripts/tests/evaluation/test_eval_dataset_v2_1_2.py`

V2.1.1 保持不可变 Golden。V2.1.2 的全部 Case 已由 `human:TGG`
人工审核通过，可用于绑定知识版本 6 的正式评测。

## 2. 新的判定语义

V2.1.2 将三种来源身份分开：

1. `relevant_logical_chunk_ids`：与问题语义相关的完整 Chunk 集合，用于
   Recall、Precision、HitRate 和 MRR。
2. `authoritative_logical_chunk_ids` / `authoritative_logical_parent_ids`：
   必须命中的可信来源子集，单独进入来源策略判定。
3. `forbidden_logical_chunk_ids`：不得进入回答的 ACL 泄漏、过期或冲突来源；
   它可以与语义相关集合重叠，但不能与权威来源重叠。

父块扩展 Case 新增 `retrieval_relevance_unit=logical_parent`：检索公式按模型
最终收到的父块身份计算，触发子块只用于证据追溯，不再把 28 字标题块作为
唯一可计分结果。

## 3. 需要重点审核的 Case

| Case | 语义相关来源变化 | 权威/禁止来源 |
|---|---|---|
| `reader_es_milvus_parent_child_expansion` | 子块补充 `chunk_7f03...`、`chunk_3154...`；指标改按 `parent_19d...` | 权威父块 `parent_19d...` |
| `reader_gitlab_rollback_authoritative` | 语义相关全集包含权威规则和两个旧 SQL 回滚块 | 权威 `chunk_296a...`；禁止 `chunk_bb13...`、`chunk_5890...` |
| `reader_webhook_worker_multi_source` | 补充日常发布检查、合并后检查和 Webhook 配置三个直接证据 | 原两个 Golden 继续作为指定权威来源 |
| `reader_milvus_index_check` | 补充另一份直接回答 Milvus schema/ACL 检查项的清单 | 原 `chunk_4e79...` 为指定权威来源 |
| `reader_visibility_positive` | 补充两份直接描述 development 可见/不可见范围的证据 | 原两个 Golden 为指定权威来源 |
| `reader_worker_failure_recovery` | 补充部署文档中更直接的 Worker 失败处理章节 | 原 `chunk_bf7e...` 为指定权威来源 |

其余 Case 的语义标注保持 V2.1.1 内容，但仍需随整个新版本重新审核。

## 4. 冲突知识源修复预览

知识版本 6 中有两条仍可检索的旧 SQL 回滚来源：

### 4.1 `development/gitlab-agent-mr-governance.md`

- 当前 Source revision：`049c22ae7853e9318018e2e4a32ca49b71ed451d`
- 冲突 Chunk：`chunk_bb13f7442fb8745c`
- 当前章节：`### 手动回滚`
- 风险：要求直接执行 SQL 更新 `publication_version`。

建议将整个章节替换为：

```markdown
### 手动回滚

知识文档事实回滚必须通过 GitLab 为目标变更新建 Revert Commit 和 Merge Request，
由 Maintainer 审核后合并到 `main`。禁止直接修改 PostgreSQL 正式知识版本指针，
也禁止直接删除或覆盖 Elasticsearch、Milvus 中的正式记录。

MR 合并后由 Webhook 登记同步任务，独立 Worker 从新的 `main` Commit 重新生成候选
版本；只有校验全部通过后才能切换正式知识版本。回滚完成后必须核对 Source SHA、
同步任务状态、正式知识版本和 ES/Milvus 版本区间，保留完整审计链。
```

### 4.2 `development/rag-deployment-checklist.md`

- 当前 Source revision：`1ca37f12a66b447dab52667f783702c9b411a3ae`
- 冲突 Chunk：`chunk_58906be3fa1f61ce`
- 当前章节：`### 12.10 回滚机制`
- 风险：给出了直接更新 `system_config.publication_version` 的 SQL 清单。

建议将整个章节替换为：

```markdown
### 12.10 回滚机制

- [ ] 文档事实回滚通过 GitLab Revert Commit 和 MR 完成
- [ ] MR 必须由 Maintainer 审核并合并到 `main`
- [ ] 禁止直接修改 PostgreSQL 正式知识版本指针
- [ ] 禁止直接删除或覆盖 ES/Milvus 正式记录
- [ ] MR 合并后由 Webhook 只登记同步任务，独立 Worker 重新生成候选版本
- [ ] 只有 PostgreSQL Manifest、ES、Milvus 全部写入并校验通过后才切换正式版本
- [ ] 回滚后确认：
  - [ ] Source `last_synced_sha` 等于新的 GitLab `main` SHA
  - [ ] 同步任务状态为 `succeeded`
  - [ ] 正式知识版本只增加一次
  - [ ] ES/Milvus 的 ACL、`source_revision` 和版本区间一致
  - [ ] 变更事件记录操作人、时间、原因和受影响文档
```

## 5. 当前发布边界

本次没有修改 PostgreSQL、Elasticsearch、Milvus，也没有创建 GitLab 分支、Commit
或 MR。尝试从 PostgreSQL Manifest 定位后只读获取 GitLab `main`，但当前 GitLab API
不可连接，因此上述替换尚未对最新 `main` 做全文乐观并发核验。

人工审核通过且 GitLab 可用后，应通过现有文档管理 dry-run / TaskPlan 确认链路提交
MR。MR 合并并发布新知识版本后，旧 Chunk 会退役且 Source revision 会变化，届时应再
创建新的数据集版本绑定新知识版本和新 Chunk ID；不能直接用绑定知识版本 6 的
V2.1.2 对新发布版本做正式评测。

## 6. 审核清单

- [x] 确认父块 Case 应按 `parent_19d48d66c7b9141e` 计分。
- [x] 逐条确认新增语义相关 Chunk 确实直接回答对应问题。
- [x] 确认原 Golden 继续作为指定权威来源符合业务期望。
- [x] 确认两个 SQL 回滚 Chunk 同时属于“语义相关”和“禁止采用”。
- [x] 确认两份源文档的建议替换正文。
- [ ] 发布知识源修复前，GitLab 恢复后重新读取最新 `main` 并生成真实 dry-run diff。
- [x] V2.1.2 已在人工审核完成后晋升 Golden；审核前未运行正式评测。
