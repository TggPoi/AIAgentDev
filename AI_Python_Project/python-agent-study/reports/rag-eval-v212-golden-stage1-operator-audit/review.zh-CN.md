# V2.1.2 Operator 检索结果审查报告

## 1. 审查结论

Operator 正式报告中的 `Precision@K=0.2667` 不能直接解释为系统真实检索
Precision，也不能直接归因于检索代码质量低。

本次逐条审查确认：

1. `operator_documented_art_scope_multi` 和
   `operator_global_reader_dev_positive` 存在明显的 Golden 相关性漏标。
2. `operator_pixel_sprite_rules` 的低 Precision 基本真实，主要表现为同一文档的
   相邻弱相关章节占满 Top 5。
3. art scope 的精确权威 Chunk 同时存在候选池召回和 reranker 排序问题；只扩大
   `candidate_k` 不能解决。
4. 当前代码已正确执行 `candidate_k -> RRF candidate pool -> rerank -> top_k`，
   本轮没有复现候选池提前截断 Bug。

按“只有直接回答问题的 Chunk 才算相关”的严格口径重新人工分类，三条 Case 的
Operator Precision 大约至少为：

| Case | 报告分数 | 严格复核下限 | 说明 |
|---|---:|---:|---|
| Pixel Sprite | 0.2000 | 0.2000 | 只有第 1 名是明确直接证据；第 5 名属于边界弱相关 |
| 普通 art 用户范围 | 0.2000 | 0.8000 | 第 1、2、3、5 名都直接描述可见或不可见范围 |
| 部署资料与启动命令 | 0.4000 | 0.6000 | 第 1、3、5 名直接回答“是否有资料”及两个具体主题 |

据此，三条 Case 的严格 Precision 均值下限约为 `0.5333`，而不是 `0.2667`。
如果把能够直接支持问题但没有给出完整细节的弱相关 Chunk 也计入，合理区间约为
`0.5333～0.7333`。这个区间是人工诊断结果，不是新的正式指标，必须通过新版本
Golden 固化后才能重新计算。

## 2. 证据边界

- 正式 Operator Run ID：`afc65bad-7792-439c-b662-7fd358f4129c`
- 数据集：V2.1.2 Golden
- 数据集哈希：`71bb897a278b6501067d33e6e7aff933e56d4aa3ece8567d5f3343d0bb34ec7d`
- 知识版本：6
- 权限：真实 Operator API Key，`can_read_all=true`
- 检索：Milvus `text-embedding-v4` + Elasticsearch + RRF
- 重排：DashScope `qwen3-rerank`

正式轻量报告只保存 Snapshot ID/哈希，没有保存逐阶段文档列表。因此本次使用一个
不调用 Router、答案生成和 DeepEval 的最小探针，真实执行认证、ES、Milvus、RRF、
rerank 和父块扩展。三条 Case 连续重放两次，vector、keyword、RRF 和 rerank 的逻辑
Chunk ID 与顺序全部一致；重放得到的 `0.2 / 0.2 / 0.4` Precision 和第三条
`MRR=1/3` 与正式报告完全吻合。

逐阶段证据：

- `evidence.json`：`candidate_k=10` 的三条 Operator 重放结果。
- `evidence-repeat.json`：稳定性复核。
- `art-scope-candidate50.json`：只改变 art scope 的候选池为 50。

这些文件是当前环境的诊断重放，不是正式 Run
`afc65bad-7792-439c-b662-7fd358f4129c` 的原始 Snapshot 落盘副本。

## 3. Pixel Sprite Case

问题：`角色美术规范中像素 Sprite 的制作核心原则与制作要求`

