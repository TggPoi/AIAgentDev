# 03. 表关系、JOIN 与事务

当前工程不只保存用户，还保存用户的会话和会话中的消息。

对应建表源码：

- [`users` 表 L5-L9](../init-scripts/create_tables.sql#L5)
- [`conversations` 表 L12-L20](../init-scripts/create_tables.sql#L12)
- [`messages` 表 L23-L33](../init-scripts/create_tables.sql#L23)

## 1. 三张表的关系

```text
users
  id
  name
  │
  │ users.id = conversations.user_id
  ▼
conversations
  id
  user_id
  title
  │
  │ conversations.id = messages.conversation_id
  ▼
messages
  id
  conversation_id
  role
  content
  embedding
```

关系为：

- 一个用户可以拥有多个会话。
- 一个会话只能属于一个用户。
- 一个会话可以拥有多条消息。
- 一条消息只能属于一个会话。

这种关系称为一对多。

### 1.1 为什么不把所有内容放在一张表

假设把用户名、会话标题和消息内容全部放在一张表中：

```text
user_name | conversation_title | role      | content
----------+--------------------+-----------+----------------
张三      | PostgreSQL 学习     | user      | 什么是外键？
张三      | PostgreSQL 学习     | assistant | 外键用于...
张三      | Docker 学习         | user      | 什么是容器？
```

这会造成重复：

- 用户名会在每条消息中重复保存。
- 会话标题会在该会话的每条消息中重复保存。
- 用户改名时，需要修改很多行。
- 删除或更新时更容易漏掉部分数据。

拆分为三张表后，每类数据只保存一次：

```text
users
  1 | 张三

conversations
  10 | 1 | PostgreSQL 学习
  11 | 1 | Docker 学习

messages
  100 | 10 | user      | 什么是外键？
  101 | 10 | assistant | 外键用于...
```

`conversations.user_id = 1` 表示会话属于 `users.id = 1` 的用户。`messages.conversation_id = 10` 表示消息属于 `conversations.id = 10` 的会话。

### 1.2 一对多关系保存在哪里

“一个用户有多个会话”并不意味着 `users` 表中需要保存一个会话数组。

关系实际保存在“多”的一侧：

```text
conversations.user_id
```

例如：

```text
conversations
id | user_id | title
---+---------+----------------
10 |       1 | PostgreSQL 学习
11 |       1 | Docker 学习
12 |       2 | AI 应用设计
```

查询 `WHERE user_id = 1` 就能得到用户 `1` 的两个会话。

## 2. 外键保证关联有效

会话表中的外键：

```sql
CONSTRAINT fk_conversations_user
    FOREIGN KEY (user_id) REFERENCES users(id)
    ON DELETE CASCADE
```

对应源码：[`init-scripts/create_tables.sql` L17-L19](../init-scripts/create_tables.sql#L17)。

它表示：

- `conversations.user_id` 必须引用已经存在的 `users.id`。
- 删除用户时，数据库自动删除该用户的会话。

消息表中的外键：

```sql
CONSTRAINT fk_messages_conversation
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
    ON DELETE CASCADE
```

对应源码：[`init-scripts/create_tables.sql` L30-L32](../init-scripts/create_tables.sql#L30)。

它表示：

- `messages.conversation_id` 必须引用已经存在的 `conversations.id`。
- 删除会话时，数据库自动删除该会话中的消息。

### 2.1 被引用表和引用表

以用户和会话为例：

```text
users.id  ←  conversations.user_id
```

| 角色 | 当前例子 | 含义 |
| --- | --- | --- |
| 被引用表 referenced table | `users` | 提供被引用的主键 |
| 引用表 referencing table | `conversations` | 保存外键，指向另一张表 |
| 被引用列 | `users.id` | 用户主键 |
| 引用列 | `conversations.user_id` | 会话所属用户 |

外键会阻止“孤儿数据”。例如，数据库中没有 `id = 999999` 的用户时，下面的 SQL 会失败：

```sql
INSERT INTO conversations (user_id, title)
VALUES (999999, '不存在的用户');
```

如果没有外键，这条会话记录可以写入，但以后无法找到它所属的真实用户。

### 2.2 外键与 JOIN 不是同一件事

这两个概念经常一起出现，但职责不同：

| 概念 | 作用 |
| --- | --- |
| 外键 `FOREIGN KEY` | 写入或删除数据时维护引用完整性 |
| `JOIN` | 查询时把多张表的行组合起来 |

建立外键后，PostgreSQL 不会自动在查询结果中附带用户名。要取得用户和会话的组合结果，仍然需要显式写 `JOIN`。

### 2.3 【重点】ON DELETE CASCADE 的含义

当前外键使用：

```sql
ON DELETE CASCADE
```

`CASCADE` 表示级联删除：

```text
删除 users 中的用户
  ↓
自动删除 conversations 中属于该用户的会话
  ↓
自动删除 messages 中属于这些会话的消息
```

它适合当前聊天记录场景，因为用户被删除后，所属会话和消息通常也不再有保留意义。

其他业务场景可能选择不同策略：

| 策略 | 含义 | 适用示例 |
| --- | --- | --- |
| `ON DELETE CASCADE` | 自动删除子记录 | 删除会话时同时删除消息 |
| 默认拒绝删除 | 存在子记录时不允许删除父记录 | 有订单时禁止删除商品 |
| `ON DELETE SET NULL` | 将子记录外键改为 `NULL` | 删除员工后保留历史任务 |

## 3. 准备一组练习数据

下面使用事务，练习结束时可以回滚：

```sql
BEGIN;

INSERT INTO users (name)
VALUES ('关系练习用户')
RETURNING *;
```

记下返回的用户 `id`。下面假设它是 `100`，实际操作时替换为你的真实值：

```sql
INSERT INTO conversations (user_id, title)
VALUES
  (100, 'PostgreSQL 学习'),
  (100, 'AI 应用设计')
RETURNING *;
```

记下第一个会话的 `id`。下面假设它是 `200`：

```sql
INSERT INTO messages (conversation_id, role, content)
VALUES
  (200, 'user', '什么是 PostgreSQL？'),
  (200, 'assistant', 'PostgreSQL 是关系型数据库。')
RETURNING *;
```

## 4. 使用 WHERE 查询一张表

查询某个用户的全部会话：

```sql
SELECT *
FROM conversations
WHERE user_id = 100
ORDER BY created_at DESC;
```

查询某个会话的全部消息：

```sql
SELECT *
FROM messages
WHERE conversation_id = 200
ORDER BY created_at ASC;
```

这正是 [`src/conversations.mjs` L19-L24](../src/conversations.mjs#L19) 和 [`src/messages.mjs` L56-L64](../src/messages.mjs#L56) 中使用的方式。

`WHERE` 查询一张表时，只能直接得到这张表中保存的列。

例如：

```sql
SELECT *
FROM conversations
WHERE user_id = 100;
```

可以得到 `user_id`，但无法直接得到用户名称，因为 `name` 保存在 `users` 表中。需要同时读取两张表的数据时，就要使用 `JOIN`。

### 对照关联相关源码

| 操作 | Node.js 实现 |
| --- | --- |
| 新增会话并保存 `user_id` | [`createConversation()` L3-L8](../src/conversations.mjs#L3) |
| 查询某个用户的全部会话 | [`getConversationsByUserId()` L19-L24](../src/conversations.mjs#L19) |
| 新增消息并保存 `conversation_id` | [`createMessage()` L22-L44](../src/messages.mjs#L22) |
| 查询某个会话的全部消息 | [`getMessagesByConversationId()` L56-L64](../src/messages.mjs#L56) |

## 5. 使用 JOIN 跨表查询

`JOIN` 用于根据关联条件组合多张表。

### 5.1 先理解 JOIN 的配对过程

为了清楚观察结果，先假设数据库中有下面的数据。

`users`：

```text
id | name
---+------
 1 | 张三
 2 | 李四
 3 | 王五
```

`conversations`：

```text
id | user_id | title
---+---------+----------------
10 |       1 | PostgreSQL 学习
11 |       1 | Docker 学习
12 |       2 | AI 应用设计
```

用户 `3` 没有会话。

执行：

```sql
SELECT
  u.id,
  u.name,
  c.id AS conversation_id,
  c.title
FROM users AS u
JOIN conversations AS c
  ON c.user_id = u.id;
```

数据库会按照 `ON c.user_id = u.id` 寻找可以配对的行。概念上可以理解为：

```text
users.id = 1  匹配 conversations.user_id = 1  → 匹配两行
users.id = 2  匹配 conversations.user_id = 2  → 匹配一行
users.id = 3  没有匹配行                         → 暂时不输出
```

结果：

```text
id | name | conversation_id | title
---+------+-----------------+----------------
 1 | 张三 |              10 | PostgreSQL 学习
 1 | 张三 |              11 | Docker 学习
 2 | 李四 |              12 | AI 应用设计
```

注意：张三会出现两次。`JOIN` 的结果不是“一位用户固定输出一行”，而是“每一个满足连接条件的行组合输出一行”。

数据库内部可能使用更高效的算法执行查询，不一定真的逐行嵌套比较。上面的过程是理解结果集的心智模型。

### 5.2 AS 是别名

查询会话以及所属用户名：

```sql
SELECT
  c.id AS conversation_id,
  c.title,
  u.id AS user_id,
  u.name AS user_name
FROM conversations AS c
JOIN users AS u
  ON c.user_id = u.id
ORDER BY c.created_at DESC;
```

这里：

- `AS c` 为 `conversations` 设置短别名。
- `AS u` 为 `users` 设置短别名。
- `ON c.user_id = u.id` 是关联条件。

别名可以让 SQL 更短，也可以消除歧义。两张表都有 `id` 列，因此只写：

```sql
SELECT id
```

数据库无法判断你要查询 `users.id` 还是 `conversations.id`。应该明确写：

```sql
SELECT u.id, c.id
```

### 5.3 多表 JOIN 可以继续连接

查询某个用户的全部消息：

```sql
SELECT
  u.name,
  c.title,
  m.role,
  m.content,
  m.created_at
FROM users AS u
JOIN conversations AS c
  ON c.user_id = u.id
JOIN messages AS m
  ON m.conversation_id = c.id
WHERE u.id = 100
ORDER BY m.created_at ASC;
```

可以按从左到右理解：

```text
users u
  ↓ 根据 c.user_id = u.id 连接
conversations c
  ↓ 根据 m.conversation_id = c.id 连接
messages m
  ↓ 只保留 u.id = 100
结果集
```

## 6. INNER JOIN 与 LEFT JOIN

### 6.1 INNER JOIN：只保留成功匹配的组合

只写 `JOIN` 时，默认就是 `INNER JOIN`：

```sql
SELECT *
FROM users AS u
JOIN conversations AS c
  ON c.user_id = u.id;
```

它只返回“至少有一个会话”的用户。

使用前面三位用户的示例数据，结果为：

```text
id | name | conversation_id | title
---+------+-----------------+----------------
 1 | 张三 |              10 | PostgreSQL 学习
 1 | 张三 |              11 | Docker 学习
 2 | 李四 |              12 | AI 应用设计
```

王五没有会话，因此无法与 `conversations` 中任何一行组成满足条件的组合，结果中不会出现王五。

适用场景：

- 只关心存在会话的用户。
- 查询每条消息所属的会话。
- 只处理两边数据都完整存在的记录。

### 6.2 【理解左表概念的重点】LEFT JOIN：左表每一行至少保留一次

如果希望没有会话的用户也显示出来，使用 `LEFT JOIN`：

```sql
SELECT
  u.id,
  u.name,
  c.id AS conversation_id,
  c.title
FROM users AS u
LEFT JOIN conversations AS c
  ON c.user_id = u.id
ORDER BY u.id;
```

`LEFT JOIN` 也可以写成 `LEFT OUTER JOIN`，含义相同。

结果：

```text
id | name | conversation_id | title
---+------+-----------------+----------------
 1 | 张三 |              10 | PostgreSQL 学习
 1 | 张三 |              11 | Docker 学习
 2 | 李四 |              12 | AI 应用设计
 3 | 王五 |            NULL | NULL
```

关键点：

- “左”指 `LEFT JOIN` 左侧的表，也就是 `users AS u`。
- 左表中的每一行至少输出一次。
- 如果右表找不到匹配行，右表对应列使用 `NULL` 补位。
- 张三有两个匹配会话，所以仍然输出两行。

适用场景：

- 查询所有用户，包括尚未创建会话的用户。
- 统计每位用户的会话数量，包括数量为 `0` 的用户。
- 查找缺失关联数据，例如“哪些用户没有会话”。

查找没有会话的用户：

```sql
SELECT u.id, u.name
FROM users AS u
LEFT JOIN conversations AS c
  ON c.user_id = u.id
WHERE c.id IS NULL;
```

### 6.3 【重点】INNER JOIN 与 LEFT JOIN 对比

| 问题 | `INNER JOIN` | `LEFT JOIN` |
| --- | --- | --- |
| 左右两侧都有匹配行时 | 返回组合结果 | 返回组合结果 |
| 左表某行没有右表匹配行时 | 丢弃该左表行 | 保留左表行，右表列填 `NULL` |
| 适合查询全部用户吗 | 不适合，会漏掉没有会话的用户 | 适合 |
| 适合只查询存在会话的用户吗 | 适合 | 可以，但通常没有必要 |

选择 JOIN 类型前，先问自己：

> 右表没有匹配数据时，我是否仍然需要保留左表这一行？

- 如果不需要，使用 `INNER JOIN`。
- 如果需要，使用 `LEFT JOIN`。

### 6.4 LEFT JOIN 的左右顺序会影响结果

下面两个查询不等价：

```sql
FROM users AS u
LEFT JOIN conversations AS c
  ON c.user_id = u.id
```

```sql
FROM conversations AS c
LEFT JOIN users AS u
  ON c.user_id = u.id
```

第一个查询保证保留所有用户。第二个查询保证保留所有会话。

当前数据库有外键，因此正常情况下每个会话都能找到用户。但在没有外键约束或处理历史脏数据时，两者差异会很明显。

### 6.5 【重点】ON 与 WHERE 的职责不同

`ON` 决定两张表如何配对：

```sql
ON c.user_id = u.id
```

**`WHERE` 在连接完成后继续过滤结果：**

```sql
WHERE u.id = 1
```

对 `LEFT JOIN` 来说，这个区别非常重要。

查询所有用户，并且只连接标题为 `PostgreSQL 学习` 的会话：

```sql
SELECT u.id, u.name, c.title
FROM users AS u
LEFT JOIN conversations AS c
  ON c.user_id = u.id
 AND c.title = 'PostgreSQL 学习';
```

没有匹配会话的用户仍然保留，`c.title` 为 `NULL`。

如果把条件放进 `WHERE`：

```sql
SELECT u.id, u.name, c.title
FROM users AS u
LEFT JOIN conversations AS c
  ON c.user_id = u.id
WHERE c.title = 'PostgreSQL 学习';
```

没有会话的用户会被过滤掉，因为其 `c.title` 为 `NULL`，不满足条件。这会让结果表现得更接近 `INNER JOIN`。

### 6.6 避免遗漏 ON 条件

如果把两张表直接组合却没有正确连接条件，可能得到笛卡尔积：

```sql
SELECT *
FROM users
CROSS JOIN conversations;
```

如果 `users` 有 3 行，`conversations` 有 3 行，结果会有 `3 × 3 = 9` 行。普通业务查询通常不需要这种结果。

### 6.7 RIGHT JOIN：保留右表的全部行

PostgreSQL 也支持 `RIGHT JOIN`。它与 `LEFT JOIN` 的方向相反：

- `LEFT JOIN` 保留左表全部行。
- `RIGHT JOIN` 保留右表全部行。

下面的查询会保留所有用户，包括没有会话的用户：

```sql
SELECT
  u.id,
  u.name,
  c.id AS conversation_id,
  c.title
FROM conversations AS c
RIGHT JOIN users AS u
  ON c.user_id = u.id
ORDER BY u.id;
```

这与下面的 `LEFT JOIN` 等价：

```sql
SELECT
  u.id,
  u.name,
  c.id AS conversation_id,
  c.title
FROM users AS u
LEFT JOIN conversations AS c
  ON c.user_id = u.id
ORDER BY u.id;
```

实际项目通常更常用 `LEFT JOIN`，因为人们更容易按“先写必须保留的主表，再连接可选数据”的顺序阅读 SQL。`RIGHT JOIN` 不是错误，但如果交换表顺序就能表达同一含义，优先使用更直观的 `LEFT JOIN`。

### 6.8 FULL JOIN：两侧未匹配的行都保留

`FULL JOIN` 也可以写成 `FULL OUTER JOIN`。它会保留：

- 左右两侧成功匹配的组合。
- 左表中没有匹配项的行，右表列补 `NULL`。
- 右表中没有匹配项的行，左表列补 `NULL`。

示例：

```sql
SELECT
  u.id AS user_id,
  u.name,
  c.id AS conversation_id,
  c.title
FROM users AS u
FULL JOIN conversations AS c
  ON c.user_id = u.id
ORDER BY u.id, c.id;
```

当前工程为 [`conversations.user_id`](../init-scripts/create_tables.sql#L14) 定义了非空外键，因此正常情况下不会出现“存在会话但找不到用户”的记录。即使如此，`FULL JOIN` 仍然值得掌握，因为它常用于：

- 对比两份来源不同的数据，找出只存在于一侧的记录。
- 数据迁移后核对新旧表是否一致。
- 清理没有完整约束的历史数据。

四种常见 JOIN 的区别：

| JOIN 类型 | 保留成功匹配行 | 保留左侧未匹配行 | 保留右侧未匹配行 |
| --- | --- | --- | --- |
| `INNER JOIN` | 是 | 否 | 否 |
| `LEFT JOIN` | 是 | 是 | 否 |
| `RIGHT JOIN` | 是 | 否 | 是 |
| `FULL JOIN` | 是 | 是 | 是 |

日常业务查询最常用 `INNER JOIN` 和 `LEFT JOIN`。理解 `RIGHT JOIN` 和 `FULL JOIN` 后，你可以根据“未匹配行是否仍然需要保留”准确选择连接类型。

## 7. 聚合统计

前面的查询主要用于读取明细行：

```sql
SELECT id, conversation_id, role, content
FROM messages
ORDER BY id;
```

结果中的每一行仍然对应一条原始消息。

但业务经常需要回答统计问题：

- 每个用户创建了多少个会话？
- 每个会话包含多少条消息？
- 每种角色分别产生了多少条消息？
- 哪些会话至少有 `10` 条消息？

这时需要使用聚合函数和 `GROUP BY`。

### 7.1 聚合函数：把多行汇总为一个值

聚合函数会读取一组行，再返回一个汇总值。常见聚合函数：

| 函数 | 作用 |
| --- | --- |
| `COUNT(...)` | 计数 |
| `SUM(...)` | 求和 |
| `AVG(...)` | 求平均值 |
| `MAX(...)` | 最大值 |
| `MIN(...)` | 最小值 |

不写 `GROUP BY` 时，整个结果集会被视为一组。

统计 `messages` 表一共有多少条消息：

```sql
SELECT COUNT(*) AS message_count
FROM messages;
```

假设表中有 `5` 条消息，结果只有一行：

```text
message_count
-------------
            5
```

原因是数据库把全部消息作为一个整体，执行一次 `COUNT(*)`。

### 7.2 GROUP BY：先分组，再为每组计算结果

如果需要分别统计每种消息角色的数量，应使用：

```sql
SELECT
  role,
  COUNT(*) AS message_count
FROM messages
GROUP BY role
ORDER BY role;
```

假设原始消息为：

```text
id | role
---+----------
 1 | user
 2 | assistant
 3 | user
 4 | system
 5 | assistant
```

`GROUP BY role` 会根据 `role` 的值将行分组：

```text
user 组
  ├── id = 1
  └── id = 3

assistant 组
  ├── id = 2
  └── id = 5

system 组
  └── id = 4
```

然后数据库为每一组执行一次 `COUNT(*)`：

```text
role      | message_count
----------+--------------
assistant |             2
system    |             1
user      |             2
```

理解 `GROUP BY` 的关键：

> `GROUP BY` 不是修改表中的数据，也不是将多行永久合并。它只是在本次查询执行过程中，根据指定字段将行临时归类。

查询结束后，`messages` 表中的五条原始记录仍然存在。

### 7.3 GROUP BY 与 ORDER BY 不是同一件事

两个关键词很容易混淆：

如果还不熟悉普通排序，先阅读 [02-SQL CRUD 与约束：`ORDER BY`](./02-sql-crud-and-constraints.md#34-order-by明确指定结果行的顺序)。

| 关键词 | 作用 |
| --- | --- |
| `GROUP BY` | 将具有相同分组键的行归为一组 |
| `ORDER BY` | 对最终结果排序 |

下面的查询按角色分组，但没有要求输出顺序：

```sql
SELECT role, COUNT(*)
FROM messages
GROUP BY role;
```

数据库可以按任意顺序返回各组。不要依赖偶然观察到的顺序。

需要按消息数量从多到少显示时，明确写出：

```sql
SELECT
  role,
  COUNT(*) AS message_count
FROM messages
GROUP BY role
ORDER BY message_count DESC, role;
```

**这里先完成分组和计数，再根据聚合结果 `message_count` 排序。**

### 7.4 GROUP BY 后 SELECT 可以写哪些列

分组后，一组中可能包含多条原始记录。数据库必须知道每一列应该如何汇总。

正确写法：

```sql
SELECT
  conversation_id,
  COUNT(*) AS message_count
FROM messages
GROUP BY conversation_id;
```

错误写法：

```sql
SELECT
  conversation_id,
  content,
  COUNT(*) AS message_count
FROM messages
GROUP BY conversation_id;
```

**问题是：一个会话中可能有很多条消息。分组后，数据库无法判断 `content` 应该显示哪一条消息的内容。**

**入门阶段先遵守下面的规则：**

> `SELECT` 中的每个字段，要么出现在 `GROUP BY` 中，要么交给聚合函数处理。

例如：

```sql
SELECT
  conversation_id,
  role,
  COUNT(*) AS message_count
FROM messages
GROUP BY conversation_id, role
ORDER BY conversation_id, role;
```

其中：

- `conversation_id` 和 `role` 都出现在 `GROUP BY` 中。
- `COUNT(*)` 是聚合函数。
- 查询可以正常执行。

PostgreSQL 在特定情况下能够根据主键推断其他列，但刚开始学习时，明确写出分组字段更容易理解和检查 SQL。

### 7.5 【重点】多列 GROUP BY：多个字段共同构成分组键

单列分组：

```sql
GROUP BY conversation_id
```

表示每个会话形成一组。

多列分组：

```sql
GROUP BY conversation_id, role
```

**表示 `(conversation_id, role)` 的组合值相同时才属于同一组。**

假设消息为：

```text
conversation_id | role
----------------+----------
             10 | user
             10 | user
             10 | assistant
             11 | user
```

使用：

```sql
SELECT
  conversation_id,
  role,
  COUNT(*) AS message_count
FROM messages
GROUP BY conversation_id, role
ORDER BY conversation_id, role;
```

结果：

```text
conversation_id | role      | message_count
----------------+-----------+--------------
             10 | assistant |             1
             10 | user      |             2
             11 | user      |             1
```

注意：`conversation_id = 10` 中的 `user` 和 `assistant` 不属于同一组，因为第二个分组字段不同。

### 7.6 JOIN 后再 GROUP BY

统计每个用户有多少个会话：

```sql
SELECT
  u.id,
  u.name,
  COUNT(c.id) AS conversation_count
FROM users AS u
LEFT JOIN conversations AS c
  ON c.user_id = u.id
GROUP BY u.id, u.name
ORDER BY u.id;
```

这个查询的处理过程：

1. `FROM users AS u` 读取用户。
2. `LEFT JOIN conversations AS c` 将用户与会话配对。
3. 没有会话的用户也保留一行，右表字段使用 `NULL` 补位。
4. `GROUP BY u.id, u.name` 将属于同一用户的连接结果归为一组。
5. `COUNT(c.id)` 统计每组中 `c.id` 不为 `NULL` 的行数。
6. `ORDER BY u.id` 对最终统计结果排序。

使用前面的示例数据，结果为：

```text
id | name | conversation_count
---+------+-------------------
 1 | 张三 |                  2
 2 | 李四 |                  1
 3 | 王五 |                  0
```

### 7.7 为什么使用 COUNT(c.id)，而不是 COUNT(*)

王五没有会话，但 `LEFT JOIN` 仍然为王五保留一行：

```text
3 | 王五 | NULL | NULL
```

区别：

| 写法 | 行为 |
| --- | --- |
| `COUNT(*)` | **统计结果集里面的所有行数，包括右表使用 `NULL` 补位的行** |
| `COUNT(c.id)` | 只统计 `c.id` 不为 `NULL` 的行 |

因此，统计会话数量时应写：

```sql
COUNT(c.id)
```

否则王五可能被错误统计为拥有 `1` 个会话。

统计每个会话有多少条消息：

```sql
SELECT
  c.id,
  c.title,
  COUNT(m.id) AS message_count
FROM conversations AS c
LEFT JOIN messages AS m
  ON m.conversation_id = c.id
GROUP BY c.id, c.title
ORDER BY c.id;
```



存在差异，但首先要纠正一个误解：

```sql
COUNT(*)
```

不是“读取并统计所有字段”，而是：

> 统计结果集中有多少行。

```sql
COUNT(c.id)
```

表示：

> 统计结果集中 `c.id` 不为 `NULL` 的行数。





### 当前场景

```sql
SELECT
  u.name,
  COUNT(c.id) AS conversation_count
FROM users AS u
LEFT JOIN conversations AS c
  ON c.user_id = u.id
GROUP BY u.id, u.name;
```

假设王五没有会话，`LEFT JOIN` 仍然会保留一行：

```text
name | c.id
-----+-----
王五 | NULL
```

两种统计结果不同：

| 写法          | 王五的统计结果 | 原因                       |
| ------------- | -------------- | -------------------------- |
| `COUNT(*)`    | `1`            | 结果集中确实存在一行       |
| `COUNT(c.id)` | `0`            | `c.id` 为 `NULL`，不会计数 |

因此，这里必须使用：

```sql
COUNT(c.id)
```

### 性能差异

通常差异非常小：

- `COUNT(*)` 直接统计行数。
- `COUNT(c.id)` 需要额外判断 `c.id` 是否为 `NULL`。
- 实际性能通常主要受 JOIN、过滤条件、数据量和索引影响。

如果使用 `INNER JOIN`，并且 `c.id` 是不可能为空的主键，那么：

```sql
COUNT(*)
```

和：

```sql
COUNT(c.id)
```

结果相同。此时通常优先使用 `COUNT(*)`，语义更直接。

但在 `LEFT JOIN` 中，两者语义不同。正确性比这点微小性能差异更重要。

### 全表统计

即使执行：

```sql
SELECT COUNT(*) FROM conversations;
```

PostgreSQL 通常仍然需要扫描整张表或覆盖全部记录的索引。它不会简单读取一个永久保存的总数，因为并发事务可能看到不同的数据版本。

可使用以下命令比较实际执行计划：

```sql
EXPLAIN ANALYZE
SELECT COUNT(*) FROM conversations;

EXPLAIN ANALYZE
SELECT COUNT(id) FROM conversations;
```

官方参考：[PostgreSQL Aggregate Functions](https://www.postgresql.org/docs/current/functions-aggregate.html)。





### 7.8 【重点】WHERE 与 HAVING：分别在分组前后过滤

**`WHERE` 和 `HAVING` 都能过滤数据，但执行阶段不同：**

| 关键词 | 过滤对象 | 执行时机 |
| --- | --- | --- |
| `WHERE` | 原始行或 JOIN 后的明细行 | **分组之前** |
| `HAVING` | 已经形成的组 | **分组之后** |

统计最近 `7` 天中，每个会话的消息数量：

```sql
SELECT
  conversation_id,
  COUNT(*) AS message_count
FROM messages
WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
GROUP BY conversation_id
ORDER BY message_count DESC;
```

处理过程：

```text
messages 原始行
  ↓ WHERE：只保留最近 7 天的消息
剩余明细行
  ↓ GROUP BY：按 conversation_id 分组
每个会话的组
  ↓ COUNT(*)：统计每一组
统计结果
  ↓ ORDER BY：按数量排序
最终结果
```

如果只关心最近 `7` 天内至少有 `3` 条消息的会话：

```sql
SELECT
  conversation_id,
  COUNT(*) AS message_count
FROM messages
WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
GROUP BY conversation_id
HAVING COUNT(*) >= 3
ORDER BY message_count DESC;
```

这里不能使用：

```sql
WHERE COUNT(*) >= 3
```

**原因是执行 `WHERE` 时，数据库还没有完成分组，也没有得到每组的 `COUNT(*)`。**

记忆方式：

```text
WHERE 过滤行
HAVING 过滤组
```

能够在 `WHERE` 中完成的过滤，通常不要拖到 `HAVING`。先减少需要参与分组的行，表达更清晰，也通常更高效。

### 7.9 GROUP BY 与 DISTINCT 的区别

`DISTINCT` 用于删除完全重复的结果行：

```sql
SELECT DISTINCT role
FROM messages;
```

可能得到：

```text
assistant
system
user
```

如果只想知道“有哪些角色”，使用 `DISTINCT` 很合适。

`GROUP BY` 更适合需要对每组执行统计的场景：

```sql
SELECT
  role,
  COUNT(*) AS message_count
FROM messages
GROUP BY role;
```

对比：

| 目标 | 推荐写法 |
| --- | --- |
| 查询出现过哪些不同角色 | `SELECT DISTINCT role ...` |
| 查询每种角色分别出现多少次 | `GROUP BY role` + `COUNT(*)` |

### 7.10 NULL 也会形成一个分组

假设某张表允许某个字段为 `NULL`，执行：

```sql
SELECT category, COUNT(*)
FROM example_items
GROUP BY category;
```

所有 `category IS NULL` 的记录会归到同一个组中。

学习时要区分：

- `NULL` 不是空字符串。
- **`NULL` 表示缺失或未知值。**
- 分组查询会将这些 `NULL` 记录汇总到一个分组中。

当前工程的 [`conversations.title`](../init-scripts/create_tables.sql#L15) 允许为 `NULL`。可以使用：

```sql
SELECT
  title,
  COUNT(*) AS conversation_count
FROM conversations
GROUP BY title
ORDER BY title NULLS LAST;
```

这段查询可以按下面的顺序理解：

| 片段 | 含义 |
| --- | --- |
| `FROM conversations` | 从会话表读取数据 |
| `GROUP BY title` | 标题相同的会话归为一组；所有 `title IS NULL` 的会话也归为一个组 |
| `COUNT(*) AS conversation_count` | 统计每个标题分组中有多少个会话 |
| `ORDER BY title` | 按照标题升序排列统计结果；省略方向时默认使用 `ASC` |
| `NULLS LAST` | 将标题为 `NULL` 的分组放在非空标题之后 |

#### 7.10.1 NULLS LAST 是什么

`NULLS LAST` 是 `ORDER BY` 的排序选项。它表示：

> 排序时，将值为 `NULL` 的行放在所有非空值后面。

这里的 `NULL` 表示“没有标题”或“标题未知”，不是字符串 `'NULL'`，也不是空字符串 `''`。

假设 `conversations` 中有：

```text
id | title
---+----------------
 1 | Docker 学习
 2 | NULL
 3 | PostgreSQL 学习
 4 | NULL
 5 | Docker 学习
```

执行：

```sql
SELECT
  title,
  COUNT(*) AS conversation_count
FROM conversations
GROUP BY title
ORDER BY title NULLS LAST;
```

会先分组，再排序。结果类似：

```text
title           | conversation_count
----------------+-------------------
Docker 学习     |                  2
PostgreSQL 学习 |                  1
NULL            |                  2
```

最后一行表示有两个会话的标题为 `NULL`。`NULLS LAST` 让这一组显示在最后。

#### 7.10.2 NULLS FIRST 与 NULLS LAST

PostgreSQL 提供两个选项：

| 写法 | 含义 |
| --- | --- |
| `NULLS FIRST` | 将 `NULL` 放在非空值前面 |
| `NULLS LAST` | 将 `NULL` 放在非空值后面 |

对比：

```sql
-- 空标题排在前面
ORDER BY title ASC NULLS FIRST;

-- 空标题排在后面
ORDER BY title ASC NULLS LAST;
```

`ASC` 和 `DESC` 控制非空值的升降序；`NULLS FIRST` 和 `NULLS LAST` 单独控制空值放在什么位置。

#### 7.10.3 为什么脚本中没有写 ASC

下面两种写法等价：

```sql
ORDER BY title NULLS LAST;
```

```sql
ORDER BY title ASC NULLS LAST;
```

因为 `ORDER BY` 未明确写出方向时，默认使用 `ASC`。

PostgreSQL 的默认空值位置：

| 排序方向 | 未显式指定时的默认空值位置 |
| --- | --- |
| `ASC` | `NULLS LAST` |
| `DESC` | `NULLS FIRST` |

因此，原脚本即使简写为：

```sql
ORDER BY title;
```

在 PostgreSQL 中通常也会让 `NULL` 排在最后。但是显式写出 `NULLS LAST` 更容易表达业务意图：

```text
请按照标题排列，并将没有标题的会话统一放在最后。
```

如果按照标题降序排列，同时仍希望空标题放在最后，则必须覆盖默认行为：

```sql
ORDER BY title DESC NULLS LAST;
```

否则：

```sql
ORDER BY title DESC;
```

默认等价于：

```sql
ORDER BY title DESC NULLS FIRST;
```

更完整的普通排序讲解见 [02-SQL CRUD 与约束：`NULLS FIRST` 与 `NULLS LAST`](./02-sql-crud-and-constraints.md#38-nulls-first-与-nulls-last控制空值位置)。

### 7.11 使用 FILTER 在同一组内分别计数

Agent 应用经常需要在一次查询中统计不同类别。例如，统计每个会话中的用户消息和助手消息：

```sql
SELECT
  conversation_id,
  COUNT(*) AS total_count,
  COUNT(*) FILTER (WHERE role = 'user') AS user_count,
  COUNT(*) FILTER (WHERE role = 'assistant') AS assistant_count,
  COUNT(*) FILTER (WHERE role = 'system') AS system_count
FROM messages
GROUP BY conversation_id
ORDER BY conversation_id;
```

含义：

- `GROUP BY conversation_id`：每个会话形成一组。
- `COUNT(*)`：统计组内全部消息。
- **`FILTER (WHERE role = 'user')`：只让满足条件的行进入这一项计数。**

这样无需为每种角色分别执行一次查询。

### 7.12 GROUP BY 在 Agent 开发中的常见用途

| 需求 | 典型分组字段 | 常用聚合 |
| --- | --- | --- |
| 统计每个会话的消息数量 | `conversation_id` | `COUNT(*)` |
| 统计每种角色的消息数量 | `role` | `COUNT(*)` |
| 查找活跃会话 | `conversation_id` | `COUNT(*)`、`MAX(created_at)` |
| 统计每天的 Agent 运行次数 | 日期 | `COUNT(*)` |
| 统计每个状态的任务数量 | `status` | `COUNT(*)` |
| 计算工具调用平均耗时 | `tool_name` | `AVG(duration_ms)` |
| 查找失败次数较多的工具 | `tool_name` | `COUNT(*)` + `HAVING` |

当前工程还没有 `agent_runs` 或 `tool_calls` 表，但后续设计运行记录时会频繁使用这些统计方式。

## 8. 验证级联删除

继续在练习事务中执行：

```sql
DELETE FROM users
WHERE id = 100;

SELECT * FROM conversations
WHERE user_id = 100;

SELECT * FROM messages
WHERE conversation_id = 200;
```

如果外键和 `ON DELETE CASCADE` 正常，后两个查询都不会返回记录。

结束练习：

```sql
ROLLBACK;
```

回滚后，事务开始前的数据不会受到影响。

### 8.1 为什么这里使用事务

级联删除会一次性删除多层数据。学习时如果直接提交：

```text
DELETE users
  ↓
自动 DELETE conversations
  ↓
自动 DELETE messages
```

数据就真的消失了。

将实验包在事务中：

```sql
BEGIN;
-- 执行删除并观察结果
ROLLBACK;
```

可以安全观察级联行为，然后恢复到实验前状态。

### 8.2 事务的核心目标：原子性

原子性表示一组操作要么全部成功，要么全部失败。

假设业务需要：

1. 创建一个会话。
2. 写入会话的第一条消息。

如果第一步成功、第二步失败，数据库会留下没有任何消息的会话。把两个操作放在同一个事务中，失败时就可以整体回滚。

```sql
BEGIN;

INSERT INTO conversations (user_id, title)
VALUES (100, '事务练习');

-- 继续插入第一条消息

COMMIT;
```

发生错误时使用：

```sql
ROLLBACK;
```

## 9. 索引的基础认识

索引类似书籍目录，用于减少查询时需要扫描的数据量。

没有索引时，数据库可能需要逐行检查：

```text
读取第 1 行 → user_id 是否等于 100？
读取第 2 行 → user_id 是否等于 100？
读取第 3 行 → user_id 是否等于 100？
...
```

有合适索引时，数据库可以更快定位符合条件的行。

主键通常自带索引。可以使用下面的 SQL 查看当前索引：

```sql
SELECT
  tablename,
  indexname,
  indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
```

普通业务查询经常按外键过滤：

```sql
SELECT *
FROM conversations
WHERE user_id = 100;
```

数据量增长后，可以考虑为外键列增加索引：

```sql
CREATE INDEX IF NOT EXISTS idx_conversations_user_id
  ON conversations (user_id);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
  ON messages (conversation_id);
```

学习阶段先理解用途，不需要为每一列都创建索引。索引会占用空间，也会增加写入成本。

### 9.1 主键索引与外键索引不是一回事

声明主键：

```sql
id SERIAL PRIMARY KEY
```

PostgreSQL 会自动为主键创建唯一 **B-tree 索引**。

声明外键：

```sql
FOREIGN KEY (user_id) REFERENCES users(id)
```

PostgreSQL 不会自动为引用列 `conversations.user_id` 创建索引。数据量增长后，如果经常执行：

```sql
SELECT *
FROM conversations
WHERE user_id = 100;
```

通常应该考虑为 `user_id` 创建索引。

### 9.2 索引不是越多越好

索引会带来成本：

- 占用磁盘空间。
- `INSERT`、`UPDATE`、`DELETE` 时需要同步维护索引。
- 不合理的索引可能长期不被查询使用。

真实项目中，应结合实际查询和 `EXPLAIN` 或 `EXPLAIN ANALYZE` 判断索引是否有价值。

```sql
EXPLAIN
SELECT *
FROM conversations
WHERE user_id = 100;
```

## 10. 本章常见误区

| 误区 | 正确理解 |
| --- | --- |
| 有外键后，查询会自动带出关联表数据 | 外键只维护数据完整性，跨表读取仍然要写 `JOIN` |
| `JOIN` 总是一位用户输出一行 | 一个用户匹配多个会话时，会输出多行 |
| `JOIN` 和 `INNER JOIN` 不同 | 只写 `JOIN` 时，默认就是 `INNER JOIN` |
| `LEFT JOIN` 会保留两边全部数据 | 它只保证保留左表全部行 |
| `COUNT(*)` 总能统计右表记录数 | `LEFT JOIN` 中应注意 `NULL` 补位，常用 `COUNT(右表主键)` |
| `GROUP BY` 会修改表中的原始数据 | 分组只在当前查询中临时发生，原始行不会消失 |
| `GROUP BY` 与 `ORDER BY` 都是排序 | `GROUP BY` 用于归类，`ORDER BY` 用于排列最终结果 |
| 聚合条件可以直接写入 `WHERE` | `WHERE` 在分组前过滤行，聚合后的组使用 `HAVING` 过滤 |
| 建立外键会自动为外键列创建索引 | PostgreSQL 不会自动为引用列创建索引 |

## 官方参考资料

- [PostgreSQL 16: Joins Between Tables](https://www.postgresql.org/docs/16/tutorial-join.html)
- [PostgreSQL 16: Aggregate Functions Tutorial](https://www.postgresql.org/docs/16/tutorial-agg.html)
- [PostgreSQL 16: GROUP BY and HAVING Clauses](https://www.postgresql.org/docs/16/queries-table-expressions.html#QUERIES-GROUP)
- [PostgreSQL 16: Constraints](https://www.postgresql.org/docs/16/ddl-constraints.html)
- [PostgreSQL 16: Indexes](https://www.postgresql.org/docs/16/indexes.html)

## 完成标准

你应该能够回答：

1. `users`、`conversations`、`messages` 之间是什么关系。
2. 外键解决什么问题。
3. `ON DELETE CASCADE` 会产生什么效果。
4. `JOIN ... ON ...` 中的 `ON` 表达了什么。
5. 为什么索引不能无节制地增加。
6. `INNER JOIN` 与 `LEFT JOIN` 在右表没有匹配行时分别会发生什么。
7. 为什么统计会话数量时应使用 `COUNT(c.id)`，而不是直接使用 `COUNT(*)`。
8. `ON` 和 `WHERE` 分别在什么阶段起作用。
9. `GROUP BY` 如何将多行临时归为一组。
10. 为什么分组查询中的普通字段通常必须出现在 `GROUP BY` 中。
11. `WHERE` 与 `HAVING` 分别过滤什么。
12. `GROUP BY`、`ORDER BY` 和 `DISTINCT` 的用途有什么区别。
13. `NULLS FIRST` 与 `NULLS LAST` 如何控制排序结果中的空值位置。

下一章：[04. pgvector 与语义检索](./04-pgvector-and-semantic-search.md)
