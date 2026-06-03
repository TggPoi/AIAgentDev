# 09. 并发、性能与生产运维

会写 CRUD 只能说明应用可以访问数据库。Agent 服务上线后，还要面对：

- 多个请求同时修改相同数据。
- 多个 worker 同时领取任务。
- 消息、运行记录和知识库切片持续增长。
- 数据库结构需要升级，但旧数据不能删除。
- 应用凭据泄露、权限越界、误删除和磁盘故障。

本章解释如何建立最基本的生产意识。

## 1. 事务不仅用于手工练习

[03-表关系、JOIN 与事务](./03-relations-joins-and-transactions.md) 已经使用：

```sql
BEGIN;
-- 修改数据
ROLLBACK;
```

来保护练习数据。

真实业务中，事务用于保证一组操作具有原子性：

```text
创建 agent_run
写入第一条运行日志
更新 conversation 最后活跃时间
```

如果这三步构成一个不可拆分的业务动作，就应该放入同一个事务：

```sql
BEGIN;

INSERT INTO agent_runs (...);
INSERT INTO run_events (...);
UPDATE conversations SET ... WHERE id = ...;

COMMIT;
```

任何一步失败时：

```sql
ROLLBACK;
```

数据库回到事务开始前的状态。

## 2. ACID 要理解到什么程度

| 特性 | 含义 | Agent 场景示例 |
| --- | --- | --- |
| Atomicity 原子性 | 一组操作要么全部成功，要么全部失败 | 创建 run 和第一条 step 不能只成功一半 |
| Consistency 一致性 | 写入后仍然满足约束和业务规则 | `tool_call.run_id` 必须引用存在的 run |
| Isolation 隔离性 | 并发事务不能任意干扰彼此 | 两个 worker 不能都领取同一个任务 |
| Durability 持久性 | 提交后的数据在故障后仍应恢复 | Agent 运行结果不能只存在进程内存中 |

入门阶段不必背诵数据库理论术语，但必须能够判断：

- 哪些 SQL 必须一起提交？
- 哪些数据可以失败后重新生成？
- 哪些写入重复执行会造成错误？
- 哪些并发修改可能互相覆盖？

## 3. MVCC：读写并发的基础

PostgreSQL 使用 MVCC（Multi-Version Concurrency Control，多版本并发控制）。可以先建立简化认识：

- 一行数据更新后，数据库会管理不同版本的可见性。
- 普通读取不需要因为另一个事务正在修改数据就全部停住。
- 不同事务在不同隔离级别下，可能看到不同的数据快照。
- 旧版本最终需要通过 vacuum 机制清理。

因此，PostgreSQL 的并发不是“所有操作排队逐个执行”。但 MVCC 也不等于自动解决所有业务竞争。多个 worker 争抢同一个任务时，仍然需要明确的锁和状态更新。

## 4. 隔离级别：控制事务能看到什么

PostgreSQL 支持：

| 隔离级别 | 适合先建立的认识 |
| --- | --- |
| `READ COMMITTED` | 默认级别。每条语句开始时读取当时已提交的数据 |
| `REPEATABLE READ` | 同一事务中的多次读取保持一致快照 |
| `SERIALIZABLE` | 尽量提供类似串行执行的效果，出现冲突时应用需要重试 |

PostgreSQL 中即使写 `READ UNCOMMITTED`，实际行为也按 `READ COMMITTED` 处理。

设置示例：

```sql
BEGIN;
SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;
-- 执行业务 SQL
COMMIT;
```

不要把所有事务一律提高到 `SERIALIZABLE`。隔离越强，并发冲突和重试成本通常越高。应该根据业务正确性要求选择。

## 5. 行锁：防止多个 worker 同时处理同一任务

假设任务表：

```sql
CREATE TABLE agent_jobs (
  id BIGSERIAL PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  payload JSONB NOT NULL,
  available_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  locked_at TIMESTAMPTZ,
  locked_by TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

多个 worker 领取任务时，可以在一个事务中执行：

```sql
BEGIN;

SELECT id
FROM agent_jobs
WHERE status = 'queued'
  AND available_at <= CURRENT_TIMESTAMP
