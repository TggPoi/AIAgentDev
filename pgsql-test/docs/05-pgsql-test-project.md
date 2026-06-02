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

### 1.1 建议的阅读顺序

不要从最长的 [`src/index.mjs`](../src/index.mjs#L6) 开始逐行阅读。建议按照依赖关系阅读：

```text
init-scripts/create_tables.sql
  ↓ 先知道数据库有哪些表
src/db.mjs
  ↓ 再知道代码如何连接数据库
src/users.mjs
  ↓ 先看最简单的单表 CRUD
src/conversations.mjs
  ↓ 再看外键关联
src/messages.mjs
  ↓ 最后看 embedding 和语义搜索
src/index.mjs
  ↓ 把所有模块串起来
```

这样每次只增加一个新概念。

### 1.2 根目录脚本与 init-scripts 脚本的区别

工程中有两个同名脚本：

```text
create_tables.sql
init-scripts/create_tables.sql
```

真正被 Docker 自动挂载的是：

[`init-scripts/create_tables.sql`](../init-scripts/create_tables.sql#L1)

因为 Compose 配置指向：

[`docker-compose.yml` L15](../docker-compose.yml#L15)

根目录中的 [`create_tables.sql`](../create_tables.sql#L1) 只是副本。修改根目录副本不会自动改变容器初始化行为。

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

### 3.1 为什么只在首次初始化时执行

如果 PostgreSQL 每次启动都自动重放所有初始化脚本，会有风险：

- 重复插入初始化数据。
- 重复执行结构变更。
- 在已有数据上执行不兼容修改。
- 难以判断数据库经历过哪些版本升级。

因此，初始化脚本适合创建一个全新的本地数据库。已经运行过的数据库应通过 migration 迁移脚本逐步升级。

### 3.2 文件、数据目录和实际数据库是三件事

```text
init-scripts/create_tables.sql
  ↓ 首次初始化时执行
volumes/postgres
  ↓ 保存 PostgreSQL 数据文件
运行中的 hello_pg
  ↓ 当前实际数据库结构
```

修改第一个文件，不会自动修改第三个状态。只要 `volumes/postgres` 仍然存在，PostgreSQL 就会继续使用已有数据目录。

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

在 2026-06-02 重新核对当前数据库时，三张表和两个外键已经存在，但没有看到：

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

### 5.1 为什么先检查现有数据再添加约束

新增约束时，数据库会检查已有数据是否符合规则。

如果已经存在：

```text
role = manager
```

再添加：

```sql
CHECK (role IN ('user', 'assistant', 'system'))
```

数据库会拒绝添加约束。正确流程是：

```text
查询不符合规则的数据
  ↓
确认结果为空，或先修复脏数据
  ↓
添加约束
```

### 5.2 另一个工程也可能修改共享数据库

教程后半部分的 `typeorm-pg-crud` 工程连接同一个 `hello_pg` 数据库，并配置了：

```ts
synchronize: true
```

这意味着启动 TypeORM 工程时，它可能根据 Entity 自动修改共享数据库结构。学习环境中可以观察这种行为，但不要把 `synchronize: true` 当作正式数据库迁移方案。

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

在 2026-06-02 重新核对当前 `.env` 时，已经存在 `DATABASE_URL`。如果以后移动数据库、修改端口或更换密码，需要同步更新该变量。

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

### 7.1 为什么使用连接池

数据库连接的建立和关闭有成本。如果每条 SQL 都重新连接一次：

```text
建立连接
  ↓
执行一条 SQL
  ↓
关闭连接
  ↓
下一条 SQL 再重新建立连接
```

会增加开销。

连接池维护一组可复用连接：

```text
应用启动
  ↓
Pool 管理若干数据库连接
  ↓
query() 借用可用连接执行 SQL
  ↓
连接回到池中，供下一次查询复用
```

### 7.2 query(text, params) 做了什么

统一封装：

```js
async function query(text, params) {
  return pool.query(text, params);
}
```

参数：

| 参数 | 含义 |
| --- | --- |
| `text` | SQL 文本，例如 `SELECT * FROM users WHERE id = $1` |
| `params` | 参数数组，例如 `[id]` |

返回值来自 node-postgres。当前代码主要使用：

| 字段 | 含义 |
| --- | --- |
| `rows` | 查询返回的行数组 |
| `rowCount` | 受 SQL 影响或返回的行数 |

### 7.3 Pool.query 的事务边界

当前模块中的普通 CRUD 每次只执行一条独立 SQL，因此使用 `pool.query()` 很方便。

如果未来要实现多条 SQL 的事务，不能将每一步随意交给 `pool.query()`，因为事务中的 SQL 必须在同一个数据库连接上执行。常见流程是：

```text
从 Pool 获取一个 client
  ↓
client.query('BEGIN')
  ↓
使用同一个 client 执行全部 SQL
  ↓
client.query('COMMIT') 或 client.query('ROLLBACK')
  ↓
释放 client
```

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

### 8.1 async 和 await 的作用

数据库查询需要等待 PostgreSQL 返回结果，因此函数使用：

```js
async function createUser(name) {
  const { rows } = await query(...);
  return rows[0];
}
```

- `async` 表示函数会返回 Promise。
- `await` 表示等待数据库查询完成，再继续执行后面的代码。
- `const { rows } = ...` 是 JavaScript 解构，只取查询结果对象中的 `rows` 字段。

### 8.2 为什么查询单行时返回 rows[0] ?? null

```js
return rows[0] ?? null;
```

含义：

```text
查询到用户
  ↓
返回第一行对象

没有查询到用户
  ↓
rows[0] 是 undefined
  ↓
返回 null
```

调用者可以明确区分“找到一个用户”和“没有找到用户”。

### 8.3 为什么删除返回布尔值

```js
return rowCount > 0;
```

含义：

- 删除到至少一行，返回 `true`。
- 没有符合条件的行，返回 `false`。

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

### 9.1 代码没有自动加载用户对象

当前原生 SQL 模块只查询：

```sql
SELECT *
FROM conversations
WHERE user_id = $1
```

返回的是 `conversations` 表中的列，不会自动附带 `users.name`。

如果需要用户名，应显式编写 `JOIN`。这是理解后续 TypeORM `relations` 功能的基础：ORM 可以帮你生成关联 SQL，但数据库底层仍然在执行 JOIN。

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

### 10.1 createMessage 的分支流程

函数签名：

```js
createMessage(conversationId, role, content, withEmbedding = false)
```

可以按下面的流程阅读：

```text
检查 role 是否有效
  ↓
withEmbedding 是否为 true？
  ├── 否：只插入 conversation_id、role、content
  └── 是：
        调用嵌入模型
        ↓
        得到 vector
        ↓
        同时插入 embedding
```

角色校验对应源码：[`src/messages.mjs` L23-L25](../src/messages.mjs#L23)。

### 10.2 getEmbeddings 为什么延迟创建

[`getEmbeddings()` L9-L19](../src/messages.mjs#L9) 只在第一次需要向量时创建客户端。

好处：

- 普通 CRUD 不需要立即初始化嵌入模型客户端。
- 没有执行向量操作时，不会调用嵌入 API。
- 后续调用可以复用同一个客户端对象。

### 10.3 文本更新与 embedding 一致性

[`updateMessage()` L67-L84](../src/messages.mjs#L67) 同样接收 `withEmbedding`。

如果一条消息原本带有 embedding，修改文本时却传入 `false`，就可能出现：

```text
content 是新文本
embedding 仍然代表旧文本
```

真实业务中，需要明确策略：

- 修改文本时同步重新生成 embedding。
- 或将旧 embedding 清空，等待异步任务重新生成。

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

### 11.1 finally 为什么调用 pool.end()

入口最后使用：

```js
.finally(() => pool.end());
```

对应源码：[`src/index.mjs` L121-L126](../src/index.mjs#L121)。

这个工程的 `index.mjs` 是一次性演示脚本。执行结束后调用 `pool.end()` 可以关闭连接池，让 Node.js 进程正常退出。

如果以后编写长期运行的 Web 服务，不能在每次请求后关闭整个连接池。连接池通常会在服务关闭时统一释放。

## 12. 从命令到数据库的完整调用链

运行：

```powershell
node src/index.mjs
```

执行链路：

```text
src/index.mjs
  ↓ 调用 createUser()
src/users.mjs
  ↓ 调用 query(text, params)
src/db.mjs
  ↓ 调用 pool.query()
node-postgres 驱动
  ↓ 通过 localhost:5432 发送 SQL
PostgreSQL 容器
  ↓ 读写 hello_pg
volumes/postgres
```

理解这条链路后，排查错误时可以判断问题属于：

- Docker 容器没有启动。
- 数据库连接字符串错误。
- SQL 语句错误。
- 表结构没有同步。
- 嵌入模型 API 配置错误。
- 向量维度不一致。

## 13. pgAdmin 状态说明

在 2026-06-02 重新核对时，Windows 主机访问 `http://localhost:8088/` 能得到 HTTP `200`，但 Compose 仍将 `pgadmin` 标记为 `unhealthy`。

这意味着：

- pgAdmin 页面实际可访问。
- 当前 healthcheck 的探测结果仍需要单独排查。
- `pgadmin` 的健康状态不等于 PostgreSQL 的健康状态。
- 学习 SQL 时，可以优先使用 `psql`，不必依赖 pgAdmin。

## 14. 教程后半段的 TypeORM

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
