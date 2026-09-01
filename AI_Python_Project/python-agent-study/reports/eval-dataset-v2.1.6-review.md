# RAG Eval 评测集 V2.1.6 Candidate 人工审核材料

## 1. 审核对象

- 数据集：`src/fast_app/evaluation/datasets/stage11_rag_eval_cases.v2.1.6.json`
- 构建脚本：`.tmp/build_eval_dataset_v2_1_6.py`
- 离线契约测试：`scripts/tests/evaluation/test_eval_dataset_v2_1_6.py`
- `dataset_version`：`2.1.6`
- `lifecycle`：`candidate`
- Case：16 条（Reader 13 条，Operator 3 条）
- `knowledge_version`：0
- `source_revision`：`sha256:720ba93c1fa2f14d4da554921d0cd14a3e1d130c699fd2d641449f05600e0167`
- `content_sha256`：`395a572316ae43b29b201d97ab3026726f947651fc208ae5bf9a71475f1ea773`
- 文件 SHA-256：`112ec9eab85e1a3383cec65be405199fabfaf313c2ceda3cf1d4bdedbcdaadce`
- 标注状态：16 条全部为 `pending_review`

V2.1.6 从不可变 V2.1.5 派生，没有原地修改 V2.1.5。V2.1.5 的
`content_sha256` 仍为
`5cbb639e5a032c2a6bb29fd2be53a371a50e78cc096e6dcb332ea34709d53124`，
文件 SHA-256 仍为
`57c5555cc4ad095c06317a1ff682368dbdffc68da112a8bf943ae3141b166ced`。

## 2. 为什么需要派生 V2.1.6

当前检索指标把 `relevant_logical_chunk_ids` / `relevant_logical_parent_ids`
解释为能够直接帮助回答问题的完整相关集合。Top-K 中出现一个确实相关、但未被标注
的 Chunk 时，Precision 会把它当成错误结果，Recall 的分母也会偏小。

对 V2.1.5 的问题与当前数据库正文再次逐条核对后，确认有 3 条 Case 共遗漏 4 个
直接相关子块，其中父块 Case 对应新增 2 个相关父块。V2.1.6 只修复这些遗漏：

- 不修改问题、身份、ACL、关键事实和预期路由；
- 不把补充证据升级为必须命中的权威来源；
- 不修改另外 13 条 Case 的业务语义；
- 不修改 ES、Milvus、PostgreSQL、知识文档或 Eval 生产代码。

## 3. 修正 Case

### 3.1 `reader_pdf_nne_training_runtime`

问题保持不变，仍评测 Learning Agents、训练到 ONNX/NNE 的链路以及 Runtime 选择。

新增语义相关 Chunk：

- `chunk_7c483a7b9ca5fe63`
  - 直接证据：需要自定义模型时转为 `PyTorch → ONNX → NNE`。
  - 判定：能够直接回答“自定义模型入口链”，应计入相关集合。
  - 权威性：属于补充证据，不替代训练/ONNX 主流程和 NNE Runtime 主说明。

V2.1.6 的相关子块共 6 个：

1. `chunk_fa9d79af16538c98`
2. `chunk_dfec29f8331e1bd6`
3. `chunk_c80e0436eac5de05`
4. `chunk_1aacfb4570bf0fbe`
5. `chunk_d8f7f46961b5a99e`
6. `chunk_7c483a7b9ca5fe63`

权威来源仍为前三个主证据，不变。因为相关项由 5 个增至 6 个，`top_k` 从 5 调整为
6，`candidate_k=10` 不变；否则即使系统返回的 6 个结果全部正确，Recall 的理论上限也
只能达到 5/6。

### 3.2 `reader_pdf_mover_migration`

新增语义相关 Chunk：

- `chunk_d3e9c4a77c432371`
  - 直接证据：UE 5.8 的 Mover 仍为 Experimental，CMC 仍应保留。
  - 判定：直接回答“为什么不能把 CMC 当成已经过时”，应计入相关集合。
  - 权威性：作为补充说明，不替代问题点名的 8.1 和 10.1 主证据。

V2.1.6 的相关子块共 5 个，`top_k=5` 保持不变：

1. `chunk_00499a8f184e0ffd`
2. `chunk_50f5a64967ad9d11`
3. `chunk_f67c617af929dfce`
4. `chunk_0c20779a4e397e0d`
5. `chunk_d3e9c4a77c432371`

权威来源仍是 `chunk_00499a8f184e0ffd` 和
`chunk_0c20779a4e397e0d`。

### 3.3 `reader_deployment_env_parent_expansion`

该 Case 的评分单位是 `logical_parent`。问题同时询问环境变量类别、认证密钥要求和
Elasticsearch 客户端注意事项。V2.1.5 只标注了环境变量父块，遗漏了两个直接回答
ES 客户端注意事项的父块。

