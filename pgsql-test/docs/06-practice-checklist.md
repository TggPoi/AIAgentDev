# 06. 练习清单

不要一次性执行全部内容。每完成一个阶段，再进入下一阶段。

## 阶段 1：进入数据库

目标：确认能够独立连接 PostgreSQL。

练习前可先查看：

- [`docker-compose.yml` 中的 PostgreSQL 服务 L3-L20](../docker-compose.yml#L3)
- [`docker-compose.yml` 中的数据库账号和端口 L7-L12](../docker-compose.yml#L7)

在 PowerShell 中执行：

```powershell
docker compose up -d
docker compose ps
docker exec -it pg_vector_db psql -U user -d hello_pg
```

在 `psql` 中执行：

```sql
SELECT current_database();
SELECT current_schema();
SELECT version();
```

再执行：

```text
\dt
\dx
\q
```

检查项：

- [ ] 我知道 `hello_pg` 是数据库名。
- [ ] 我知道 `pg_vector_db` 是容器名。
- [ ] 我能进入和退出 `psql`。
- [ ] 我能查看表和扩展。

## 阶段 2：完成 users CRUD

目标：熟悉最基础的增删改查。

练习前可先查看：

- [`users` 表结构 L5-L9](../init-scripts/create_tables.sql#L5)
- [`src/users.mjs` 中的用户 CRUD L3-L31](../src/users.mjs#L3)

```sql
BEGIN;

INSERT INTO users (name)
VALUES ('练习用户')
RETURNING *;

SELECT *
FROM users
WHERE name = '练习用户';

UPDATE users
SET name = '练习用户-已修改'
WHERE name = '练习用户'
RETURNING *;

DELETE FROM users
WHERE name = '练习用户-已修改'
RETURNING *;

ROLLBACK;
```

检查项：

- [ ] 我能区分 `INSERT`、`SELECT`、`UPDATE`、`DELETE`。
- [ ] 我知道 `RETURNING *` 的用途。
- [ ] 我知道修改和删除前需要检查 `WHERE`。
- [ ] 我知道 `ROLLBACK` 会撤销尚未提交的操作。

追加观察实验：

```sql
BEGIN;

INSERT INTO users (name)
VALUES ('默认值练习')
RETURNING id, name, created_at;

ROLLBACK;
```

观察：

- [ ] 我没有手动填写 `id`，但数据库自动生成了主键。
- [ ] 我没有手动填写 `created_at`，但数据库使用了默认时间。

空值判断实验：

```sql
SELECT *
FROM conversations
WHERE title IS NULL;
```

说明：判断 `NULL` 应使用 `IS NULL`，不要写 `title = NULL`。

排序实验：

```sql
BEGIN;

INSERT INTO users (name)
VALUES
  ('排序练习-B'),
  ('排序练习-A'),
  ('排序练习-A');

SELECT id, name, created_at
FROM users
WHERE name LIKE '排序练习-%'
ORDER BY name ASC, id DESC;

ROLLBACK;
```

观察：

- [ ] 我知道不写 `ORDER BY` 时，数据库不保证结果顺序。
- [ ] 我能解释 `name ASC` 为什么让 `排序练习-A` 排在 `排序练习-B` 前面。
- [ ] 我能解释两个名称相同的用户为什么继续按照 `id DESC` 排序。
- [ ] 我知道省略排序方向时默认使用 `ASC`。

`NULL` 排序实验：

```sql
SELECT id, title
FROM conversations
ORDER BY title ASC NULLS LAST, id ASC;
```

观察：

- [ ] 我知道 `NULLS LAST` 会将标题为空的会话放在最后。
- [ ] 我知道 `ORDER BY title ASC, id ASC` 中的 `id` 提供稳定的第二排序条件。

分页排序实验：

```sql
SELECT id, name, created_at
FROM users
ORDER BY created_at DESC, id DESC
LIMIT 3
OFFSET 0;
```

观察：

- [ ] 我知道 `LIMIT 3` 表示最多返回三行。
- [ ] 我知道分页时为什么不能省略 `ORDER BY`。
- [ ] 我知道第一排序字段可能重复时，应该追加主键作为排序条件。

## 阶段 3：完成三张表关联练习

目标：理解主键、外键和一对多关系。

练习前可先查看：

- [`conversations` 表和用户外键 L12-L20](../init-scripts/create_tables.sql#L12)
- [`messages` 表和会话外键 L23-L33](../init-scripts/create_tables.sql#L23)
- [`getConversationsByUserId()` L19-L24](../src/conversations.mjs#L19)
- [`getMessagesByConversationId()` L56-L64](../src/messages.mjs#L56)

```sql
BEGIN;

INSERT INTO users (name)
VALUES ('关联练习用户')
RETURNING id;
```

记下返回的用户 `id`，下面用 `<用户ID>` 表示：

```sql
INSERT INTO conversations (user_id, title)
VALUES (<用户ID>, '关联查询练习')
RETURNING id;
```

记下返回的会话 `id`，下面用 `<会话ID>` 表示：

```sql
INSERT INTO messages (conversation_id, role, content)
VALUES
  (<会话ID>, 'user', '什么是外键？'),
  (<会话ID>, 'assistant', '外键用于维护表之间的引用关系。');
```

关联查询：

```sql
SELECT
  u.name,
  c.title,
  m.role,
  m.content
FROM users AS u
JOIN conversations AS c
  ON c.user_id = u.id
JOIN messages AS m
  ON m.conversation_id = c.id
WHERE u.id = <用户ID>
ORDER BY m.created_at ASC;
```

验证级联删除：

```sql
DELETE FROM users
WHERE id = <用户ID>;

SELECT * FROM conversations
WHERE user_id = <用户ID>;

SELECT * FROM messages
WHERE conversation_id = <会话ID>;

ROLLBACK;
```

### 对比 INNER JOIN 与 LEFT JOIN

重新开始一组不会永久保留的实验：

```sql
BEGIN;

INSERT INTO users (name)
VALUES
  ('有会话用户'),
  ('无会话用户');

INSERT INTO conversations (user_id, title)
SELECT id, 'JOIN 对比练习'
FROM users
WHERE name = '有会话用户';
```

执行 `INNER JOIN`：

```sql
SELECT
  u.name,
  c.title
FROM users AS u
INNER JOIN conversations AS c
  ON c.user_id = u.id
WHERE u.name IN ('有会话用户', '无会话用户')
ORDER BY u.name;
```

预期：

```text
只有“有会话用户”
```

执行 `LEFT JOIN`：

```sql
SELECT
  u.name,
  c.title
FROM users AS u
LEFT JOIN conversations AS c
  ON c.user_id = u.id
WHERE u.name IN ('有会话用户', '无会话用户')
ORDER BY u.name;
```

预期：

```text
有会话用户 | JOIN 对比练习
无会话用户 | NULL
```

统计每位用户的会话数量：

```sql
SELECT
  u.name,
  COUNT(c.id) AS conversation_count
FROM users AS u
LEFT JOIN conversations AS c
  ON c.user_id = u.id
WHERE u.name IN ('有会话用户', '无会话用户')
GROUP BY u.id, u.name
ORDER BY u.name;
```

结束实验：

```sql
ROLLBACK;
```

检查项：

- [ ] 我能解释 `users.id = conversations.user_id`。
- [ ] 我能解释 `conversations.id = messages.conversation_id`。
- [ ] 我能写出两张表或三张表的 `JOIN`。
- [ ] 我知道 `ON DELETE CASCADE` 的效果。
- [ ] 我能解释为什么 `INNER JOIN` 不返回“无会话用户”。
- [ ] 我能解释为什么 `LEFT JOIN` 为“无会话用户”补充了 `NULL`。
- [ ] 我知道统计右表记录数量时为什么使用 `COUNT(c.id)`。
- [ ] 我能解释 `GROUP BY u.id, u.name` 如何将 JOIN 结果按用户分组。
- [ ] 我能区分 `WHERE` 过滤明细行和 `HAVING` 过滤分组结果。
- [ ] 我能区分 `GROUP BY`、`ORDER BY` 和 `DISTINCT`。

## 阶段 4：完成向量检索练习

目标：不依赖 API，先理解 pgvector SQL。

练习前可先查看：

- [`vector` 扩展 L1-L2](../init-scripts/create_tables.sql#L1)
- [`embedding vector(1024)` L28](../init-scripts/create_tables.sql#L28)
- [语义检索 SQL L92-L103](../src/messages.mjs#L92)

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

SELECT
  content,
  embedding <=> '[1,0,0]' AS cosine_distance,
  1 - (embedding <=> '[1,0,0]') AS similarity
FROM vector_demo
ORDER BY embedding <=> '[1,0,0]';
```

预期排序：

```text
A 最相似
B 次之
C 最不相似
```

原因：

- `A = [1,0,0]` 与查询向量完全相同。
- `B = [0.9,0.1,0]` 与查询向量方向接近。
- `C = [0,1,0]` 与查询向量方向垂直。

检查项：

- [ ] 我知道 `<=>` 返回余弦距离。
- [ ] 我知道距离越小越相似。
- [ ] 我知道为什么代码中使用 `1 - distance` 作为相似度。
- [ ] 我知道嵌入模型和 pgvector 的职责不同。
- [ ] 我知道 `vector(1024)` 要求模型输出维度严格匹配。
- [ ] 我知道修改文本后可能需要重新生成 embedding。
- [ ] 我知道 `<=>` 对应 `vector_cosine_ops`。

## 阶段 5：核对工程数据库结构

目标：建立“脚本不等于实际数据库”的意识。

练习前可先查看：

- [初始化脚本完整内容](../init-scripts/create_tables.sql#L1)
- [HNSW 索引定义 L35-L37](../init-scripts/create_tables.sql#L35)
- [初始化脚本挂载配置 L13-L15](../docker-compose.yml#L13)

```sql
SELECT
  tablename,
  indexname,
  indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
```

```sql
SELECT
  conrelid::regclass AS table_name,
  conname,
  contype,
  pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace
ORDER BY conrelid::regclass::text, conname;
```

检查项：

- [ ] 我能查看实际索引。
- [ ] 我能查看实际约束。
- [ ] 我知道修改 `init-scripts/create_tables.sql` 后，已有数据库不会自动同步。
- [ ] 我不会随意删除 `volumes/postgres`。
- [ ] 我能解释为什么修改初始化脚本不会自动改变已有数据库。
- [ ] 我知道另一个使用 `synchronize: true` 的 TypeORM 工程也可能修改共享数据库结构。

## 阶段 6：阅读 Node.js CRUD

目标：将 SQL 映射到代码。

按顺序阅读：

1. [`src/db.mjs` L6-L12](../src/db.mjs#L6)
2. [`src/users.mjs` L3-L31](../src/users.mjs#L3)
3. [`src/conversations.mjs` L3-L47](../src/conversations.mjs#L3)
4. [`src/messages.mjs` L22-L103](../src/messages.mjs#L22)
5. [`src/index.mjs` L6-L126](../src/index.mjs#L6)

重点源码入口：

| 知识点 | 源码 |
| --- | --- |
| 创建连接池 | [`src/db.mjs` L6-L8](../src/db.mjs#L6) |
| 统一执行 SQL | [`src/db.mjs` L10-L12](../src/db.mjs#L10) |
| 新增用户 | [`src/users.mjs` L3-L8](../src/users.mjs#L3) |
| 新增会话 | [`src/conversations.mjs` L3-L8](../src/conversations.mjs#L3) |
| 写入普通消息 | [`src/messages.mjs` L38-L44](../src/messages.mjs#L38) |
| 写入向量消息 | [`src/messages.mjs` L27-L35](../src/messages.mjs#L27) |
| 语义检索 | [`src/messages.mjs` L92-L103](../src/messages.mjs#L92) |

检查项：

- [ ] 我知道 `Pool` 的作用。
- [ ] 我知道 `$1`、`$2` 是 SQL 参数占位符。
- [ ] 我知道 `rows[0]` 和 `rowCount` 分别是什么。
- [ ] 我能找到普通消息写入 SQL。
- [ ] 我能找到向量消息写入 SQL。
- [ ] 我能找到语义检索 SQL。
- [ ] 我能画出 `index.mjs → users.mjs → db.mjs → pool.query() → PostgreSQL` 调用链。
- [ ] 我知道 `rows[0] ?? null` 表示查询不到时返回 `null`。
- [ ] 我知道 `rowCount > 0` 为什么可以转换为删除成功与否。

## 阶段 7：运行 Node.js 演示

目标：串联数据库、代码和嵌入模型。

演示入口：[`src/index.mjs` L6-L126](../src/index.mjs#L6)。

确认 `.env` 中存在：

```dotenv
DATABASE_URL=postgresql://user:123456@localhost:5432/hello_pg
```

并确保嵌入模型配置有效，然后执行：

```powershell
node src/index.mjs
```

运行后进入 `psql` 查看数据：

```sql
SELECT * FROM users ORDER BY id DESC LIMIT 5;

SELECT * FROM conversations ORDER BY id DESC LIMIT 5;

SELECT
  id,
  conversation_id,
  role,
  content,
  embedding IS NOT NULL AS has_embedding
FROM messages
ORDER BY id DESC
LIMIT 10;
```

注意：每次执行 `node src/index.mjs` 都会新增演示数据。重复运行后看到 ID 增长和多组数据是正常现象。

检查项：

- [ ] 我能解释演示脚本写入了哪些数据。
- [ ] 我能判断哪些消息带有 embedding。
- [ ] 我能解释语义检索结果为什么按相似度排序。
- [ ] 我知道一次性脚本结束时为什么调用 `pool.end()`。

## 阶段 8：从示例工程扩展到 Agent 开发

目标：不再局限于当前三张表，开始掌握 Agent 服务需要的 PostgreSQL 能力。

先阅读：

1. [07-Agent 开发所需的 PostgreSQL 知识地图](./07-agent-development-postgresql-roadmap.md)
2. [08-高级查询、JSONB 与混合检索](./08-advanced-query-jsonb-and-hybrid-search.md)
3. [09-并发、性能与生产运维](./09-concurrency-performance-and-operations.md)

按顺序完成练习：

1. 使用 `RIGHT JOIN` 重写一个已有 `LEFT JOIN`，验证结果相同。
2. 使用 `FULL JOIN` 解释如何核对两份来源不同的数据。
3. 使用 CTE 和窗口函数查询每个会话最近一条消息。
4. 创建临时学习表，练习 `jsonb` 的 `->>`、`@>` 和 GIN 索引。
5. 使用 `INSERT ... ON CONFLICT` 模拟幂等写入。
6. 为 `messages.conversation_id` 创建普通索引，并使用 `EXPLAIN ANALYZE` 对比查询计划。
7. 使用两个 `psql` 窗口练习 `FOR UPDATE SKIP LOCKED`。
8. 使用 `pg_dump` 备份数据库，再恢复到新的练习数据库中验证。

检查项：

- [ ] 我能列出 Agent 数据库中除了消息以外还需要保存哪些实体。
- [ ] 我能解释普通列与 `jsonb` 的边界。
- [ ] 我能解释关键词检索和向量检索为什么需要组合。
- [ ] 我能解释幂等键解决什么问题。
- [ ] 我能解释事务为什么必须复用同一数据库连接。
- [ ] 我能解释为什么外部模型调用不应该占用长事务。
- [ ] 我能使用 `EXPLAIN ANALYZE` 开始验证索引效果。
- [ ] 我知道初始化脚本不能替代 migration。
- [ ] 我已经理解备份与恢复验证必须一起完成。

## 学完后的下一步

完成以上内容后，可以继续学习：

1. 根据 [07-Agent 开发所需的 PostgreSQL 知识地图](./07-agent-development-postgresql-roadmap.md) 选择一个 Agent 场景，设计 `agent_runs`、`tool_calls` 或知识库切片表。
2. 使用 migration 管理新增表和索引，不再依赖重新初始化数据目录。
3. 使用 NestJS + TypeORM 将表映射为实体，并观察 ORM 最终执行的 SQL。
4. 为多租户、任务队列或知识库检索编写集成测试。
5. 数据量增长后，再按实际瓶颈评估分区、RLS、读副本和专用队列。

此时再阅读教程后半段的 TypeORM 内容，会更容易理解 ORM 隐藏了哪些 SQL。
