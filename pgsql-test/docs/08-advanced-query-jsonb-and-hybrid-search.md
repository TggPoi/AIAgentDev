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

**CTE 的价值主要是提高表达能力。不要假设“写成 CTE 一定更快”；最终性能仍然要通过 `EXPLAIN ANALYZE` 验证。**



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

### 6.3 GIN 索引是什么

GIN 是 Generalized Inverted Index，通常翻译为“通用倒排索引”。

先不要被名字吓到。倒排索引的核心思想是：

```text
普通表：
  第 1 行有哪些内容？
  第 2 行有哪些内容？
  第 3 行有哪些内容？

倒排索引：
  某个内容出现在哪些行？
```

普通 B-tree 索引更适合这种问题：

```sql
WHERE tool_name = 'search_weather'
WHERE created_at > '2026-06-01'
ORDER BY created_at DESC
```

因为 B-tree 按“整列值”排序，擅长等值、范围、排序。

GIN 更适合这种问题：

```sql
WHERE arguments ? 'city'
WHERE arguments @> '{"unit": "celsius"}'::jsonb
```

因为 `jsonb` 里面不是一个简单值，而是一堆 key、value、嵌套路径。GIN 会把这些可搜索元素拆出来，建立“元素 -> 行位置”的映射。

### 6.4 用 `jsonb` 例子理解 GIN 的结构

假设表里有三行：

```text
id | arguments
---+---------------------------------------------------
1  | {"city": "Shanghai", "unit": "celsius"}
2  | {"city": "Beijing", "unit": "celsius"}
3  | {"city": "New York", "unit": "fahrenheit"}
```

GIN 索引可以粗略理解成类似下面的结构：

```text
city                 -> [1, 2, 3]
unit                 -> [1, 2, 3]
city = Shanghai      -> [1]
city = Beijing       -> [2]
city = New York      -> [3]
unit = celsius       -> [1, 2]
unit = fahrenheit    -> [3]
```

真实 PostgreSQL 内部结构比这个复杂，但初学时先抓住这个模型：

```text
不是按整条 JSON 排序
而是把 JSON 内部的 key/value 拆成索引项
每个索引项指向包含它的行
```

当你执行：

```sql
SELECT *
FROM example_tool_calls
WHERE arguments @> '{"unit": "celsius"}'::jsonb;
```

数据库可以先在 GIN 索引里找：

```text
unit = celsius -> [1, 2]
```

然后再回到表里取出第 1、2 行。

如果没有索引，数据库通常需要扫描很多行，把每一行的 `arguments` 都拿出来判断是否包含 `{"unit": "celsius"}`。

### 6.5 GIN 为什么适合 `jsonb`

`jsonb` 查询常见需求不是“整段 JSON 是否等于某个值”，而是：

- 是否存在某个 key。
- 是否包含某个 key/value。
- 是否包含某个嵌套结构。
- 数组中是否包含某个元素。