| Rerank | Chunk | 内容判断 | 分类 |
|---:|---|---|---|
| 1 | `chunk_a2a894bca15c2988` | 明确给出“清晰度优先于细节数量”和完整 Sprite 制作要求 | 直接相关、权威 |
| 2 | `chunk_15eb212207bbd84e` | 角色美术通用总结，不是 Sprite 专项要求 | 弱相关，不作为直接证据 |
| 3 | `chunk_8590007d404f6dc1` | 只说明文档适用于 Sprite，没有给出制作规则 | 背景信息 |
| 4 | `chunk_1970ee43c01da9d0` | 只有文档标题 | 无回答价值 |
| 5 | `chunk_2b46de783426d416` | 包含小尺寸可读、轮廓优先、避免噪声等通用要求 | 边界弱相关 |

结论：该 Case 的 `0.2` 在严格二元相关口径下基本成立。检索系统已经把真正证据
稳定排在第 1，但仍固定填满 5 条结果，而且全部来自同一文档。第一名 rerank 分数约
`0.986`，后续结果只有约 `0.650、0.638、0.600、0.531`，说明当前链路缺少
post-rerank 低相关过滤和同文档结果多样性控制。

这属于真实检索设计质量问题，不是 ACL 或候选池 Bug。

## 4. 普通 art 用户范围 Case

问题：`ACL 规则文档如何描述普通 art 部门用户可见和不可见的文档范围？`

| Rerank | Chunk | 内容判断 | V2.1.2 标注 |
|---:|---|---|---|
| 1 | `chunk_15eb212207bbd84e` | art 私有文档只对 art 可见，不对 development/product 可见 | 相关、权威 |
| 2 | `chunk_e66042e24778969e` | public 文档对所有认证用户可见，明确包含 art 用户 | 漏标 |
| 3 | `chunk_e46195e75a0e4c4a` | development 文档不应对 art 用户可见 | 漏标 |
| 4 | `chunk_f8a53eabbef5743c` | 通用 ACL 判断规则，主要以 development 用户为例 | 部分相关、边界项 |
| 5 | `chunk_f996084e4616344d` | public 文档应对包括 art 在内的认证用户可见 | 漏标 |

因此当前 `Precision=1/5=0.2` 主要是 Golden 漏标造成的假低分。严格计算至少应为
`4/5=0.8`。

指定权威 Chunk `chunk_9ca728a00b73727c` 的正文最精确地列出普通 art 用户：

- 可见：`art/character-art-style.md`、`public/project-overview.md`
- 不可见：`product_planning/combat-design.md`、
  `development/rag-backend-deployment.md`

但在 `candidate_k=10` 时它不在任何候选阶段。将唯一变量改为
`candidate_k=50` 后：

- vector 第 13；
- keyword 第 16；
- RRF 第 12；
- rerank 仍未进入 Top 5。

这说明存在两层真实问题：候选池 10 对该精确短 Chunk 不够；即使扩大候选池，当前
reranker 仍更偏好篇幅更长、ACL 词汇更多的概括性 Chunk。来源策略失败是真实的，
但语义 Precision 低分主要不真实。

## 5. 部署资料与启动命令 Case

问题：`知识库中是否有关于 RAG 后端部署环境变量要求与 FastAPI 本地启动命令的资料？`

| Rerank | Chunk | 内容判断 | V2.1.2 标注 |
|---:|---|---|---|
| 1 | `chunk_4fde136a1c94ccd2` | 文档目的明确列出环境变量配置和 FastAPI 启动 | 漏标 |
| 2 | `chunk_0b468b33828eaa6e` | 列出“FastAPI 启动命令是什么”等部署测试问题 | 弱相关；按“是否有资料”口径可计相关 |
| 3 | `chunk_bf5a29d90fe09980` | 给出完整环境变量要求 | 相关、权威 |
| 4 | `chunk_284aad967acb60c7` | 主要是目录结构，只提及 `.env` | 弱相关/噪声 |
| 5 | `chunk_4280ef8844cf5af5` | 给出 `uvicorn fast_app.main:app --reload` | 相关、权威 |

