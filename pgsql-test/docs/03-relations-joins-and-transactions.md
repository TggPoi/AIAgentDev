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

### 对照关联相关源码

| 操作 | Node.js 实现 |
| --- | --- |
| 新增会话并保存 `user_id` | [`createConversation()` L3-L8](../src/conversations.mjs#L3) |
| 查询某个用户的全部会话 | [`getConversationsByUserId()` L19-L24](../src/conversations.mjs#L19) |
| 新增消息并保存 `conversation_id` | [`createMessage()` L22-L44](../src/messages.mjs#L22) |
| 查询某个会话的全部消息 | [`getMessagesByConversationId()` L56-L64](../src/messages.mjs#L56) |

## 5. 使用 JOIN 跨表查询

`JOIN` 用于根据关联条件组合多张表。

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

## 6. INNER JOIN 与 LEFT JOIN

只写 `JOIN` 时，默认是 `INNER JOIN`：

```sql
SELECT *
FROM users AS u
JOIN conversations AS c
  ON c.user_id = u.id;
```

它只返回“至少有一个会话”的用户。

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

## 7. 聚合统计

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

## 9. 索引的基础认识

索引类似书籍目录，用于减少查询时需要扫描的数据量。

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

## 完成标准

你应该能够回答：

1. `users`、`conversations`、`messages` 之间是什么关系。
2. 外键解决什么问题。
3. `ON DELETE CASCADE` 会产生什么效果。
4. `JOIN ... ON ...` 中的 `ON` 表达了什么。
5. 为什么索引不能无节制地增加。

下一章：[04. pgvector 与语义检索](./04-pgvector-and-semantic-search.md)
