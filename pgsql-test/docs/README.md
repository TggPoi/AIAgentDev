# PostgreSQL 学习路线

这套文档根据教程原文 [`PostgreSQL_Learn.md`](../PostgreSQL_Learn.md) 和当前 `pgsql-test` 工程整理。

目标不是只读懂当前示例，而是先建立数据库基础，再逐步掌握 Agent 开发必须具备的数据建模、查询、检索、并发、性能和生产运维能力。

## 学习顺序

请按下面的顺序学习。每章结尾都有检查项。

| 顺序 | 文档 | 目标 |
| --- | --- | --- |
| 1 | [01-数据库与 PostgreSQL 基础](./01-database-and-postgresql-basics.md) | 理解数据库、表、行、列、主键，并能进入 `psql` |
| 2 | [02-SQL CRUD 与约束](./02-sql-crud-and-constraints.md) | 掌握增删改查，理解字段类型和约束 |
| 3 | [03-表关系、JOIN 与事务](./03-relations-joins-and-transactions.md) | 理解一对多关系、外键、级联删除和关联查询 |
| 4 | [04-pgvector 与语义检索](./04-pgvector-and-semantic-search.md) | 理解向量、余弦距离、HNSW 索引和语义检索 SQL |
| 5 | [05-pgsql-test 工程拆解](./05-pgsql-test-project.md) | 将前面的知识映射到当前工程 |
| 6 | [06-练习清单](./06-practice-checklist.md) | 按顺序动手练习并自检 |
| 7 | [07-Agent 开发所需的 PostgreSQL 知识地图](./07-agent-development-postgresql-roadmap.md) | 明确必须掌握、按需深入和暂缓学习的知识 |
| 8 | [08-高级查询、JSONB 与混合检索](./08-advanced-query-jsonb-and-hybrid-search.md) | 掌握复杂 SQL、半结构化数据、全文检索和混合召回 |
| 9 | [09-并发、性能与生产运维](./09-concurrency-performance-and-operations.md) | 掌握并发任务处理、索引验证、迁移、安全和恢复 |

## Agent 开发必须掌握的能力

当前工程是学习入口，不是知识边界。开发 Agent 应用时，至少需要逐步掌握：

| 能力 | 需要解决的问题 |
| --- | --- |
| 关系建模和约束 | 用户、会话、消息、运行记录、工具调用和知识库如何可靠关联 |
| 高级 SQL | 如何使用 JOIN、聚合、子查询、CTE、窗口函数和 UPSERT 组织业务查询 |
| Agent 检索 | 如何组合 `jsonb` metadata、全文关键词、向量相似度和租户过滤 |
| 事务和并发 | 如何防止多个 worker 重复领取任务，如何安全重试 |
| 索引和性能 | 如何为真实查询设计 B-tree、GIN、HNSW 索引，并使用 `EXPLAIN ANALYZE` 验证 |
| 工程化 | 如何使用连接池、参数化查询、migration、最小权限、备份恢复和监控 |

完整知识清单和学习优先级见 [07-Agent 开发所需的 PostgreSQL 知识地图](./07-agent-development-postgresql-roadmap.md)。

## 当前工程解决的问题

教程用聊天记录场景说明 PostgreSQL 的用途：

```text
users
  └── conversations
        └── messages
              └── embedding
```

- 一个用户可以有多个会话。
- 一个会话可以有多条消息。
- 每条消息可以保存一个向量，用于语义相似度检索。
- 业务数据和向量数据都保存在 PostgreSQL 中，可以结合普通条件、关联查询和向量检索。

## 源码导航

阅读文档时，可以通过下面的入口直接跳转到当前工程源码：