V2.1.6 的相关父块：

| 逻辑父块 | 触发子块 | 章节 | 作用 |
|---|---|---|---|
| `parent_8203549515f66e1b` | `chunk_ac5579214b6a604d`、`chunk_c4c06a13c5280044` | 4. 环境变量配置 | 回答服务类别、认证密钥和 ES 客户端总注意事项 |
| `parent_1a0572e425043fdf` | `chunk_e44caff2a0b48c44` | 6. Python 依赖安装 | 明确 Docker ES 与 Python 客户端版本需要匹配，并说明异步依赖 |
| `parent_948c596391bdf5cb` | `chunk_00ecace9d8c29128` | 18.1 Elasticsearch 客户端版本不兼容 | 给出版本不兼容现象和安装匹配客户端的处理方式 |

环境变量父块 `parent_8203549515f66e1b` 仍是唯一权威来源；后两个父块只进入
语义相关集合。`top_k=5` 保持不变，3 个相关父块都可进入最终结果。

## 4. 不变边界

- 另外 13 条 Case 除候选版本身份、审计状态和说明字段外，业务字段完全不变。
- 16 条 Case 的问题、Reader/Operator 身份、ACL、预期路由和关键事实不变。
- ACL negative、no-result 和 underfilled Case 不变。
- 新增的 4 个子块只进入语义相关集合，没有进入权威集合。
- 所有 answerable Case 的评分单位相关身份数均不超过 `top_k`。
- 数据集仍绑定 `knowledge_version=0`，没有伪造可重放的正式知识版本。
- 没有运行 RAG、Embedding、Reranker、LLM 或 DeepEval。

## 5. 数据库只读核对

2026-08-29 针对最终 V2.1.6 和固定 `content_sha256` 完成了只读整体验证：

- 数据集引用 52 个唯一子块（含 1 个 forbidden）和 3 个唯一父块。
- Elasticsearch 命中 55/55：52 个子块、3 个父块，缺失 0、重复 0。
- Milvus 命中 52/52 个子块，缺失 0、重复 0；3 个父块均未错误写入 Milvus。
- 数据集与 Elasticsearch 的 `doc_id`、`source_path`、`source_revision` 差异为 0。
- Elasticsearch 与 Milvus 的正文、标题、文档身份、来源路径、来源修订、父子关系、
  Chunk 序号、版本区间和 ACL 差异为 0。
- 子块类型分布为 `chunk=28`、`markdown_child=24`；3 个父块均为
  `markdown_parent`；所有引用记录 `valid_to_version=0`。
- PostgreSQL `knowledge_publication_state.active_version=[0]`，
  `knowledge_publications` 记录数为 0。

本次核对只按逻辑 ID 精确读取存储记录，没有执行搜索召回、Embedding、Reranker、
LLM 或 DeepEval。

## 6. 可重复构建与离线验证

- 构建脚本连续执行两次，文件 SHA-256 均为
  `112ec9eab85e1a3383cec65be405199fabfaf313c2ceda3cf1d4bdedbcdaadce`。
- V2.1.6 专属契约覆盖三处 qrel 修复、权威集合不变、版本边界和相关项数量上限。
- V2.1.3 至 V2.1.6 的离线回归均不依赖 Docker 或模型调用。

## 7. 发布边界

由于 PostgreSQL 当前没有 `knowledge_version > 0` 的正式发布，V2.1.6 必须保持
`candidate/pending_review`，不能晋升 Golden，也不能作为可重放的正式评测基线。

人工审核通过后，仍需先建立正式知识发布版本。如果发布过程改变任何逻辑 ID、正文、
ACL、source revision 或父子关系，必须再次派生新数据集版本，不能原地修改 V2.1.6。

## 8. 人工审核清单

- [ ] 确认 NNE 新增 Chunk 直接回答自定义模型入口链，应计入语义相关集合。
- [ ] 确认 NNE `top_k=6` 是为保持 Recall 理论上限为 1.0。
- [ ] 确认 NNE 的 3 个权威主证据无需变化。
- [ ] 确认 Mover 新增 Chunk 直接解释 Experimental 状态和保留 CMC 的原因。
- [ ] 确认 Mover 新增 Chunk 相关但不属于点名章节的权威主证据。
- [ ] 确认部署 Case 的两个新增章节直接回答 ES 客户端注意事项。
- [ ] 确认部署 Case 应按 3 个逻辑父块计分，环境变量父块仍是唯一权威来源。
- [ ] 确认另外 13 条 Case 无需修改。
- [x] 数据库身份与跨库内容一致性验证通过。
- [x] V2.1.5 文件和内容哈希保持不变。
- [ ] 确认未获得正式知识版本前不晋升 Golden、不运行真实评测。
