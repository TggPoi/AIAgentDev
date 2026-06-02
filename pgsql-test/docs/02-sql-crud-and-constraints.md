# 02. SQL CRUD 与约束

CRUD 是四类最基本的数据操作：

| 缩写 | 操作 | SQL |
| --- | --- | --- |
| Create | 新增数据 | `INSERT` |
| Read | 查询数据 | `SELECT` |
| Update | 更新数据 | `UPDATE` |
| Delete | 删除数据 | `DELETE` |

本章先只操作 `users` 表。

## 1. 查看 users 表定义

[`init-scripts/create_tables.sql` L5-L9](../init-scripts/create_tables.sql#L5) 中定义了：

```sql
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

逐列理解：

| 列 | 类型或约束 | 含义 |
| --- | --- | --- |
| `id` | `SERIAL PRIMARY KEY` | 自动生成的唯一编号 |
| `name` | `TEXT NOT NULL` | 文本，不能为空 |
| `created_at` | `TIMESTAMP WITH TIME ZONE` | 带时区的时间 |
| `DEFAULT CURRENT_TIMESTAMP` | 默认值 | 插入时不填写则使用当前时间 |

### 1.1 类型、约束和默认值不是同一概念

一列定义可以同时包含多类规则：

```sql
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
```

拆开理解：

| 部分 | 类型 | 作用 |
| --- | --- | --- |
| `created_at` | 列名 | 保存创建时间 |
| `TIMESTAMP WITH TIME ZONE` | 数据类型 | 限制该列保存带时区时间 |
| `DEFAULT CURRENT_TIMESTAMP` | 默认值 | 插入时不填写该列，就使用当前时间 |

再看：

```sql
name TEXT NOT NULL
```

| 部分 | 类型 | 作用 |
| --- | --- | --- |
| `name` | 列名 | 保存用户名称 |
| `TEXT` | 数据类型 | 允许保存文本 |
| `NOT NULL` | 约束 | 禁止保存空值 `NULL` |

数据类型解决“保存什么种类的值”，约束解决“哪些值虽然类型正确但仍然不允许保存”。

## 2. 新增数据 INSERT

`INSERT` 用于向表中增加新行。基本结构是：

```sql
INSERT INTO 表名 (列1, 列2)
VALUES (值1, 值2);
```

列和值按照位置一一对应。

在 `psql` 中执行：

```sql
INSERT INTO users (name)
VALUES ('张三');
```

~~~
INSERT 0 1

耗时58 毫秒 成功返回查询。
~~~



新增后立即返回完整记录：

```sql
INSERT INTO users (name)
VALUES ('李四')
RETURNING *;
```

`RETURNING` 是 PostgreSQL 很实用的能力。应用程序新增数据后，通常需要立即知道数据库生成的 `id`。

~~~
RETURNING * 插入后直接返回当前行的数据
~~~

如果只需要返回主键，可以减少返回数据量：

```sql
INSERT INTO users (name)
VALUES ('赵六')
RETURNING id;
```

### 2.1 省略列时发生什么

插入用户时只填写了 `name`：

```sql
INSERT INTO users (name)
VALUES ('张三');
```

数据库会自动处理另外两列：

- `id` 使用 `SERIAL` 对应序列生成。
- `created_at` 使用 `DEFAULT CURRENT_TIMESTAMP`。

### 2.2 一次插入多行

```sql
INSERT INTO users (name)
VALUES
  ('用户 A'),
  ('用户 B'),
  ('用户 C')
RETURNING *;
```

一次插入多行通常比循环发送多条独立 SQL 更高效。





## 3. 查询数据 SELECT

`SELECT` 用于读取数据。它不会修改表中的行。

查询全部用户：

```sql
SELECT * FROM users;
```

只查询部分列：

```sql
SELECT id, name FROM users;
```

按条件查询：

```sql
SELECT *
FROM users
WHERE name = '张三';
```

排序：

```sql
SELECT *
FROM users
ORDER BY id DESC;
```

限制返回数量：

```sql
SELECT *
FROM users
ORDER BY id DESC
LIMIT 3;
```

组合使用：

```sql
SELECT id, name, created_at
FROM users
WHERE id >= 1
ORDER BY created_at DESC
LIMIT 5;
```

### 3.1 SELECT 的阅读顺序

虽然 SQL 通常从 `SELECT` 开始书写，但阅读时建议按下面的逻辑理解：

```text
FROM users
  ↓ 确定从哪张表读取
WHERE id >= 1
  ↓ 过滤行
SELECT id, name, created_at
  ↓ 选择输出列
ORDER BY created_at DESC
  ↓ 排序
LIMIT 5
  ↓ 只保留前 5 行
```

因此：

```sql
SELECT id, name, created_at
FROM users
WHERE id >= 1
ORDER BY created_at DESC
LIMIT 5;
```

可以读成：“从 `users` 表中找出 `id >= 1` 的用户，输出三个指定列，按照创建时间倒序排列，只取前五行。”

### 3.2 WHERE 只保留条件为真的行

```sql
SELECT *
FROM users
WHERE name = '张三';
```

数据库会逐行判断 `name = '张三'`。只有判断结果为真的行才进入结果集。

### 3.3 NULL 不是空字符串

`NULL` 表示“未知”或“没有值”，它不同于空字符串 `''`。

判断空值时不能写：

```sql
-- 错误示例
WHERE title = NULL
```

应该写：

```sql
WHERE title IS NULL
```

查找非空值：

```sql
WHERE title IS NOT NULL
```

### 3.4 ORDER BY：明确指定结果行的顺序

SQL 查询返回的是一个结果集。如果没有写 `ORDER BY`，PostgreSQL **不保证** 行的返回顺序。

下面的查询可以正常执行：

```sql
SELECT id, name
FROM users;
```

你可能暂时观察到结果按照 `id` 从小到大显示，但不能依赖这个现象。随着数据变化、索引变化或查询计划变化，同一条 SQL 可能以不同顺序返回数据。

需要稳定顺序时，必须明确写出：

```sql
SELECT id, name
FROM users
ORDER BY id;
```

`ORDER BY id` 表示：根据 `id` 列的值排列查询结果。

重要区别：

| 语句 | 是否保证顺序 |
| --- | --- |
| `SELECT * FROM users;` | 不保证 |
| `SELECT * FROM users ORDER BY id;` | 保证按照 `id` 排序 |

不要把“当前看起来有顺序”误认为“数据库承诺了这个顺序”。

### 3.5 ASC 与 DESC：升序和降序

`ORDER BY` 可以指定排序方向：

| 关键词 | 含义 | 数字示例 | 时间示例 |
| --- | --- | --- | --- |
| `ASC` | 升序，从小到大 | `1, 2, 3` | 从较早时间到较晚时间 |
| `DESC` | 降序，从大到小 | `3, 2, 1` | 从较晚时间到较早时间 |

按照用户 ID 从小到大排列：

```sql
SELECT id, name
FROM users
ORDER BY id ASC;
```

按照用户 ID 从大到小排列：

```sql
SELECT id, name
FROM users
ORDER BY id DESC;
```

如果省略方向，默认使用 `ASC`：

```sql
ORDER BY id
```

等价于：

```sql
ORDER BY id ASC
```

在会话或消息列表中，经常使用时间排序：

```sql
-- 从旧到新显示消息，适合按照对话发生顺序阅读
SELECT id, role, content, created_at
FROM messages
WHERE conversation_id = 1
ORDER BY created_at ASC;
```

当前工程的 [`getMessagesByConversationId()`](../src/messages.mjs#L56) 就使用了这种方式。

查询最近创建的五位用户：

```sql
SELECT id, name, created_at
FROM users
ORDER BY created_at DESC
LIMIT 5;
```

### 3.6 【重点】多列排序：前一列相同时，再比较后一列

排序条件可以包含多个字段：

```sql
SELECT id, name, created_at
FROM users
ORDER BY created_at DESC, id DESC;
```

阅读方式：

1. 先按照 `created_at` 从晚到早排列。
2. 如果两条记录的 `created_at` 完全相同，再按照 `id` 从大到小排列。

假设数据为：

```text
id | name | created_at
---+------+------------------------
 1 | A    | 2026-06-02 10:00:00+08
 2 | B    | 2026-06-02 10:00:00+08
 3 | C    | 2026-06-02 11:00:00+08
```

执行：

```sql
ORDER BY created_at DESC, id DESC
```

结果：

```text
id | name
---+-----
 3 | C
 2 | B
 1 | A
```

**`id = 1` 和 `id = 2` 的创建时间相同，因此继续使用第二个条件 `id DESC` 决定顺序。**

每个字段可以独立指定方向：

```sql
ORDER BY name ASC, created_at DESC
```

表示先按名称升序排列；名称相同时，较新的记录排在前面。

### 3.7 【重点】稳定排序：结果相同时仍然需要确定顺序

下面的查询不一定具有完全稳定的顺序：

```sql
SELECT id, name, created_at
FROM users
ORDER BY created_at DESC;
```

**如果两位用户的 `created_at` 相同，数据库没有收到进一步排序要求，因此这两行谁先谁后没有保证。**

可以增加一个唯一字段作为最终排序条件：

```sql
SELECT id, name, created_at
FROM users
ORDER BY created_at DESC, id DESC;
```

**这对分页非常重要。分页时如果排序不稳定，相邻两页可能出现重复记录或遗漏记录。**

实践习惯：

> 当第一排序字段可能重复时，追加主键作为最后一个排序字段。

例如：

```sql
ORDER BY created_at DESC, id DESC
```

### 3.8 NULLS FIRST 与 NULLS LAST：控制空值位置

[`conversations.title`](../init-scripts/create_tables.sql#L15) 允许为 `NULL`。查询会话时，可以明确要求空标题显示在最后：

```sql
SELECT id, title
FROM conversations
ORDER BY title ASC NULLS LAST;
```

关键词：

| 写法 | 含义 |
| --- | --- |
| `NULLS FIRST` | 将 `NULL` 放在非空值前面 |
| `NULLS LAST` | 将 `NULL` 放在非空值后面 |

PostgreSQL 的默认行为：

| 排序方向 | 默认空值位置 |
| --- | --- |
| `ASC` | `NULLS LAST` |
| `DESC` | `NULLS FIRST` |

即使默认行为满足需求，业务查询也可以显式写出 `NULLS FIRST` 或 `NULLS LAST`，让意图更容易阅读。

例如，按照更新时间从新到旧排列，但没有更新时间的记录放在最后：

```sql
ORDER BY updated_at DESC NULLS LAST
```

如果省略 `NULLS LAST`，降序排序会默认让 `NULL` 出现在前面，这通常不符合“最近更新优先”的业务需求。

### 3.9 可以按照表达式或别名排序

`ORDER BY` 不局限于原始列，也可以使用表达式。

按照名称长度排序：

```sql
SELECT id, name
FROM users
ORDER BY length(name) ASC, id ASC;
```

也可以先为表达式声明别名，再使用别名排序：

```sql
SELECT
  id,
  name,
  length(name) AS name_length
FROM users
ORDER BY name_length DESC, id;
```

聚合查询也经常按照统计结果的别名排序：

```sql
SELECT
  role,
  COUNT(*) AS message_count
FROM messages
GROUP BY role
ORDER BY message_count DESC, role;
```

这里先按 `role` 分组并计算 `message_count`，再把数量较多的角色排在前面。

PostgreSQL 也允许按照输出列序号排序：

```sql
SELECT id, name
FROM users
ORDER BY 2;
```

这里的 `2` 表示第二个输出列 `name`。这种写法较短，但修改 `SELECT` 列表后容易产生误解。业务代码中通常优先写明确的列名或别名。

### 3.10 ORDER BY 与 LIMIT：先排序，再取前几行

`LIMIT` 用于限制返回行数：

```sql
SELECT id, name, created_at
FROM users
ORDER BY created_at DESC, id DESC
LIMIT 5;
```

含义：

1. 查询用户。
2. 按照创建时间和 ID 从大到小排序。
3. 只返回排序后的前五行。

这才表示“最近创建的五位用户”。

如果省略排序：

```sql
SELECT id, name, created_at
FROM users
LIMIT 5;
```

它只表示“任意返回不超过五位用户”，不能解释为“最早五位”或“最近五位”。

### 3.11 ORDER BY 与 OFFSET：基础分页

`OFFSET` 表示跳过多少行：

```sql
SELECT id, name, created_at
FROM users
ORDER BY created_at DESC, id DESC
LIMIT 5
OFFSET 10;
```

含义：

1. 按照稳定顺序排列全部用户。
2. 跳过前 `10` 行。
3. 返回接下来的 `5` 行。

可以将它理解为获取第三页，每页五条记录。

分页时必须提供可预测的排序：

```sql
ORDER BY created_at DESC, id DESC
```

否则数据库无法明确“应该跳过哪十行”。

`OFFSET` 适合入门和数据量较小的管理页面。偏移量很大时，数据库仍然需要计算并跳过前面的行，性能可能下降。长会话和大数据列表通常使用游标分页，详见 [08-高级查询、JSONB 与混合检索](./08-advanced-query-jsonb-and-hybrid-search.md#92-游标分页)。

### 3.12 ORDER BY、GROUP BY 与索引的关系

三个概念不要混淆：

| 概念 | 作用 |
| --- | --- |
| `ORDER BY` | 决定结果行如何排列 |
| `GROUP BY` | 将行临时归类，通常配合聚合函数 |
| 索引 | 数据库用于提高特定查询效率的数据结构 |

`ORDER BY` 描述的是业务需要的结果顺序。索引可能帮助数据库更快返回这种顺序，但不是所有排序都会自动使用索引。

例如，经常按照会话和消息时间读取记录：

```sql
SELECT id, role, content, created_at
FROM messages
WHERE conversation_id = 1
ORDER BY created_at ASC, id ASC;
```

数据量增长后，可以评估复合索引：

```sql
CREATE INDEX idx_messages_conversation_created_id
  ON messages (conversation_id, created_at ASC, id ASC);
```

是否真正使用索引，要通过 `EXPLAIN` 或 `EXPLAIN ANALYZE` 验证，而不是只看索引已经创建。

### 3.13 向量检索中的 ORDER BY

`ORDER BY` 也可以按照计算结果排序。当前工程的 pgvector 查询：

```sql
ORDER BY embedding <=> $1::vector
LIMIT $3
```

源码见 [`searchSimilarMessages()`](../src/messages.mjs#L92)。

`embedding <=> $1::vector` 计算每条消息与查询向量的余弦距离。距离越小，语义越接近。因此：

1. 先按距离升序排列。
2. 再使用 `LIMIT $3` 只保留最近的几条记录。

详细解释见 [04-pgvector 与语义检索](./04-pgvector-and-semantic-search.md#41-为什么-order-by-使用距离而不是别名-similarity)。

## 4. 更新数据 UPDATE

`UPDATE` 修改已经存在的行。基本结构：

```sql
UPDATE 表名
SET 列名 = 新值
WHERE 条件;
```

修改指定用户：

```sql
UPDATE users
SET name = '王五'
WHERE id = 1
RETURNING *;
```

`WHERE id = 1` 非常重要。如果省略 `WHERE`，会修改表中的所有用户：

```sql
-- 不要随意执行
UPDATE users SET name = '王五';
```

执行前建议先把同一个条件用于查询：

```sql
SELECT *
FROM users
WHERE id = 1;
```

确认目标行正确后，再执行 `UPDATE`。

## 5. 删除数据 DELETE

`DELETE` 删除符合条件的整行数据，不是将某个字段清空。

删除指定用户：

```sql
DELETE FROM users
WHERE id = 1
RETURNING *;
```

如果省略 `WHERE`，会删除表中的所有用户：

```sql
-- 不要随意执行
DELETE FROM users;
```

初学阶段执行 `UPDATE` 和 `DELETE` 前，先用同一个条件执行一次 `SELECT`：

```sql
SELECT * FROM users WHERE id = 1;
```

确认目标正确后，再执行修改或删除。

如果只是希望清空一个字段，应使用 `UPDATE`：

```sql
UPDATE conversations
SET title = NULL
WHERE id = 1;
```



## 6. 使用事务保护练习数据

事务可以将多个操作视为一个整体。

如果事务中的多个操作属于同一个业务步骤，就应该一起成功或一起失败。例如转账不能只扣款但不入账。当前学习工程中，创建会话和写入第一条消息也可能需要作为一个整体处理。

下面的练习不会永久写入数据库：

```sql
BEGIN;

INSERT INTO users (name)
VALUES ('事务练习用户')
RETURNING *;

SELECT * FROM users
WHERE name = '事务练习用户';

ROLLBACK;

SELECT * FROM users
WHERE name = '事务练习用户';
```

含义：

| SQL | 作用 |
| --- | --- |
| `BEGIN` | 开始事务 |
| `COMMIT` | 提交事务，永久保存修改 |
| `ROLLBACK` | 回滚事务，撤销尚未提交的修改 |

### 6.1 COMMIT 与 ROLLBACK 的区别

```text
BEGIN
  ↓
执行若干 INSERT、UPDATE 或 DELETE
  ↓
COMMIT    永久保存修改
或
ROLLBACK  撤销本次事务中的修改
```

事务尚未提交时，当前连接可以看到自己的修改。执行 `ROLLBACK` 后，这些修改会消失。



## 7. 约束是什么

约束用于阻止无效数据进入数据库。

应用程序可以做参数校验，但数据库约束仍然重要。因为数据不一定只通过一个 Node.js 程序写入，还可能来自：

- 其他后端服务。
- pgAdmin。
- `psql` 手动 SQL。
- 批量导入脚本。

数据库约束是最后一道一致性防线。

### NOT NULL

`users.name` 使用了 `NOT NULL`：

```sql
name TEXT NOT NULL
```

下面的 SQL 会失败：

```sql
INSERT INTO users (name) VALUES (NULL);
```

### PRIMARY KEY

主键保证唯一性，并且不能为空：

```sql
id SERIAL PRIMARY KEY
```

### CHECK

初始化脚本中，消息角色被限制为三种值：

```sql
role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system'))
```

对应源码：[`init-scripts/create_tables.sql` L26](../init-scripts/create_tables.sql#L26)。

数据库应该拒绝其他角色，例如 `manager`。

`CHECK` 用于表达“值必须满足某个布尔条件”。当前规则可以读成：

```text
role 必须属于 user、assistant、system 三个值之一
```

仅使用 `TEXT` 类型无法表达这个业务限制，因为字符串 `'manager'` 在类型上仍然是合法文本。

### FOREIGN KEY

外键用于确保关联数据存在。例如，会话必须属于一个真实用户：

```sql
FOREIGN KEY (user_id) REFERENCES users(id)
```

对应源码：[`init-scripts/create_tables.sql` L17-L19](../init-scripts/create_tables.sql#L17)。

下一章会详细学习外键。

## 8. SQL 与 Node.js 参数化查询

[`src/users.mjs` L3-L8](../src/users.mjs#L3) 中新增用户的代码是：

```js
const { rows } = await query(
  "INSERT INTO users (name) VALUES ($1) RETURNING *",
  [name]
);
```

`$1` 是占位符，`[name]` 提供实际值。

不要使用字符串拼接直接插入用户输入：

```js
// 不推荐
`INSERT INTO users (name) VALUES ('${name}')`
```

参数化查询能够正确处理特殊字符，并降低 SQL 注入风险。

多个参数按顺序编号：

```js
await query(
  "UPDATE users SET name = $1 WHERE id = $2 RETURNING *",
  [name, id]
);
```

对应源码：[`src/users.mjs` L21-L26](../src/users.mjs#L21)。

### 对照完整用户 CRUD 源码

| 操作 | Node.js 实现 |
| --- | --- |
| 新增用户 | [`createUser()` L3-L8](../src/users.mjs#L3) |
| 按 ID 查询用户 | [`getUserById()` L11-L13](../src/users.mjs#L11) |
| 查询全部用户 | [`getAllUsers()` L16-L18](../src/users.mjs#L16) |
| 更新用户 | [`updateUser()` L21-L26](../src/users.mjs#L21) |
| 删除用户 | [`deleteUser()` L29-L31](../src/users.mjs#L29) |

## 官方参考资料

- [PostgreSQL 16: Sorting Rows (`ORDER BY`)](https://www.postgresql.org/docs/16/queries-order.html)
- [PostgreSQL 16: `LIMIT` and `OFFSET`](https://www.postgresql.org/docs/16/queries-limit.html)
- [PostgreSQL 16: Querying a Table](https://www.postgresql.org/docs/16/tutorial-select.html)
- [PostgreSQL 16: Aggregate Functions](https://www.postgresql.org/docs/16/tutorial-agg.html)

## 本章练习

使用事务完成一次完整 CRUD：

```sql
BEGIN;

INSERT INTO users (name)
VALUES ('SQL 学习用户')
RETURNING *;

SELECT * FROM users
WHERE name = 'SQL 学习用户';

UPDATE users
SET name = 'SQL 学习用户-已更新'
WHERE name = 'SQL 学习用户'
RETURNING *;

DELETE FROM users
WHERE name = 'SQL 学习用户-已更新'
RETURNING *;

ROLLBACK;
```

## 完成标准

你应该能够回答：

1. CRUD 分别对应哪些 SQL。
2. 为什么 `UPDATE` 和 `DELETE` 需要谨慎检查 `WHERE`。
3. `NOT NULL`、`PRIMARY KEY`、`CHECK` 分别解决什么问题。
4. Node.js 中为什么使用 `$1`、`$2`，而不是拼接 SQL 字符串。
5. 为什么没有 `ORDER BY` 时不能依赖结果行的显示顺序。
6. `ASC`、`DESC`、`NULLS FIRST`、`NULLS LAST` 分别有什么作用。
7. 多列排序中，第二个排序字段何时起作用。
8. 为什么 `LIMIT` 和分页查询通常需要稳定排序。
9. `ORDER BY`、`GROUP BY` 和索引分别解决什么问题。

下一章：[03. 表关系、JOIN 与事务](./03-relations-joins-and-transactions.md)