V2.1.2 只标注第 3、5 名，导致报告的 MRR 为 `1/3=0.3333`。但问题问的是
“是否有资料”，第 1 名已经直接回答“有，并且文档覆盖这两个主题”，所以按当前问句
语义，首个相关结果应在第 1，MRR 应为 1.0。

此外，候选阶段还存在 V2.1.2 未标注的直接证据：

- `chunk_2e05b9ea8bf32de8`：直接给出 FastAPI 启动命令，RRF 第 2，
  但被 reranker 移出 Top 5；
- `chunk_fd5026edc8062ec3`：直接列出环境配置验收项，vector 第 6、RRF 第 9，
  没有进入最终 Top 5。

所以该 Case 同时有 Golden 漏标和 reranker 证据选择问题。当前 Precision/MRR 的
主要误差来自 Golden，真实排序问题则表现为把另一份直接命令证据移出 Top 5、保留了
目录结构 Chunk。

## 6. 根因排序

### 第一：V2.1.2 Operator qrels 仍不完整

这是当前数值偏低的最大原因。两条 Case 把能够直接回答问题的 Chunk 算成了
false positive。V2.1.2 已经是不可变 Golden，不能原地修正；如要建立可信基线，必须
创建新的数据集版本并重新人工审核。

### 第二：固定 Top 5 缺少低相关过滤和多样性控制

Pixel Case 的第 2～5 名与第 1 名存在巨大 rerank 分差，却仍全部进入结果；并且五条
都来自同一文档。这会消耗最终上下文并拉低 Precision。

### 第三：reranker 偏好长篇概括性 ACL 文本

art scope 的精确短权威块在扩大候选池后仍输给多条通用 ACL 文档。当前 reranker
只判断语义相关性，不理解 Eval 中的“指定权威来源”业务规则。

### 第四：`candidate_k=10` 对高相似 ACL 语料偏小

精确 art scope Chunk 在 vector/keyword 中分别为第 13/16，默认候选池无法看到它。
但候选池扩大到 50 后仍未进入最终 Top 5，所以这只是贡献因素，不是唯一根因。

### 第五：Operator 全库权限扩大了合理候选空间

已确认 Operator 的权限范围为 `can_read_all=true`。development、public、art 和
product_planning 文档同时参与检索是正确行为，不是 ACL 泄漏；其中一些跨部门文档
恰好能够描述普通 art 用户的不可见范围，因此不能简单视为噪声。

### 附加发现：父块扩展存在部分 fallback

三条探针的最终上下文中均有部分子块没有替换成完整父块，日志表现为每个 Top 5
大约 3 个父块成功扩展、2 个保留子块 fallback。它不是本次 Precision/MRR 低分的
原因，因为四项检索指标按 rerank 子块阶段计算；但它可能影响后续生成答案的上下文
完整性，应在生成层评测前单独核对父块记录是否完整。

## 7. 当前可以确认和不能确认的结论

可以确认：

- 候选池修复在真实链路中生效；
- Operator 原报告的 `0.2667` Precision 明显低估实际语义相关性；
- Pixel Case 存在真实的冗余和低相关 Top K 问题；
- art scope 存在权威来源漏召回/漏排序问题；
- 部署 Case 存在 reranker 放弃直接证据、保留较弱证据的问题。

不能确认：

- 不能用 3 条 Case 推断整个系统的 Operator 检索质量；
- 不能在没有新 Golden 的情况下给出一个正式“修正后 Precision”；
- 不能只调大 `candidate_k` 就宣称问题解决；
- 不能把所有低分都归因于代码，也不能把所有低分都归因于数据集。

建议后续顺序是：先按不可变规则建立新的 Golden 版本，补齐本报告确认的直接相关
Chunk，并明确“直接相关”和“弱相关”的二元边界；再用同一最小探针对
post-rerank 阈值、文档多样性和候选池大小做单变量对比。完成这些后才适合修改生产
检索策略并重跑阶段一。