| 源码 | 用途 |
| --- | --- |
| [`docker-compose.yml` L1](../docker-compose.yml#L1) | 启动 PostgreSQL 和 pgAdmin |
| [`docker-compose.yml` L14](../docker-compose.yml#L14) | PostgreSQL 数据目录挂载 |
| [`docker-compose.yml` L15](../docker-compose.yml#L15) | 初始化脚本目录挂载 |
| [`init-scripts/create_tables.sql` L2](../init-scripts/create_tables.sql#L2) | 启用 pgvector 扩展 |
| [`init-scripts/create_tables.sql` L5](../init-scripts/create_tables.sql#L5) | 定义 `users` 表 |
| [`init-scripts/create_tables.sql` L12](../init-scripts/create_tables.sql#L12) | 定义 `conversations` 表 |
| [`init-scripts/create_tables.sql` L23](../init-scripts/create_tables.sql#L23) | 定义 `messages` 表 |
| [`src/db.mjs` L6](../src/db.mjs#L6) | 创建数据库连接池 |
| [`src/users.mjs` L3](../src/users.mjs#L3) | 用户 CRUD |
| [`src/conversations.mjs` L3](../src/conversations.mjs#L3) | 会话 CRUD |
| [`src/messages.mjs` L22](../src/messages.mjs#L22) | 消息 CRUD 和向量写入 |
| [`src/messages.mjs` L92](../src/messages.mjs#L92) | 语义检索 |
| [`src/index.mjs` L6](../src/index.mjs#L6) | 演示入口 |

## 开始前检查环境

在工程根目录执行：

```powershell
docker compose up -d
docker compose ps
```

PostgreSQL 服务正常时，`pg_vector_db` 应显示为 `healthy`。

进入 PostgreSQL 命令行：

```powershell
docker exec -it pg_vector_db psql -U user -d hello_pg
```

看到下面形式的提示符，表示已经进入数据库：

```text
hello_pg=#
```

退出 `psql`：

```text
\q
```

## 使用 pgAdmin

浏览器访问：

```text
http://localhost:8088/
```

登录账号来自 [`docker-compose.yml` L27-L29](../docker-compose.yml#L27)：

```text
邮箱：admin@admin.com
密码：admin
```

首次在 pgAdmin 中注册数据库服务器时，填写：

```text
Host name/address: postgres
Port:              5432
Maintenance DB:    hello_pg
Username:          user
Password:          123456
```

`postgres` 是 Compose 网络中的服务名。只有从 Windows 主机直接连接数据库时，才使用 `localhost:5432`。

## 已核对的工程状态

在 2026-06-02 重新核对这些文档时，当前运行环境中：

- PostgreSQL 容器健康。
- `vector` 扩展已安装，版本为 `0.8.2`。
- `users`、`conversations`、`messages` 三张表已存在。
- 运行中的数据库尚未显示 `messages.role` 的 `CHECK` 约束。
- 运行中的数据库尚未显示 `idx_messages_embedding` HNSW 索引。
- 当前 `.env` 已经包含 `DATABASE_URL`，[`src/db.mjs` L6-L8](../src/db.mjs#L6) 会使用它连接数据库。

脚本内容和数据库实际结构可能不同。原因及处理方式见 [05-pgsql-test 工程拆解](./05-pgsql-test-project.md)。

## 学习原则

1. 先用 `psql` 手写 SQL，再阅读 Node.js 代码。
2. 每次只练习一个概念。
3. 修改或删除数据前先确认 `WHERE` 条件。
4. 不要为了重新执行初始化脚本而直接删除 `volumes/postgres`。该目录保存数据库数据。
5. `pgAdmin` 是图形化工具，不是数据库本身。遇到问题时，优先用 `psql` 验证数据库。
6. 不要只复制 SQL。执行前先预测结果，执行后再解释为什么得到这个结果。
7. 遇到相近概念时，主动做对比实验。例如分别执行 `INNER JOIN` 和 `LEFT JOIN`，观察结果集中缺少了哪些行。

## 官方参考资料

- [PostgreSQL 16 Tutorial](https://www.postgresql.org/docs/16/tutorial.html)
- [PostgreSQL 16 SQL Language](https://www.postgresql.org/docs/16/tutorial-sql.html)
- [PostgreSQL 16 JSON Types](https://www.postgresql.org/docs/16/datatype-json.html)
- [PostgreSQL 16 Indexes](https://www.postgresql.org/docs/16/indexes.html)
- [PostgreSQL 16 Concurrency Control](https://www.postgresql.org/docs/16/mvcc.html)
- [PostgreSQL 16 Full Text Search](https://www.postgresql.org/docs/16/textsearch.html)
- [PostgreSQL Docker Official Image README](https://github.com/docker-library/docs/blob/master/postgres/README.md)
- [pgvector README](https://github.com/pgvector/pgvector)
- [pgAdmin Container Deployment](https://www.pgadmin.org/docs/pgadmin4/latest/container_deployment.html)
