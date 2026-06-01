# 05. pgsql-test 工程拆解

完成前四章后，再阅读当前工程。这样每段代码都能映射到已经学过的概念。

## 1. 工程结构

```text
pgsql-test/
├── docker-compose.yml
├── init-scripts/
│   └── create_tables.sql
├── create_tables.sql
├── src/
│   ├── db.mjs
│   ├── users.mjs
│   ├── conversations.mjs
│   ├── messages.mjs
│   └── index.mjs
├── .env
└── docs/
```

文件职责：

| 文件 | 职责 |
| --- | --- |
| [`docker-compose.yml` L1](../docker-compose.yml#L1) | 启动 PostgreSQL 和 pgAdmin |
| [`init-scripts/create_tables.sql` L1](../init-scripts/create_tables.sql#L1) | 首次初始化数据目录时建扩展、建表和建索引 |
| [`create_tables.sql` L1](../create_tables.sql#L1) | 根目录中的脚本副本，不会被 Compose 自动执行 |
| [`src/db.mjs` L6](../src/db.mjs#L6) | 创建数据库连接池，并统一暴露 `query()` |
| [`src/users.mjs` L3](../src/users.mjs#L3) | 用户 CRUD |
| [`src/conversations.mjs` L3](../src/conversations.mjs#L3) | 会话 CRUD |
| [`src/messages.mjs` L22](../src/messages.mjs#L22) | 消息 CRUD、嵌入向量写入、语义检索 |
| [`src/index.mjs` L6](../src/index.mjs#L6) | 串联功能的演示入口 |

## 2. 启动数据库

在工程根目录执行：

```powershell
docker compose up -d
docker compose ps
```

数据库连接信息来自 Compose：

```text
主机：localhost
端口：5432
数据库：hello_pg
用户：user
密码：123456
```

对应源码：[`docker-compose.yml` L7-L12](../docker-compose.yml#L7)。

进入 `psql`：

```powershell
docker exec -it pg_vector_db psql -U user -d hello_pg
```

## 3. 初始化脚本何时执行

Compose 将目录挂载为：

```yaml
- ./init-scripts:/docker-entrypoint-initdb.d
```

对应源码：[`docker-compose.yml` L13-L15](../docker-compose.yml#L13)。

需要特别注意：`/docker-entrypoint-initdb.d` 中的 SQL 脚本只会在 PostgreSQL 数据目录为空、首次初始化数据库时自动执行。

下面的操作不会自动重新执行建表脚本：

```powershell
docker compose restart
docker compose down
docker compose up -d
```

因为工程中的 `volumes/postgres` 已经保存了数据库数据。

这是一项重要的数据库实践：脚本文件是期望状态，运行中的数据库是实际状态。修改脚本后，需要通过迁移或手动 SQL 更新现有数据库。

## 4. 检查实际数据库结构

进入 `psql` 后执行：

```text
\dx
\dt
\d users
\d conversations
\d messages
```

查看公共 schema 中的索引：

```sql
SELECT
  tablename,
  indexname,
  indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
```

查看约束：

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

约束类型常用值：

| 值 | 含义 |
| --- | --- |
| `p` | 主键约束 |
| `f` | 外键约束 |
| `c` | `CHECK` 约束 |

## 5. 同步当前数据库缺少的结构

在 2026-06-01 核对当前数据库时，三张表和两个外键已经存在，但没有看到：

- `messages.role` 的 `CHECK` 约束。
- `idx_messages_embedding` HNSW 索引。

初始化脚本中的期望定义：

- [`messages.role` 检查约束 L26](../init-scripts/create_tables.sql#L26)
- [`idx_messages_embedding` HNSW 索引 L35-L37](../init-scripts/create_tables.sql#L35)

先检查是否存在不符合角色规则的数据：

```sql
SELECT id, role
FROM messages
WHERE role NOT IN ('user', 'assistant', 'system')
   OR role IS NULL;
```

如果结果为空，再添加约束：

```sql
ALTER TABLE messages
ADD CONSTRAINT messages_role_check
CHECK (role IN ('user', 'assistant', 'system'));
```

添加 HNSW 索引：

```sql
CREATE INDEX IF NOT EXISTS idx_messages_embedding
    ON messages USING hnsw (embedding vector_cosine_ops);
```

再次执行：

```text
\d messages
```

应该能够看到约束和索引。

不要为了重放初始化脚本直接删除 `volumes/postgres`，除非你明确接受清空数据库数据。

## 6. 配置 Node.js 数据库连接

[`src/db.mjs` L6-L8](../src/db.mjs#L6) 使用：

```js
const pool = new Pool({
  connectionString: process.env.DATABASE_URL
});
```

因此 `.env` 需要包含：

```dotenv
DATABASE_URL=postgresql://user:123456@localhost:5432/hello_pg
```

连接字符串结构：

```text
postgresql://用户名:密码@主机:端口/数据库名
```

在 2026-06-01 核对当前 `.env` 时，没有发现 `DATABASE_URL`。运行 Node.js 演示前，需要补充它。

`.env` 中还需要配置语义检索使用的嵌入模型：

```dotenv
OPENAI_BASE_URL=兼容 OpenAI API 的服务地址
OPENAI_API_KEY=你的 API Key
EMBEDDING_MODEL=输出 1024 维向量的嵌入模型
```

不要将 `.env` 提交到 Git。当前 [`.gitignore` L3](../.gitignore#L3) 已忽略它。

## 7. db.mjs：连接池

[`src/db.mjs` L6-L12](../src/db.mjs#L6) 的核心代码：

```js
const pool = new Pool({
  connectionString: process.env.DATABASE_URL
});

async function query(text, params) {
  return pool.query(text, params);
}
```

连接池 `Pool` 会复用数据库连接。其他模块不需要重复创建连接，只需要导入 `query()`。

## 8. users.mjs：基础 CRUD

[`src/users.mjs` L3-L31](../src/users.mjs#L3) 最适合先读。

新增用户：

```js
const { rows } = await query(
  "INSERT INTO users (name) VALUES ($1) RETURNING *",
  [name]
);
return rows[0];
```

查询用户：

```js
const { rows } = await query(
  "SELECT * FROM users WHERE id = $1",
  [id]
);
return rows[0] ?? null;
```

删除用户：

```js
const { rowCount } = await query(
  "DELETE FROM users WHERE id = $1",
  [id]
);
return rowCount > 0;
```

对应源码：

| 操作 | 源码 |
| --- | --- |
| 新增用户 | [`createUser()` L3-L8](../src/users.mjs#L3) |
| 查询用户 | [`getUserById()` L11-L13](../src/users.mjs#L11) |
| 查询全部用户 | [`getAllUsers()` L16-L18](../src/users.mjs#L16) |
| 更新用户 | [`updateUser()` L21-L26](../src/users.mjs#L21) |
| 删除用户 | [`deleteUser()` L29-L31](../src/users.mjs#L29) |

需要理解：

- `rows` 是查询结果行。
- `rows[0]` 是第一行。
- `rowCount` 是受影响行数。
- `$1` 是参数占位符。
- `RETURNING *` 让数据库返回新增或修改后的记录。

## 9. conversations.mjs：一对多关系

[`src/conversations.mjs` L3-L8](../src/conversations.mjs#L3) 新增会话：

```js
await query(
  "INSERT INTO conversations (user_id, title) VALUES ($1, $2) RETURNING *",
  [userId, title]
);
```

查询某个用户的会话列表：

```js
await query(
  "SELECT * FROM conversations WHERE user_id = $1 ORDER BY created_at DESC",
  [userId]
);
```

对应源码：[`getConversationsByUserId()` L19-L24](../src/conversations.mjs#L19)。

这里的 `user_id` 就是外键。代码使用它实现“一个用户拥有多个会话”。

## 10. messages.mjs：普通消息和向量消息

[`src/messages.mjs` L22-L44](../src/messages.mjs#L22) 支持两种写入方式：

```js
createMessage(conversationId, role, content, withEmbedding = false)
```

当 `withEmbedding` 为 `false` 时，只保存普通字段：

```sql
INSERT INTO messages (conversation_id, role, content)
VALUES ($1, $2, $3)
```

对应源码：[`src/messages.mjs` L38-L44](../src/messages.mjs#L38)。

当 `withEmbedding` 为 `true` 时：

1. 调用嵌入模型将文本转换为向量。
2. 将向量转换为 JSON 字符串。
3. 使用 `$4::vector` 写入 PostgreSQL。

```sql
INSERT INTO messages (conversation_id, role, content, embedding)
VALUES ($1, $2, $3, $4::vector)
```

对应源码：[`src/messages.mjs` L27-L35](../src/messages.mjs#L27)。

语义搜索：

```js
searchSimilarMessages(conversationId, searchText, limit = 5)
```

对应源码：[`src/messages.mjs` L92-L103](../src/messages.mjs#L92)。

它会：

1. 将搜索文本转换为向量。
2. 只查询指定会话中带有 embedding 的消息。
3. 使用 `<=>` 计算余弦距离。
4. 按距离升序返回前几条记录。

## 11. index.mjs：演示入口

[`src/index.mjs` L6-L126](../src/index.mjs#L6) 按顺序演示：

```text
创建用户
  ↓
查询、更新用户
  ↓
创建会话
  ↓
查询、更新会话
  ↓
创建普通消息
  ↓
创建带 embedding 的消息
  ↓
执行语义搜索
```

运行：

```powershell
node src/index.mjs
```

执行前确保：

1. PostgreSQL 容器健康。
2. `.env` 已配置 `DATABASE_URL`。
3. 嵌入模型 API 配置有效。
4. 嵌入模型输出维度与 `vector(1024)` 一致。

每次运行演示都会写入新数据。学习时可以在 `psql` 或 pgAdmin 中观察表数据变化。

演示流程对应源码：

| 步骤 | 源码 |
| --- | --- |
| 用户 CRUD | [`src/index.mjs` L9-L16](../src/index.mjs#L9) |
| 会话 CRUD | [`src/index.mjs` L20-L35](../src/index.mjs#L20) |
| 普通消息 CRUD | [`src/index.mjs` L39-L62](../src/index.mjs#L39) |
| 写入带 embedding 的消息 | [`src/index.mjs` L66-L89](../src/index.mjs#L66) |
| 执行语义检索 | [`src/index.mjs` L91-L109](../src/index.mjs#L91) |

## 12. pgAdmin 状态说明

在 2026-06-01 核对时，Windows 主机访问 `http://localhost:8088/` 能得到 HTTP `200`，但 Compose 仍将 `pgadmin` 标记为 `unhealthy`。

这意味着：

- pgAdmin 页面实际可访问。
- 当前 healthcheck 的探测结果仍需要单独排查。
- `pgadmin` 的健康状态不等于 PostgreSQL 的健康状态。
- 学习 SQL 时，可以优先使用 `psql`，不必依赖 pgAdmin。

## 13. 教程后半段的 TypeORM

教程后半段使用 NestJS + TypeORM 再次实现表映射和 CRUD。

建议暂时不要立刻进入 ORM。先完成当前工程的原生 SQL 学习，因为：

1. ORM 最终仍然会生成并执行 SQL。
2. 不理解主键、外键和 JOIN 时，很难判断 ORM 配置是否正确。
3. `pgvector` 的扩展语法仍经常需要手写 SQL。

完成 [06-练习清单](./06-practice-checklist.md) 后，再学习 TypeORM 会更容易。

## 官方参考资料

- [PostgreSQL Docker Official Image README](https://github.com/docker-library/docs/blob/master/postgres/README.md)
- [node-postgres Pool](https://node-postgres.com/apis/pool)
- [pgvector README](https://github.com/pgvector/pgvector)

下一章：[06. 练习清单](./06-practice-checklist.md)
