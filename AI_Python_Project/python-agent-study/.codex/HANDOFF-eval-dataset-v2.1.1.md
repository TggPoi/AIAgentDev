# 交接文档：RAG 评测集 V2.1.1 修正

> 修正时间：2026-08-12。V2.1.0 保持不可变；本文件记录新的 V2.1.1 candidate。

## 1. 当前状态

- 数据集：`src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.1.json`
- lifecycle：candidate
- case 数量：15
- content_sha256：`d6fbf555a86a391a74d97ecec2f03b73c563bd2ed169fe8ae96c76592933406b`
- source_revision：`sha256:0896f1c3669b6abb9ffaa8b265e37f56b1c36f7101193d89664293e5d6604723`
- knowledge_version：6
- 构建脚本：`.tmp/build_eval_dataset_v2_1_1.py`
- 回归测试：`scripts/tests/evaluation/test_eval_dataset_v2_1.py`
- 审核材料：`reports/eval-dataset-v2.1.1-review.md`

## 2. 修正范围

修正了旧 candidate 中 2 条部分准确和 5 条必须修改的 case：真实父块扩展、真实 underfilled source filter、权威回滚来源、可隔离的 ACL 负例，以及 operator `knowledge:read:all` 身份语义。

旧 V2.1.0 数据集、构建脚本、审核材料和哈希 `f1967310...` 均保持不变，其历史试跑报告不得用于 V2.1.1。

## 3. 接手点

1. 用户人工审核 `reports/eval-dataset-v2.1.1-review.md`。
2. 审核通过后填写每条 case 的 `reviewed_by`、带时区的 `reviewed_at`、非空 `review_note`，再晋升 golden 并重算哈希。
3. 使用 `load_golden_eval_dataset()` 验证 Golden 门禁。
4. 以 reader/operator 分开执行新的 rag_agent 真实流式评测；报告必须绑定 V2.1.1 新哈希。

## 4. 禁止事项

- 禁止用 V2.1.0 旧报告宣称 V2.1.1 已验收。
- 禁止把 operator 当作普通 art 用户；该身份具有 `knowledge:read:all`。
- 禁止原地修改已提交的 V2.1.0 文件。