ORDER BY id
FOR UPDATE SKIP LOCKED
LIMIT 1;

UPDATE agent_jobs
SET
  status = 'running',
  locked_at = CURRENT_TIMESTAMP,
  locked_by = 'worker-01',
  attempt_count = attempt_count + 1
WHERE id = 123;

COMMIT;
```

关键词：

| 语法 | 作用 |
| --- | --- |
| `FOR UPDATE` | 锁住选中的任务行，避免其他事务同时修改 |
| `SKIP LOCKED` | 如果其他 worker 已锁住某行，不等待，继续找下一条 |
| `LIMIT 1` | 每次只领取一条 |

生产代码通常会把“选中并更新”组合得更紧凑，例如使用 CTE 和 `UPDATE ... RETURNING`：

```sql
WITH next_job AS (
  SELECT id
  FROM agent_jobs
  WHERE status = 'queued'
    AND available_at <= CURRENT_TIMESTAMP
  ORDER BY id
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE agent_jobs AS j
SET
  status = 'running',
  locked_at = CURRENT_TIMESTAMP,
  locked_by = $1,
  attempt_count = attempt_count + 1
FROM next_job
WHERE j.id = next_job.id
RETURNING j.*;
```

这类模式适合中小规模后台任务。吞吐量、路由和消息语义要求更复杂时，再评估专用消息队列。

## 6. 事务必须复用同一个数据库连接

当前工程将普通查询封装为：

```js
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

export const query = (text, params) => pool.query(text, params);
```

源码见 [`src/db.mjs` L6-L12](../src/db.mjs#L6)。

`pool.query(...)` 适合单条 SQL。但事务中的多条 SQL 必须在同一个 client 上执行：

```js
const client = await pool.connect();

try {
  await client.query("BEGIN");
  await client.query("INSERT INTO ...", paramsA);
  await client.query("UPDATE ...", paramsB);
  await client.query("COMMIT");
} catch (error) {
  await client.query("ROLLBACK");
  throw error;
} finally {
  client.release();
}
```

原因：

- 事务属于某一条具体数据库连接。
- 连续调用 `pool.query(...)` 时，连接池可能为不同语句分配不同连接。
- 在连接 A 上执行 `BEGIN`，再在连接 B 上执行 `UPDATE`，无法组成同一个事务。

## 7. 死锁：不是数据库故障，而是需要处理的并发情况

假设两个事务按不同顺序锁定任务：

```text
事务 A 已锁定任务 1，等待任务 2
事务 B 已锁定任务 2，等待任务 1
```

两边互相等待，就形成死锁。PostgreSQL 会检测死锁，并终止其中一个事务。

降低风险：

1. 多行更新时尽量按稳定顺序加锁，例如始终按 `id ASC`。
2. 事务尽量短，不要在事务中等待用户输入或调用耗时模型 API。
3. 应用捕获可重试错误，并带有限次数和退避策略地重试。
4. 不要把事务打开后长时间闲置。

Agent 调用大模型可能持续数秒甚至更久。常见设计是：

```text
短事务：领取任务并提交
事务外：调用模型或工具
短事务：保存结果并更新状态
```

不要为了“保证原子性”而在一个长事务里等待外部 HTTP 请求。

## 8. 索引：为真实查询服务

当前工程已经在 SQL 脚本中声明 HNSW 索引：

```sql
CREATE INDEX IF NOT EXISTS idx_messages_embedding
    ON messages USING hnsw (embedding vector_cosine_ops);
```

源码见 [`init-scripts/create_tables.sql` L36-L37](../create_tables.sql#L36)。

但 Agent 应用不只有向量检索。常见索引类型：

| 索引类型 | 常见用途 |
| --- | --- |
| B-tree | 等值过滤、范围过滤、排序、主键、时间分页 |
| GIN | `jsonb` 包含查询、数组、全文检索 |
| HNSW | pgvector 近似最近邻搜索 |
| IVFFlat | pgvector 另一种近似最近邻索引，需要理解训练和参数 |
| BRIN | 超大表中与物理顺序高度相关的列，例如持续递增时间 |

入门和大多数业务查询先掌握 B-tree、GIN、HNSW。

## 9. 外键不会自动创建引用列索引

当前工程有：

```sql
FOREIGN KEY (user_id) REFERENCES users(id)
```

以及：

```sql
FOREIGN KEY (conversation_id) REFERENCES conversations(id)
```

源码：

- [`conversations.user_id`](../create_tables.sql#L17)
- [`messages.conversation_id`](../create_tables.sql#L30)

主键会自动拥有唯一索引，但外键的引用列通常需要根据查询单独建索引：

```sql
CREATE INDEX idx_conversations_user_id
  ON conversations (user_id);

CREATE INDEX idx_messages_conversation_id
  ON messages (conversation_id);
```

原因：

- 经常按用户查询会话。
- 经常按会话查询消息。
- 删除父记录时，数据库也需要检查相关子记录。

索引是否需要创建，最终仍然应该结合数据规模和实际查询验证。

## 10. 复合索引：列顺序必须匹配查询

游标分页查询：

```sql
SELECT id, conversation_id, role, content, created_at
FROM messages
WHERE conversation_id = $1
  AND (created_at, id) < ($2, $3)
ORDER BY created_at DESC, id DESC
LIMIT 20;
```

推荐索引：

```sql
CREATE INDEX idx_messages_conversation_created_id
  ON messages (conversation_id, created_at DESC, id DESC);
```

顺序表达了查询路径：

1. 先按 `conversation_id` 定位一个会话。
2. 再按 `created_at` 和 `id` 从新到旧遍历。

复合索引不是“把常用列随便放在一起”。应该从具体 `WHERE` 和 `ORDER BY` 出发设计。

## 11. 部分索引：只索引真正需要的行

任务表中，worker 通常只关心待领取任务：

```sql
WHERE status = 'queued'
  AND available_at <= CURRENT_TIMESTAMP
```

可以考虑部分索引：

```sql
CREATE INDEX idx_agent_jobs_queued_available
  ON agent_jobs (available_at, id)
  WHERE status = 'queued';
```

优点：

- 索引更小。
- 已成功任务不会占据这个索引。
- 领取任务查询更聚焦。

代价：

- 只对满足索引条件的查询有用。
- 条件变化后需要重新评估。

## 12. 向量索引：准确率和速度之间有权衡

pgvector 默认可以执行精确最近邻搜索。增加 HNSW 或 IVFFlat 索引后，可以执行近似最近邻搜索，以一定召回率代价换取速度。

当前工程使用：

```sql
embedding vector(1024)
```

和：

```sql
embedding vector_cosine_ops
```

对应源码：

- [`vector(1024)`](../create_tables.sql#L28)
- [`vector_cosine_ops`](../create_tables.sql#L37)

必须掌握：

- 使用 `<=>` 余弦距离时，索引 operator class 应与余弦距离匹配。
- 不同距离算法通常需要不同索引。
- `NULL` 向量不会进入向量索引。
- 过滤条件和近似检索组合后，返回数量和召回率需要实测。
- 小数据量时，精确搜索可能已经足够。
- 向量模型、维度和版本需要受控管理。

不要只看到 HNSW 索引存在就断言查询已经优化。必须查看实际执行计划，并用真实数据验证召回质量。

## 13. 使用 EXPLAIN ANALYZE 验证查询

`EXPLAIN` 显示 PostgreSQL 计划如何执行查询：

```sql
EXPLAIN
SELECT *
FROM messages
WHERE conversation_id = 1;
```

`EXPLAIN ANALYZE` 会真正执行查询，并显示实际耗时和实际行数：

```sql
EXPLAIN ANALYZE
SELECT *
FROM messages
WHERE conversation_id = 1;
```

对修改数据的 SQL 要谨慎。可以包在事务中回滚：

```sql
BEGIN;

EXPLAIN ANALYZE
UPDATE messages
SET content = 'test'
WHERE id = 1;

ROLLBACK;
```

先认识几个常见节点：

| 节点 | 含义 |
| --- | --- |
| `Seq Scan` | 顺序扫描整张表 |
| `Index Scan` | 使用索引找到行，再访问表 |
| `Index Only Scan` | 查询所需信息可以主要从索引获得 |
| `Bitmap Index Scan` | 先通过索引生成候选位置集合 |
| `Sort` | 执行排序 |
| `Nested Loop`、`Hash Join` | 不同 JOIN 执行策略 |

小表出现 `Seq Scan` 不一定是问题。表很小时，直接扫描可能比读取索引更快。不要为了“看见 Index Scan”而强行调整配置。

## 14. ANALYZE 和 autovacuum 为什么重要

PostgreSQL 的查询规划器需要统计信息估算：

- 某个条件大约会命中多少行。
- 顺序扫描还是索引扫描更划算。
- JOIN 应该采用什么执行顺序和算法。

`ANALYZE` 会更新统计信息：

```sql
ANALYZE messages;
```

MVCC 会产生不再需要的旧行版本。`VACUUM` 用于维护这些数据：

```sql
VACUUM ANALYZE messages;
```

日常通常由 autovacuum 自动处理。你需要知道：

- 不要随意关闭 autovacuum。
- 大量批量写入后，统计信息可能需要更新。
- 长事务会阻碍旧版本清理。
- 表持续膨胀、查询计划估算严重偏差时，要检查 vacuum 和 analyze 状态。

## 15. Migration：初始化脚本不能替代结构升级

当前工程挂载：

```yaml
- ./init-scripts:/docker-entrypoint-initdb.d
```

源码见 [`docker-compose.yml` L15](../docker-compose.yml#L15)。

这些初始化脚本通常只在数据目录首次初始化时执行。[05-pgsql-test 工程拆解](./05-pgsql-test-project.md) 已经详细说明这一点。

真实项目需要 migration：

```text
001_create_users.sql
002_create_conversations.sql
003_create_messages.sql
004_add_message_embedding.sql
005_add_agent_runs.sql
```

Migration 的目标：

- 每次结构变更都有版本记录。
- 已有环境可以从旧版本升级。
- 团队成员、测试环境和生产环境执行相同变更。
- 回滚策略和数据兼容性可以评审。

不要依赖：

- 删除数据库目录后重新初始化。
- 手工在 pgAdmin 中改表但不记录 SQL。
- 在生产环境开启 ORM 自动同步并希望它自动处理一切。

## 16. 数据库 role 和最小权限

当前教学环境使用：

```yaml
POSTGRES_USER: user
POSTGRES_PASSWORD: 123456
```

源码见 [`docker-compose.yml` L8-L9](../docker-compose.yml#L8)。

这只适合本地学习。生产环境应该：

1. 使用专门的 migration role 修改结构。
2. 使用权限受限的应用 role 读写业务表。
3. 不让普通应用连接使用超级用户。
4. 从安全的密钥管理系统注入密码。
5. 定期轮换凭据。

学习示例：

```sql
CREATE ROLE agent_app LOGIN PASSWORD 'replace-me';

GRANT CONNECT ON DATABASE hello_pg TO agent_app;
GRANT USAGE ON SCHEMA public TO agent_app;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON TABLE users, conversations, messages
  TO agent_app;
GRANT USAGE, SELECT
  ON ALL SEQUENCES IN SCHEMA public
  TO agent_app;
```

这是概念示例。不要把示例密码直接用于生产环境。

## 17. RLS：多租户隔离的数据库防线

如果你还不理解“租户”和 `tenant_id`，先阅读 [07-知识地图中的租户字段](./07-agent-development-postgresql-roadmap.md#61-租户字段)。RLS 是建立在清晰租户建模之上的数据库层保护。

如果多个租户共享同一张表，可以考虑 Row-Level Security：

```sql
ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_chunks_policy
ON knowledge_chunks
USING (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

理解目标：

- 普通应用即使忘记在某条查询中写 `WHERE tenant_id = ...`，数据库策略仍可以阻止越权读取。
- 插入和更新也要设计对应检查条件。

RLS 不是“加一行 SQL 就自动安全”：

- 超级用户和具有 `BYPASSRLS` 的 role 可以绕过策略。
- 表 owner 通常也会绕过策略，除非额外强制。
- 连接池复用连接时，租户上下文设置和清理必须严格控制。
- migration、后台任务和运维查询需要单独设计权限。

入门阶段先理解用途。真正启用前，需要为越权场景编写集成测试。

## 18. 备份和恢复必须一起练习

只执行备份命令，但从未验证恢复，不算完成备份设计。

本地逻辑备份示例：

```powershell
docker exec pg_vector_db pg_dump -U user -d hello_pg -Fc -f /tmp/hello_pg.dump
docker cp pg_vector_db:/tmp/hello_pg.dump ./hello_pg.dump
```

恢复前应该创建一个新的练习数据库，不要覆盖正在使用的数据：

```powershell
docker exec pg_vector_db createdb -U user hello_pg_restore_test
docker cp ./hello_pg.dump pg_vector_db:/tmp/hello_pg.dump
docker exec pg_vector_db pg_restore -U user -d hello_pg_restore_test /tmp/hello_pg.dump
```

然后验证：

```powershell
docker exec -it pg_vector_db psql -U user -d hello_pg_restore_test
```

在 `psql` 中检查：

```sql
\dt
SELECT COUNT(*) FROM users;
SELECT COUNT(*) FROM conversations;
SELECT COUNT(*) FROM messages;
```

完成验证后，再决定何时删除练习数据库。

生产环境还需要明确：

- 备份频率。
- 保留周期。
- 备份文件加密和访问权限。
- 恢复时间目标。
- 可接受的数据丢失范围。
- 谁负责定期执行恢复演练。

## 19. 基础监控：先会回答这些问题

出现数据库问题时，至少要能回答：

| 问题 | 常用方向 |
| --- | --- |
| 当前有哪些长时间运行查询？ | `pg_stat_activity` |
| 是否有事务长时间不提交？ | `pg_stat_activity` |
| 哪些锁正在等待？ | `pg_locks` |
| 表大约有多少活跃行和失效行？ | `pg_stat_user_tables` |
| 索引是否被使用？ | `pg_stat_user_indexes` |
| 某条 SQL 为什么慢？ | `EXPLAIN (ANALYZE, BUFFERS)` |
| autovacuum 是否正常工作？ | `pg_stat_user_tables` 和日志 |

学习查询：

```sql
SELECT
  pid,
  state,
  query_start,
  wait_event_type,
  wait_event,
  query
FROM pg_stat_activity
WHERE datname = current_database()
ORDER BY query_start;
```

查看用户表统计：

```sql
SELECT
  relname,
  n_live_tup,
  n_dead_tup,
  last_autovacuum,
  last_autoanalyze
FROM pg_stat_user_tables
ORDER BY relname;
```

## 20. 连接池与超时

连接池可以复用数据库连接。当前工程使用 `pg.Pool`：

```js
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});
```

源码见 [`src/db.mjs` L6-L8](../src/db.mjs#L6)。

生产环境还要考虑：

- 应用实例数量乘以每个实例连接池大小，是否超过数据库可承受连接数。
- SQL 是否有合理超时。
- 事务是否可能长时间空闲。
- 外部模型调用是否错误地放在事务内部。
- 服务退出时是否正确释放连接。

当前一次性脚本在结束时调用：

```js
await pool.end();
```

源码见 [`src/index.mjs` L121-L126](../src/index.mjs#L121)。

长时间运行的 Web 服务通常不会在每次请求后关闭整个连接池，而是在进程关闭时统一清理。

## 21. Agent 项目上线前的数据库检查清单

### 数据正确性

- [ ] 核心表有主键。
- [ ] 关联关系有外键。
- [ ] 有限状态有 `CHECK` 或等价约束。
- [ ] 关键写入考虑幂等性。
- [ ] embedding 保存模型、维度和版本信息。
- [ ] 多租户检索不会漏掉租户过滤。

### 并发

- [ ] 多 worker 领取任务不会重复执行。
- [ ] 事务中的 SQL 复用同一连接。
- [ ] 外部 HTTP 调用不占用长事务。
- [ ] 可重试错误有有限次数、日志和退避策略。

### 性能

- [ ] 高频查询有对应索引。
- [ ] 外键引用列是否需要索引已经评估。
- [ ] 分页使用稳定排序。
- [ ] 向量索引的召回率和速度使用真实数据验证。
- [ ] 慢 SQL 使用 `EXPLAIN ANALYZE` 检查。

### 结构演进

- [ ] 使用 migration 管理结构变化。
- [ ] migration 在测试环境验证过。
- [ ] 不依赖删除数据目录重新初始化。
- [ ] 不依赖生产 ORM 自动同步。

### 安全与恢复

- [ ] 应用不使用超级用户连接。
- [ ] 密码不写死在源码。
- [ ] 有定期备份。
- [ ] 已经做过恢复演练。
- [ ] 可以查看活动查询、锁等待和表统计。

## 22. 本章练习

### 练习 1：观察查询计划

1. 对按 `conversation_id` 查询消息的 SQL 执行 `EXPLAIN ANALYZE`。
2. 创建 `idx_messages_conversation_id`。
3. 再次执行 `EXPLAIN ANALYZE`。
4. 解释为什么数据量很小时，数据库仍可能选择 `Seq Scan`。

### 练习 2：模拟任务领取

1. 在单独的学习表中创建三条 `queued` 任务。
2. 开启两个 `psql` 窗口。
3. 在第一个窗口中执行 `BEGIN` 和 `SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1`，暂不提交。
4. 在第二个窗口执行相同 SQL。
5. 观察两个窗口是否领取不同任务。
6. 最后回滚并删除学习表。

### 练习 3：验证备份恢复

1. 使用 `pg_dump` 导出当前数据库。
2. 恢复到新的练习数据库。
3. 核对三张表和记录数量。
4. 记录恢复过程，而不是只保留备份文件。

## 23. 完成标准

- [ ] 我能解释事务为什么必须复用同一连接。
- [ ] 我能解释为什么模型 API 调用不应该放在长事务中。
- [ ] 我能使用 `FOR UPDATE SKIP LOCKED` 描述任务领取流程。
- [ ] 我知道 B-tree、GIN 和 HNSW 分别解决什么问题。
- [ ] 我能使用 `EXPLAIN ANALYZE` 开始排查慢查询。
- [ ] 我知道初始化脚本不能替代 migration。
- [ ] 我知道为什么生产应用不能使用超级用户连接。
- [ ] 我已经理解“备份成功”与“恢复验证成功”的区别。

## 官方参考资料

- [PostgreSQL 16 Transaction Isolation](https://www.postgresql.org/docs/16/transaction-iso.html)
- [PostgreSQL 16 Explicit Locking](https://www.postgresql.org/docs/16/explicit-locking.html)
- [PostgreSQL 16 SELECT Locking Clause](https://www.postgresql.org/docs/16/sql-select.html#SQL-FOR-UPDATE-SHARE)
- [PostgreSQL 16 Indexes](https://www.postgresql.org/docs/16/indexes.html)
- [PostgreSQL 16 Examining Index Usage](https://www.postgresql.org/docs/16/indexes-examine.html)
- [PostgreSQL 16 EXPLAIN](https://www.postgresql.org/docs/16/sql-explain.html)
- [PostgreSQL 16 Routine Vacuuming](https://www.postgresql.org/docs/16/routine-vacuuming.html)
- [PostgreSQL 16 Privileges](https://www.postgresql.org/docs/16/ddl-priv.html)
- [PostgreSQL 16 Row Security Policies](https://www.postgresql.org/docs/16/ddl-rowsecurity.html)
- [PostgreSQL 16 Backup and Restore](https://www.postgresql.org/docs/16/backup.html)
- [PostgreSQL 16 Monitoring Database Activity](https://www.postgresql.org/docs/16/monitoring.html)
- [node-postgres Pool API](https://node-postgres.com/apis/pool)
- [pgvector README](https://github.com/pgvector/pgvector)
