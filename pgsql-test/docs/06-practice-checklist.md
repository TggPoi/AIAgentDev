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

检查项：

- [ ] 我能解释 `users.id = conversations.user_id`。
- [ ] 我能解释 `conversations.id = messages.conversation_id`。
- [ ] 我能写出两张表或三张表的 `JOIN`。
- [ ] 我知道 `ON DELETE CASCADE` 的效果。

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

检查项：

- [ ] 我知道 `<=>` 返回余弦距离。
- [ ] 我知道距离越小越相似。
- [ ] 我知道为什么代码中使用 `1 - distance` 作为相似度。
- [ ] 我知道嵌入模型和 pgvector 的职责不同。

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

检查项：

- [ ] 我能解释演示脚本写入了哪些数据。
- [ ] 我能判断哪些消息带有 embedding。
- [ ] 我能解释语义检索结果为什么按相似度排序。

## 学完后的下一步

完成以上内容后，可以继续学习：

1. 使用迁移工具管理数据库结构变更。
2. 为外键列添加普通索引，并使用 `EXPLAIN ANALYZE` 观察查询计划。
3. 使用 NestJS + TypeORM 将表映射为实体。
4. 设计分页查询。
5. 学习备份、恢复和生产环境凭据管理。

此时再阅读教程后半段的 TypeORM 内容，会更容易理解 ORM 隐藏了哪些 SQL。
