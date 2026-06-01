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

## 2. 新增数据 INSERT

在 `psql` 中执行：

```sql
INSERT INTO users (name)
VALUES ('张三');
```

新增后立即返回完整记录：

```sql
INSERT INTO users (name)
VALUES ('李四')
RETURNING *;
```

`RETURNING` 是 PostgreSQL 很实用的能力。应用程序新增数据后，通常需要立即知道数据库生成的 `id`。

## 3. 查询数据 SELECT

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

## 4. 更新数据 UPDATE

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

## 5. 删除数据 DELETE

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

## 6. 使用事务保护练习数据

事务可以将多个操作视为一个整体。

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

## 7. 约束是什么

约束用于阻止无效数据进入数据库。

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

下一章：[03. 表关系、JOIN 与事务](./03-relations-joins-and-transactions.md)