如果你还不理解“租户”是什么，先阅读 [07-知识地图中的租户字段](./07-agent-development-postgresql-roadmap.md#61-租户字段)。

例如：

```sql
-- 是否存在 city 这个 key
SELECT *
FROM example_tool_calls
WHERE arguments ? 'city';
```

```sql
-- 是否包含指定 key/value
SELECT *
FROM example_tool_calls
WHERE arguments @> '{"unit": "celsius"}'::jsonb;
```

```sql
-- 数组里是否包含某个工具标签
SELECT *
FROM example_tool_calls
WHERE arguments @> '{"tags": ["weather"]}'::jsonb;
```

这些查询都很符合 GIN 的倒排思路：

```text
先找包含某个元素的行号集合
再回表取完整行
```

### 6.6 GIN 查询不是直接返回最终结果

理解这一点很重要：GIN 索引通常帮助数据库缩小候选范围，但数据库仍然可能需要回表复查。

原因是：

- JSONB 的包含关系可能涉及嵌套结构。
- 索引项只保存适合检索的信息，不等于保存完整原始行。
- 某些操作符可能先通过索引找到候选行，再由 PostgreSQL 对候选行做精确判断。

可以用这个流程理解：

```text
SQL 条件：arguments @> '{"unit": "celsius"}'
  ↓
GIN 索引找到可能匹配的行号
  ↓
PostgreSQL 读取这些行
  ↓
再次检查 arguments 是否真的满足条件
  ↓
返回最终结果
```

所以 `EXPLAIN ANALYZE` 中你可能看到类似：

```text
Bitmap Index Scan
Bitmap Heap Scan
```

大致含义是：

| 执行节点 | 含义 |
| --- | --- |
| `Bitmap Index Scan` | 先通过索引找出匹配行的位置 |
| `Bitmap Heap Scan` | 再根据这些位置回到表里读取行 |

不需要一开始记住所有执行计划细节，但要知道：GIN 不一定让查询“一步完成”，它常常是先缩小范围。

### 6.7 `jsonb_ops` 与 `jsonb_path_ops`

创建 JSONB GIN 索引时，PostgreSQL 有不同的 operator class。可以先理解为“索引用什么规则拆解和支持查询”。

默认写法：

```sql
CREATE INDEX idx_example_tool_calls_arguments
  ON example_tool_calls
  USING GIN (arguments);
```

等价于使用默认的 `jsonb_ops`。它支持的操作更全面，例如：

- `?`：是否存在某个 key。
- `?|`：是否存在这些 key 中任意一个。
- `?&`：是否同时存在这些 key。
- `@>`：是否包含某段 JSON。
- `@?`、`@@`：JSON path 相关查询。

如果你的主要查询几乎都是 `@>` 包含查询，也可以考虑：

```sql
CREATE INDEX idx_example_tool_calls_arguments_path
  ON example_tool_calls
  USING GIN (arguments jsonb_path_ops);
```

`jsonb_path_ops` 的特点：

| 类型 | 特点 |
| --- | --- |
| `jsonb_ops` | 默认选择，支持操作符更多，索引通常更大 |
| `jsonb_path_ops` | 更偏向 `@>` 包含查询，索引通常更小，但不支持 `?` 这类 key-exists 查询 |

初学和大多数项目里，优先使用默认 `jsonb_ops`。当你已经确认业务高频查询主要是 `@>`，并且数据量变大、索引体积明显影响成本时，再评估 `jsonb_path_ops`。

### 6.8 GIN 索引的代价

GIN 索引不是免费的。它会带来几个成本：

| 成本 | 说明 |
| --- | --- |
| 磁盘空间 | 一条 JSON 可能拆出很多索引项，索引可能比你想象的大 |
| 写入变慢 | `INSERT`、`UPDATE` 时不仅要写表，还要维护 GIN 索引 |
| 更新 JSONB 成本高 | PostgreSQL 更新一行时会写入新版本，频繁改大 JSON 会增加成本 |
| 查询不一定用索引 | 小表、低选择性条件、统计信息不足时，优化器可能仍然选择顺序扫描 |

“低选择性”是指一个条件能过滤掉的数据很少。例如大多数行都有：

```json
{"unit": "celsius"}
```

那么这个查询：

```sql
WHERE arguments @> '{"unit": "celsius"}'::jsonb
```

即使有 GIN 索引，数据库也可能认为：反正大部分行都要读，不如直接扫表。

### 6.9 Agent 项目中怎么判断是否要建 GIN

适合建 GIN 的情况：

- `jsonb` 字段数据量明显增长，例如几十万行以上。
- 高频接口经常按 metadata、tool arguments、tags 过滤。
- 查询条件能过滤掉大量无关数据。
- 已经用 `EXPLAIN ANALYZE` 看到顺序扫描成为瓶颈。

不适合一开始就建 GIN 的情况：

- 表里只有几百或几千行。
- JSONB 只是用来保存响应快照，几乎不查询内部字段。
- 你总是按 `tenant_id`、`created_at`、`status` 查询，这些应该建普通列索引。
- JSONB 字段非常大，并且更新非常频繁。

Agent 开发中常见设计是：

```text
高频过滤字段：普通列 + B-tree 索引
低频、变化快、结构不固定的信息：jsonb
确实需要按 jsonb 内部字段过滤：再加 GIN 索引
```

例如：

```sql
CREATE TABLE agent_tool_calls (
  id BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  status TEXT NOT NULL,
  arguments JSONB NOT NULL,
  result JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

更合理的索引组合可能是：

```sql
-- 高频普通过滤条件
CREATE INDEX idx_agent_tool_calls_tenant_created
  ON agent_tool_calls (tenant_id, created_at DESC);

-- 高频工具名过滤
CREATE INDEX idx_agent_tool_calls_tool_name
  ON agent_tool_calls (tool_name);

-- 只有当你确实经常查 arguments 内部字段时才加
CREATE INDEX idx_agent_tool_calls_arguments_gin
  ON agent_tool_calls
  USING GIN (arguments);
```

### 6.10 哪些字段不应该藏进 JSONB

假设每次都要按租户、状态和创建时间查询。租户基础概念见 [07-知识地图中的租户字段](./07-agent-development-postgresql-roadmap.md#61-租户字段)：

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

其中 `tenant_id` 是多租户系统中的数据归属字段，基础概念见 [07-知识地图中的租户字段](./07-agent-development-postgresql-roadmap.md#61-租户字段)。

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
