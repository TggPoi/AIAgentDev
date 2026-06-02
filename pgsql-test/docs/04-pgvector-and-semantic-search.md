# 04. pgvector 与语义检索

前面学习的是传统关系型查询。本章学习教程的 AI 相关部分：使用 `pgvector` 保存向量，并按语义相似度检索消息。

## 1. 向量是什么

嵌入模型可以将文本转换为一组数字：

```text
"如何查询相似消息？"
  ↓ 嵌入模型
[0.12, -0.08, 0.33, ...]
```

这组数字称为 embedding，也叫嵌入向量。

语义相近的文本，其向量通常也更接近。数据库可以比较向量距离，找出与搜索文本最接近的历史消息。

### 1.1 embedding 不是原文，也不是关键词列表

embedding 是模型根据文本内容计算出的数值表示。它不是：

- 原始文本的压缩副本。
- 人工编写的标签列表。
- 数据库自动生成的值。

例如，下面两句话没有使用完全相同的关键词，但语义接近：

```text
如何查询相似消息？
怎么检索含义接近的聊天记录？
```

嵌入模型可能将它们转换为方向接近的向量。随后 pgvector 负责比较向量距离。

### 1.2 为什么要把业务字段和向量放在同一张表

当前消息表同时保存：

```text
messages
  ├── conversation_id   属于哪个会话
  ├── role              谁发送的消息
  ├── content           原始文本
  ├── embedding         文本对应的向量
  └── created_at        创建时间
```

这样可以在一条 SQL 中同时使用普通业务条件和向量距离：

```text
只搜索某个会话
  +
只搜索已经生成 embedding 的消息
  +
按语义距离排序
```

## 2. pgvector 做了什么

PostgreSQL 本身擅长保存结构化业务数据。`pgvector` 扩展为 PostgreSQL 增加向量类型和向量距离运算符。

当前工程启用扩展：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

