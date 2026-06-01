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

pgvector 还提供其他距离运算符：

| 运算符 | 含义 |
| --- | --- |
| `<->` | L2 欧氏距离 |
| `<#>` | 负内积 |
| `<=>` | 余弦距离 |

当前工程使用余弦距离。

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

下一章：[05. pgsql-test 工程拆解](./05-pgsql-test-project.md)
