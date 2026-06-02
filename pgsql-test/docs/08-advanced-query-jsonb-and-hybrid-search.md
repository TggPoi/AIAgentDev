# 08. 高级查询、JSONB 与混合检索

当前工程已经实现了基础语义检索：

```sql
SELECT id, conversation_id, role, content, created_at,
       1 - (embedding <=> $1::vector) AS similarity
FROM messages
WHERE conversation_id = $2 AND embedding IS NOT NULL
ORDER BY embedding <=> $1::vector
LIMIT $3;
```

源码见 [`src/messages.mjs` L92-L103](../src/messages.mjs#L92)。

真实 Agent 应用还需要回答更多问题：

- 如何查询每个会话最近一条消息？
- 如何避免同一个外部请求重复写入？
- 如何保存不同工具各自不同的参数？
- 如何同时使用关键词、向量和 metadata 检索知识库？
- 如何稳定地翻页，而不是随着新数据写入出现重复或遗漏？

本章补齐这些能力。

## 1. JOIN 不只两种

[03-表关系、JOIN 与事务](./03-relations-joins-and-transactions.md) 已经解释：

- `INNER JOIN`：只保留两侧成功匹配的行。
- `LEFT JOIN`：保留左侧全部行。
- `RIGHT JOIN`：保留右侧全部行。
- `FULL JOIN`：两侧未匹配行都保留。

对 Agent 业务来说，日常最常用的是：

```sql
-- 查询某个会话中的全部消息
SELECT c.id, c.title, m.id, m.role, m.content
FROM conversations AS c
JOIN messages AS m
  ON m.conversation_id = c.id
WHERE c.id = $1
ORDER BY m.created_at, m.id;
```

以及：

```sql
-- 查询所有会话，即使某个会话还没有消息
SELECT c.id, c.title, COUNT(m.id) AS message_count
FROM conversations AS c
LEFT JOIN messages AS m
  ON m.conversation_id = c.id
GROUP BY c.id, c.title
ORDER BY c.id;
```

`RIGHT JOIN` 和 `FULL JOIN` 相对少见，但数据核对、迁移检查和历史数据清理时非常有用。

## 2. 子查询：把一个查询结果交给另一个查询

子查询是嵌套在另一个 SQL 中的查询。

查询至少有一条消息的会话：

```sql
SELECT id, title
FROM conversations
WHERE id IN (
  SELECT conversation_id
  FROM messages
);
```

更常见的写法是使用 `EXISTS`：

```sql
SELECT c.id, c.title
FROM conversations AS c
WHERE EXISTS (
  SELECT 1
  FROM messages AS m
  WHERE m.conversation_id = c.id
);
```

理解 `EXISTS`：

1. 外层先处理一个会话 `c`。
2. 内层检查是否存在一条 `m.conversation_id = c.id` 的消息。
3. 只要找到一条就可以确认条件成立，不需要把全部消息取出。

查找没有消息的会话：

```sql
SELECT c.id, c.title
FROM conversations AS c
WHERE NOT EXISTS (
  SELECT 1
  FROM messages AS m
  WHERE m.conversation_id = c.id
);
```

它与 `LEFT JOIN ... WHERE m.id IS NULL` 经常可以表达同一业务含义。两种写法都应该看懂。

## 3. CTE：为复杂查询命名

CTE 是 Common Table Expression，使用 `WITH` 声明。它可以把一个复杂查询拆成多个有名字的步骤。

查询每个会话最后收到消息的时间：

```sql
WITH latest_message_time AS (
  SELECT
    conversation_id,
    MAX(created_at) AS latest_created_at
  FROM messages
  GROUP BY conversation_id
)
SELECT
  c.id,
  c.title,
  l.latest_created_at
FROM conversations AS c
LEFT JOIN latest_message_time AS l
  ON l.conversation_id = c.id
ORDER BY l.latest_created_at DESC NULLS LAST;
```

阅读顺序：

1. `latest_message_time` 先计算每个会话最后一条消息的时间。
2. 外层把这个结果与 `conversations` 连接。
3. 没有消息的会话仍然保留，所以使用 `LEFT JOIN`。

CTE 的价值主要是提高表达能力。不要假设“写成 CTE 一定更快”；最终性能仍然要通过 `EXPLAIN ANALYZE` 验证。

## 4. 窗口函数：统计时仍然保留明细行

普通聚合会把多行压缩成一行：

```sql
SELECT conversation_id, COUNT(*)
FROM messages
GROUP BY conversation_id;
```

窗口函数会计算统计值，但保留每一条消息：

```sql
SELECT
  id,
  conversation_id,
  role,
  content,
  created_at,
  ROW_NUMBER() OVER (
    PARTITION BY conversation_id
    ORDER BY created_at DESC, id DESC
  ) AS row_number
FROM messages;
```

关键词含义：

| 语法 | 作用 |
| --- | --- |
| `OVER (...)` | 表示这是窗口计算 |
| `PARTITION BY conversation_id` | 每个会话独立编号 |
| `ORDER BY created_at DESC, id DESC` | 每个会话内从新到旧排序 |
| `ROW_NUMBER()` | 为排序后的行生成 `1, 2, 3 ...` |

取出每个会话最后一条消息：

```sql
WITH ranked_messages AS (
  SELECT
    m.*,
    ROW_NUMBER() OVER (
      PARTITION BY conversation_id
      ORDER BY created_at DESC, id DESC
    ) AS row_number
  FROM messages AS m
)
SELECT *
FROM ranked_messages
WHERE row_number = 1;
```

Agent 应用常见用途：

- 获取每个会话最近一条消息。
- 获取每个知识库文档最相关的前 `N` 个切片。
- 对每个租户分别统计运行耗时排名。
- 去重时保留每组最新记录。

## 5. UPSERT：让重复请求可以安全重试

Agent 调用外部模型、工具和队列时，网络失败后通常需要重试。重试可能造成同一业务写入多次。

先创建唯一约束：

```sql
CREATE TABLE example_requests (
  id BIGSERIAL PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  response JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

然后使用：

```sql
INSERT INTO example_requests (idempotency_key, status)
VALUES ('request-20260602-001', 'running')
ON CONFLICT (idempotency_key)
DO NOTHING;
```

如果同一个 key 已经存在，第二次插入不会生成重复记录。

也可以更新现有记录：

```sql
INSERT INTO example_requests (idempotency_key, status)
VALUES ('request-20260602-001', 'running')
ON CONFLICT (idempotency_key)
DO UPDATE SET status = EXCLUDED.status;
```

`EXCLUDED.status` 表示“本次原本准备插入的新值”。

重要区别：

| 写法 | 冲突时行为 |
| --- | --- |
| `DO NOTHING` | 保留旧数据，不执行写入 |
| `DO UPDATE` | 按规则更新已有记录 |

唯一约束与 `ON CONFLICT` 应该一起设计。只靠应用先查再写：

```text
SELECT 是否存在
如果不存在，再 INSERT
```

在并发情况下仍然可能出现两个请求同时判断“不存在”，然后都尝试写入。

## 6. `jsonb`：保存半结构化 Agent 数据

PostgreSQL 有 `json` 和 `jsonb` 两种 JSON 类型。通常优先使用 `jsonb`：

- `json` 更接近原始文本保存。
- `jsonb` 会转换为便于处理的内部格式。
- `jsonb` 支持索引，适合频繁查询。

学习示例：

```sql
CREATE TABLE example_tool_calls (
  id BIGSERIAL PRIMARY KEY,
  tool_name TEXT NOT NULL,
  arguments JSONB NOT NULL,
  result JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

写入：

```sql
INSERT INTO example_tool_calls (tool_name, arguments)
VALUES (
  'search_weather',
  '{"city": "Shanghai", "unit": "celsius"}'::jsonb
);
```

### 6.1 常用 JSONB 操作符

读取一个字段：

```sql
SELECT arguments -> 'city'
FROM example_tool_calls;
```

结果仍然是 JSONB 字符串：

```text
"Shanghai"
```

读取文本值：

```sql
SELECT arguments ->> 'city'
FROM example_tool_calls;
```

结果是普通 SQL 文本：

```text
Shanghai
```

判断是否包含某个键值：

```sql
SELECT *
FROM example_tool_calls
WHERE arguments @> '{"unit": "celsius"}'::jsonb;
```

判断是否存在某个键：

```sql
SELECT *
FROM example_tool_calls
WHERE arguments ? 'city';
```

### 6.2 JSONB 索引

数据较多并且经常使用 `@>`、`?` 等操作符过滤时，可以创建 GIN 索引：

```sql
CREATE INDEX idx_example_tool_calls_arguments
  ON example_tool_calls
  USING GIN (arguments);
```

不要看到 `jsonb` 就立刻创建索引。索引会占用磁盘，也会增加写入成本。先明确真实查询，再使用 `EXPLAIN ANALYZE` 验证。

### 6.3 哪些字段不应该藏进 JSONB

假设每次都要按租户、状态和创建时间查询：

```sql
WHERE tenant_id = $1
  AND status = 'running'
ORDER BY created_at DESC
```

那么 `tenant_id`、`status`、`created_at` 应该是普通列，而不是藏在 `metadata` 中。普通列更容易：

- 添加约束。
- 创建高效索引。
- 关联其他表。
- 保持查询清晰。

## 7. 全文检索：关键词仍然有价值

向量检索擅长找到语义相近文本，但关键词检索仍然重要：

- 用户搜索准确的错误码，例如 `23505`。
- 用户搜索函数名，例如 `searchSimilarMessages`。
- 用户搜索产品编号、订单号或版本号。
- 用户要求结果必须出现某个专有名词。

PostgreSQL 内置全文检索使用：

| 类型或函数 | 作用 |
| --- | --- |
| `tsvector` | 经过处理后可搜索的文档表示 |
| `tsquery` | 搜索条件 |
| `to_tsvector(...)` | 将文本转换为可搜索文档 |
| `plainto_tsquery(...)` | 将普通输入转换为查询 |
| `@@` | 判断文档是否匹配查询 |
| `ts_rank(...)` | 计算关键词匹配排名 |

英文示例：

```sql
SELECT
  id,
  content,
  ts_rank(
    to_tsvector('english', content),
    plainto_tsquery('english', 'database transaction')
  ) AS keyword_score
FROM messages
WHERE to_tsvector('english', content)
      @@ plainto_tsquery('english', 'database transaction')
ORDER BY keyword_score DESC;
```

创建表达式 GIN 索引：

```sql
CREATE INDEX idx_messages_content_fts
  ON messages
  USING GIN (to_tsvector('english', content));
```

查询表达式必须与索引表达式保持一致。

### 7.1 中文检索需要额外评估

PostgreSQL 内置全文检索配置对英文词形处理更直接。中文通常还要考虑分词质量。你可以根据业务阶段选择：

- 使用 `simple` 配置做基础实验。
- 安装适合中文的 PostgreSQL 扩展。
- 使用外部搜索引擎处理复杂中文关键词检索。
- 保留 pgvector 语义召回，再结合应用层关键词规则。

不要因为已经有向量检索，就假设关键词检索可以完全删除。两者解决的问题不同。

## 8. 混合检索：同时考虑关键词、语义和 metadata

知识库检索通常至少有三类条件：

```text
结构化过滤：tenant_id、document_id、权限、标签、时间范围
关键词相关性：是否出现关键术语、错误码、名称
语义相关性：embedding 距离是否接近
```

结构化过滤应该尽量提前执行：

```sql
WHERE tenant_id = $1
  AND embedding IS NOT NULL
```

当前工程已经在向量检索前按会话过滤：

```sql
WHERE conversation_id = $2 AND embedding IS NOT NULL
```

源码见 [`src/messages.mjs` L97](../src/messages.mjs#L97)。

### 8.1 为什么只做向量检索可能不够

用户问：

```text
错误码 23505 是什么？
```

语义搜索可能返回“唯一约束冲突”的解释，但准确包含 `23505` 的文档通常应该优先。关键词检索可以强化这种精确匹配。

### 8.2 使用 RRF 合并两套排名

RRF 是 Reciprocal Rank Fusion。它不要求关键词分数和向量相似度具有相同数值范围，而是根据两套结果中的名次合并排序。

学习用 SQL：

```sql
WITH semantic_results AS (
  SELECT
    id,
    ROW_NUMBER() OVER (
      ORDER BY embedding <=> $1::vector
    ) AS semantic_rank
  FROM knowledge_chunks
  WHERE tenant_id = $2
    AND embedding IS NOT NULL
  ORDER BY embedding <=> $1::vector
  LIMIT 20
),
keyword_results AS (
  SELECT
    id,
    ROW_NUMBER() OVER (
      ORDER BY ts_rank(search_vector, plainto_tsquery('english', $3)) DESC
    ) AS keyword_rank
  FROM knowledge_chunks
  WHERE tenant_id = $2
    AND search_vector @@ plainto_tsquery('english', $3)
  ORDER BY ts_rank(search_vector, plainto_tsquery('english', $3)) DESC
  LIMIT 20
),
combined_results AS (
  SELECT
    COALESCE(s.id, k.id) AS id,
    s.semantic_rank,
    k.keyword_rank
  FROM semantic_results AS s
  FULL JOIN keyword_results AS k ON k.id = s.id
)
SELECT
  c.id,
  c.content,
  COALESCE(1.0 / (60 + r.semantic_rank), 0) +
  COALESCE(1.0 / (60 + r.keyword_rank), 0) AS rrf_score
FROM knowledge_chunks AS c
JOIN combined_results AS r ON r.id = c.id
ORDER BY rrf_score DESC
LIMIT 10;
```

这段 SQL 用于理解混合检索结构，不要求你现在直接加入当前工程。重点是：

1. 语义搜索和关键词搜索分别取候选集。
2. 使用窗口函数为候选结果编号。
3. 根据名次计算融合分数。
4. `combined_results` 使用 `FULL JOIN` 保留只在某一种检索中命中的记录。
5. 最后按融合分数排序。

生产实现还要根据数据规模、语言、索引和召回质量进行测试。

## 9. 分页：消息多了以后不能一次全部加载

当前工程读取一个会话的全部消息：

```sql
SELECT id, conversation_id, role, content, created_at
FROM messages
WHERE conversation_id = $1
ORDER BY created_at ASC
```

源码见 [`src/messages.mjs` L56-L64](../src/messages.mjs#L56)。

教学项目可以这样写。真实会话很长时，需要分页。

### 9.1 OFFSET 分页

```sql
SELECT id, conversation_id, role, content, created_at
FROM messages
WHERE conversation_id = $1
ORDER BY created_at DESC, id DESC
LIMIT 20 OFFSET 40;
```

优点：容易理解，可以直接跳到某一页。

缺点：

- 偏移量很大时，数据库仍要跳过大量记录。
- 翻页过程中有新数据写入时，可能重复或遗漏记录。

### 9.2 游标分页

第一批：

```sql
SELECT id, conversation_id, role, content, created_at
FROM messages
WHERE conversation_id = $1
ORDER BY created_at DESC, id DESC
LIMIT 20;
```

下一批：

```sql
SELECT id, conversation_id, role, content, created_at
FROM messages
WHERE conversation_id = $1
  AND (created_at, id) < ($2, $3)
ORDER BY created_at DESC, id DESC
LIMIT 20;
```

把上一页最后一条记录的 `(created_at, id)` 作为下一页游标。

对应索引：

```sql
CREATE INDEX idx_messages_conversation_created_id
  ON messages (conversation_id, created_at DESC, id DESC);
```

为什么同时使用 `created_at` 和 `id`：

- 多条消息可能具有相同时间。
- `id` 提供稳定的第二排序条件。
- 排序条件和游标条件必须保持一致。

## 10. 参数化查询仍然是底线

不要把用户输入直接拼进 SQL：

```js
// 错误示例
const sql = `SELECT * FROM messages WHERE content = '${userInput}'`;
```

当前工程使用占位符：

```sql
WHERE conversation_id = $2
LIMIT $3
```

并通过参数数组传值：

```js
[JSON.stringify(vector), conversationId, limit]
```

源码见 [`src/messages.mjs` L94-L102](../src/messages.mjs#L94)。

参数化查询既降低 SQL 注入风险，也让 SQL 与数据边界更清晰。

## 11. 本章练习

### 练习 1：每个会话最后一条消息

1. 先用窗口函数为每个会话内的消息编号。
2. 再用 CTE 只保留 `row_number = 1`。
3. 解释为什么排序中最好同时使用 `created_at` 和 `id`。

### 练习 2：安全重试写入

1. 创建 `example_requests` 表。
2. 连续两次插入相同 `idempotency_key`。
3. 对比没有 `ON CONFLICT` 与使用 `DO NOTHING` 时的行为。
4. 练习结束后删除学习表。

### 练习 3：JSONB 查询

1. 创建 `example_tool_calls` 表。
2. 写入至少三种不同工具参数。
3. 使用 `->>` 查询城市。
4. 使用 `@>` 过滤参数。
5. 创建 GIN 索引，并记录为什么小数据量下不一定看到性能变化。

### 练习 4：设计知识库查询

不必立刻实现，先写出查询条件：

```text
tenant_id 必须匹配
document_id 可选
metadata 标签可选
embedding 不能为空
关键词召回前 20 条
语义召回前 20 条
最终合并前 10 条
```

然后解释每个条件解决的业务问题。

## 12. 完成标准

- [ ] 我能解释子查询、CTE 和窗口函数各自解决什么问题。
- [ ] 我能使用 `ON CONFLICT` 设计幂等写入。
- [ ] 我知道什么字段适合使用 `jsonb`，什么字段应该使用普通列。
- [ ] 我知道 GIN 索引适合哪些 JSONB 和全文检索操作。
- [ ] 我能解释关键词检索与向量检索为什么需要共存。
- [ ] 我能解释游标分页相比 OFFSET 分页的优点。
- [ ] 我能写出带结构化过滤的向量检索 SQL。

## 官方参考资料

- [PostgreSQL 16 Queries](https://www.postgresql.org/docs/16/queries.html)
- [PostgreSQL 16 WITH Queries](https://www.postgresql.org/docs/16/queries-with.html)
- [PostgreSQL 16 Window Functions Tutorial](https://www.postgresql.org/docs/16/tutorial-window.html)
- [PostgreSQL 16 INSERT and ON CONFLICT](https://www.postgresql.org/docs/16/sql-insert.html)
- [PostgreSQL 16 JSON Types](https://www.postgresql.org/docs/16/datatype-json.html)
- [PostgreSQL 16 JSON Functions and Operators](https://www.postgresql.org/docs/16/functions-json.html)
- [PostgreSQL 16 Full Text Search](https://www.postgresql.org/docs/16/textsearch.html)
- [PostgreSQL 16 Preferred Text Search Index Types](https://www.postgresql.org/docs/16/textsearch-indexes.html)
- [pgvector README](https://github.com/pgvector/pgvector)