对应源码：[`init-scripts/create_tables.sql` L1-L2](../init-scripts/create_tables.sql#L1)。

检查扩展：

```sql
SELECT extname, extversion
FROM pg_extension
WHERE extname = 'vector';
```

当前工程的消息表包含：

```sql
embedding vector(1024)
```

对应源码：[`init-scripts/create_tables.sql` L28](../init-scripts/create_tables.sql#L28)。

这表示每个向量必须包含 `1024` 个数字。嵌入模型输出维度必须与数据库字段维度一致。

### 2.1 维度必须严格一致

`vector(1024)` 中的 `1024` 表示每条向量包含 `1024` 个分量：

```text
[数字1, 数字2, ..., 数字1024]
```

如果模型输出 `1536` 维向量，却尝试写入 `vector(1024)` 字段，数据库会拒绝写入。

因此，切换嵌入模型时不能只修改环境变量，还要确认：

1. 新模型输出多少维。
2. 数据库字段维度是否匹配。
3. 已有消息向量是否需要重新生成。
4. 查询向量和表中向量是否来自兼容的模型。

不同模型生成的向量通常不能直接混用。即使维度碰巧相同，它们也未必处于同一个向量空间中。

## 3. 先用三维向量练习

真实的 `1024` 维向量不适合手写。可以建立临时表练习三维向量：

```sql
CREATE TEMP TABLE vector_demo (
  id SERIAL PRIMARY KEY,
  content TEXT NOT NULL,
  embedding vector(3) NOT NULL
);

INSERT INTO vector_demo (content, embedding)
VALUES
  ('A', '[1,0,0]'),
  ('B', '[0.9,0.1,0]'),
  ('C', '[0,1,0]');
```

临时表只在当前数据库会话中存在。退出 `psql` 后会自动删除。

这里使用三维向量，是为了让方向容易观察：

```text
A = [1, 0, 0]
B = [0.9, 0.1, 0]
C = [0, 1, 0]
```

- `B` 与 `A` 的方向非常接近。
- `C` 与 `A` 的方向垂直。
- 因此，查询向量为 `A` 时，预期顺序是 `A`、`B`、`C`。

## 4. 理解余弦距离

查询与 `[1,0,0]` 最接近的向量：

```sql
SELECT
  id,
  content,
  embedding <=> '[1,0,0]' AS cosine_distance
FROM vector_demo
ORDER BY embedding <=> '[1,0,0]'
LIMIT 3;
```

`<=>` 表示余弦距离：

- 距离越小，越相似。
- 因此按距离升序排列。

执行后，结果大致如下：

```text
content | cosine_distance
--------+----------------------
A       | 0
B       | 0.0061...
C       | 1
```

解释：

- `A` 与自己方向完全相同，所以距离为 `0`。
- `B` 与 `A` 很接近，所以距离接近 `0`。
- `C` 与 `A` 垂直，所以余弦距离为 `1`。

为了显示更直观的相似度，可以计算：

```sql
SELECT
  id,
  content,
  1 - (embedding <=> '[1,0,0]') AS similarity
FROM vector_demo
ORDER BY embedding <=> '[1,0,0]'
LIMIT 3;
```

- 相似度越大，越相似。
- 排序时仍然直接使用距离表达式。

余弦相似度与余弦距离的关系：

```text
cosine_similarity = 1 - cosine_distance
```

示例结果：

```text
content | similarity
--------+----------------------
A       | 1
B       | 0.9938...
C       | 0
```

### 4.1 为什么 ORDER BY 使用距离，而不是别名 similarity

如果还不熟悉普通查询中的排序，先阅读 [02-SQL CRUD 与约束：`ORDER BY`](./02-sql-crud-and-constraints.md#34-order-by明确指定结果行的顺序)。本节是在此基础上解释向量检索中的特殊排序方式。

当前工程按距离升序：

```sql
ORDER BY embedding <=> $1::vector
```

因为 HNSW 索引是围绕距离运算符建立的。按照 pgvector 官方说明，最近邻查询应结合 `ORDER BY` 和 `LIMIT` 使用索引。

可以将相似度作为展示字段返回给调用者，但排序仍然保留距离表达式：

```sql
SELECT 1 - (embedding <=> $1::vector) AS similarity
...
ORDER BY embedding <=> $1::vector
LIMIT $3;
```

pgvector 还提供其他距离运算符：

| 运算符 | 含义 |
| --- | --- |
| `<->` | L2 欧氏距离 |
| `<#>` | 负内积 |
| `<=>` | 余弦距离 |

当前工程使用余弦距离。

不同距离函数适合不同模型和业务语义。不要只修改 SQL 运算符，还要同步确认索引的 operator class 是否匹配。

## 5. 当前工程中的语义检索 SQL

[`src/messages.mjs` L92-L103](../src/messages.mjs#L92) 中的核心查询是：

```sql
SELECT id, conversation_id, role, content, created_at,
       1 - (embedding <=> $1::vector) AS similarity
FROM messages
WHERE conversation_id = $2 AND embedding IS NOT NULL
ORDER BY embedding <=> $1::vector
LIMIT $3
```

逐步理解：

| 片段 | 含义 |
| --- | --- |
| `$1::vector` | 将嵌入模型生成的向量作为查询向量 |
| `conversation_id = $2` | 只搜索指定会话 |
| `embedding IS NOT NULL` | 忽略没有生成向量的消息 |
| `embedding <=> $1::vector` | 计算余弦距离 |
| `1 - (...) AS similarity` | 将距离转换为相似度 |
| `ORDER BY ...` | 最相似的消息排在前面 |
| `LIMIT $3` | 只取前几条 |

这条 SQL 将普通条件过滤和向量检索结合在了一起。

### 5.1 参数如何进入 SQL

调用：

```js
[JSON.stringify(vector), conversationId, limit]
```

对应：

| 占位符 | JavaScript 值 | 用途 |
| --- | --- | --- |
| `$1` | `JSON.stringify(vector)` | 查询向量 |
| `$2` | `conversationId` | 限定会话 |
| `$3` | `limit` | 限制返回数量 |

`$1::vector` 中的 **`::vector` 是 PostgreSQL 类型转换。**Node.js 传入的是文本形式的数组，PostgreSQL 将其转换为 pgvector 的向量类型后，再参与距离计算。

### 5.2 为什么先过滤 conversation_id

当前搜索不是从整个数据库寻找相似消息，而是在一个指定会话中搜索：

```sql
WHERE conversation_id = $2
```

这体现了 PostgreSQL 的优势：关系型过滤和向量排序可以组合在一条 SQL 中。

未来如果要实现“搜索某个用户的所有历史会话”，就需要结合 `conversations.user_id` 和 `JOIN` 扩展查询范围。

## 6. embedding 为什么允许为空

消息表定义：

```sql
embedding vector(1024)
```

没有设置 `NOT NULL`，所以它允许为空。

这是合理的设计：

- 普通聊天消息可以先写入数据库，不立即调用嵌入模型。
- 只有需要语义检索的消息才生成 embedding。
- 搜索时通过 `embedding IS NOT NULL` 排除空值。

### 6.1 文本更新后，向量也可能需要更新

如果消息内容改变：

```text
旧 content → 旧 embedding
新 content → 应重新生成新 embedding
```

否则数据库中会出现不一致：

```text
content 已经是新文本
embedding 仍然代表旧文本
```

当前 [`updateMessage()` L67-L84](../src/messages.mjs#L67) 提供 `withEmbedding` 参数：

- `withEmbedding = true` 时，同时更新文本和向量。
- `withEmbedding = false` 时，只更新文本。

如果一条消息原本带有 embedding，修改内容时应谨慎决定是否重新向量化。

## 7. HNSW 索引

初始化脚本中定义了：

```sql
CREATE INDEX IF NOT EXISTS idx_messages_embedding
    ON messages USING hnsw (embedding vector_cosine_ops);
```

对应源码：[`init-scripts/create_tables.sql` L35-L37](../init-scripts/create_tables.sql#L35)。

含义：

| 片段 | 含义 |
| --- | --- |
| `USING hnsw` | 使用 HNSW 近似最近邻索引 |
| `embedding` | 为向量列创建索引 |
| `vector_cosine_ops` | 索引用于余弦距离查询 |

按照 pgvector 官方说明：

- 没有近似索引时，默认执行精确最近邻搜索。
- HNSW 索引通过近似搜索提升速度，但会在召回率、构建时间和内存使用之间做权衡。
- HNSW 不需要训练步骤，因此表中还没有数据时也可以创建。

### 7.1 精确搜索与近似搜索

没有 HNSW 索引时，pgvector 默认执行精确最近邻搜索：

```text
比较候选向量
  ↓
得到精确排序
```

增加 HNSW 索引后，可以执行近似最近邻搜索：

```text
通过图结构快速寻找较接近的候选
  ↓
减少搜索成本
  ↓
可能牺牲少量召回率
```

“近似”表示速度和召回率之间存在权衡，并不表示结果毫无意义。数据量较小时，学习重点是理解 SQL；数据量增长后，索引才更能体现价值。

### 7.2 operator class 必须与距离运算符匹配

当前查询使用余弦距离：

```sql
embedding <=> query_vector
```

因此索引使用：

```sql
vector_cosine_ops
```

常见对应关系：

| 查询距离 | 运算符 | HNSW operator class |
| --- | --- | --- |
| L2 欧氏距离 | `<->` | `vector_l2_ops` |
| 内积 | `<#>` | `vector_ip_ops` |
| 余弦距离 | `<=>` | `vector_cosine_ops` |

如果索引为余弦距离创建，却在查询中改用 `<->`，该索引不能按预期服务这条查询。

### 7.3 【重点】NULL 向量不会进入向量索引

pgvector 官方说明中指出，`NULL` 向量不会被索引。当前查询同时显式写了：

```sql
embedding IS NOT NULL
```

这样可以清楚表达业务意图：只搜索已经完成向量化的消息。

检查索引是否存在：

```sql
SELECT indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename = 'messages';
```

如果缺少索引，可以手动执行：

```sql
CREATE INDEX IF NOT EXISTS idx_messages_embedding
    ON messages USING hnsw (embedding vector_cosine_ops);
```

## 8. 从文本到搜索结果的完整流程

```text
用户输入搜索文本
  ↓
嵌入模型生成查询向量
  ↓
Node.js 将向量作为 SQL 参数传入
  ↓
PostgreSQL 使用 <=> 比较 messages.embedding
  ↓
按余弦距离升序排列
  ↓
返回最相似的前 N 条消息
```

写入带向量消息时：

```text
消息文本
  ↓
嵌入模型生成向量
  ↓
同时写入 messages.content 和 messages.embedding
```

对应 Node.js 源码：[`src/messages.mjs` L27-L35](../src/messages.mjs#L27)。

## 9. 对照 pgvector 相关源码

| 功能 | 源码 |
| --- | --- |
| 启用 `vector` 扩展 | [`init-scripts/create_tables.sql` L2](../init-scripts/create_tables.sql#L2) |
| 定义 `embedding vector(1024)` | [`init-scripts/create_tables.sql` L28](../init-scripts/create_tables.sql#L28) |
| 创建 HNSW 索引 | [`init-scripts/create_tables.sql` L36-L37](../init-scripts/create_tables.sql#L36) |
| 配置嵌入模型 | [`src/messages.mjs` L9-L19](../src/messages.mjs#L9) |
| 写入带向量消息 | [`src/messages.mjs` L27-L35](../src/messages.mjs#L27) |
| 更新消息和向量 | [`src/messages.mjs` L67-L77](../src/messages.mjs#L67) |
| 执行语义检索 | [`src/messages.mjs` L92-L103](../src/messages.mjs#L92) |

## 10. pgvector 不等于嵌入模型

需要区分两个职责：

| 组件 | 职责 |
| --- | --- |
| 嵌入模型 | 将文本转换为向量 |
| pgvector | 在 PostgreSQL 中保存向量并计算距离 |

PostgreSQL 不会自动理解文本语义。应用程序必须先调用嵌入模型生成向量。

## 11. 当前工程需要特别注意的模型配置

初始化脚本中的注释提到 `text-embedding-v3` 和 `1024` 维向量：

[`init-scripts/create_tables.sql` L28](../init-scripts/create_tables.sql#L28)。

当前代码默认模型是：

```js
process.env.EMBEDDING_MODEL || "text-embedding-v4"
```

对应源码：[`src/messages.mjs` L12](../src/messages.mjs#L12)。

这两个名称不完全一致。实际运行时，应以 `.env` 中的 `EMBEDDING_MODEL` 和服务商文档为准，确认模型输出确实是 `1024` 维。不要仅根据模型名称推测维度。

## 12. 常见误区

| 误区 | 正确理解 |
| --- | --- |
| PostgreSQL 会自动把文本转换为向量 | 不会，Node.js 必须先调用嵌入模型 |
| embedding 是原始文本的压缩副本 | 不是，它是模型生成的数值表示 |
| 维度相同的模型一定可以混用 | 不一定，不同模型的向量空间通常不兼容 |
| 有 HNSW 索引后结果一定与精确搜索完全相同 | 不一定，HNSW 是近似最近邻索引 |
| 修改文本后可以永远不更新 embedding | 可能造成文本与向量不一致 |
| 任意距离运算符都能使用同一个 HNSW 索引 | 不行，operator class 要与距离类型匹配 |

## 官方参考资料

- [pgvector README](https://github.com/pgvector/pgvector)

## 本章练习

1. 在 `psql` 中创建 `vector_demo` 临时表。
2. 插入三个三维向量。
3. 使用 `<=>` 查询距离。
4. 使用 `1 - (...)` 查询相似度。
5. 查询当前 `messages` 表的索引。

## 完成标准

你应该能够回答：

1. embedding 和 pgvector 分别负责什么。
2. `vector(1024)` 中的 `1024` 表示什么。
3. `<=>` 的结果越大越相似，还是越小越相似。
4. 为什么 SQL 中使用 `1 - (embedding <=> query_vector)`。
5. HNSW 索引的用途是什么。
6. 为什么切换嵌入模型时需要确认维度和已有向量兼容性。
7. 文本更新后，为什么通常要考虑重新生成 embedding。
8. `<=>` 和 `vector_cosine_ops` 为什么需要匹配。

下一章：[05. pgsql-test 工程拆解](./05-pgsql-test-project.md)
