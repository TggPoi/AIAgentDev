# 07. Agent 开发所需的 PostgreSQL 知识地图

当前工程是一个很好的起点，但它只覆盖了 Agent 数据库能力的一部分：

- [`users`](../create_tables.sql#L5) 保存用户。
- [`conversations`](../create_tables.sql#L12) 保存会话。
- [`messages`](../create_tables.sql#L23) 保存消息和 embedding。
- [`searchSimilarMessages()`](../src/messages.mjs#L92) 根据向量距离召回历史消息。

真实 Agent 应用还会遇到运行状态、工具调用、知识库文档、切片、检索过滤、并发写入、结构迁移、权限隔离和故障恢复。学习 PostgreSQL 时，不要只把目标定为“能写 CRUD”，而要逐步建立一套能支撑 Agent 业务的数据库能力。

## 1. 先区分三个学习优先级

### 1.1 必须掌握

这些知识会直接影响数据正确性、查询性能和线上可靠性。学习 Agent 开发时不能跳过：

| 类别 | 必须掌握的知识点 | Agent 场景中的用途 |
| --- | --- | --- |
| 数据库基础 | 服务、数据库、schema、表、行、列、主键、外键 | 看懂数据存在哪里，理解表之间如何关联 |
| 数据类型 | `text`、整数、布尔值、`timestamptz`、`uuid`、`jsonb`、`vector` | 保存消息、状态、元数据、标识符和 embedding |
| 约束 | `NOT NULL`、`DEFAULT`、`PRIMARY KEY`、`UNIQUE`、`CHECK`、`FOREIGN KEY` | 在数据库层拒绝非法状态 |
| 基础 SQL | `INSERT`、`SELECT`、`UPDATE`、`DELETE`、`WHERE`、`ORDER BY`、`LIMIT` | 实现最基本的数据读写 |
| 关联查询 | `INNER JOIN`、`LEFT JOIN`、聚合、`GROUP BY` | 查询用户、会话、消息和统计信息 |
| 高级查询 | 子查询、CTE、窗口函数、`INSERT ... ON CONFLICT` | 组织复杂检索、排序和幂等写入 |
| 事务 | `BEGIN`、`COMMIT`、`ROLLBACK`、原子性、隔离级别 | 保证多步 Agent 操作要么全部成功，要么全部失败 |
| 并发控制 | MVCC、行锁、`SELECT ... FOR UPDATE`、死锁重试 | 防止多个 worker 重复执行同一个任务 |
| 索引 | B-tree、复合索引、部分索引、GIN、HNSW、`EXPLAIN ANALYZE` | 让会话列表、状态过滤、JSONB 和向量检索可扩展 |
| 检索 | `jsonb`、全文检索、向量检索、元数据过滤、混合检索 | 实现 Agent 的长期记忆和知识库召回 |
| 应用接入 | 参数化查询、连接池、事务必须复用同一连接、分页 | 正确地从 Node.js 或 ORM 调用 PostgreSQL |
| 结构演进 | migration、初始化脚本与 migration 的区别 | 让已经存在的数据可以随版本升级 |
| 安全 | role、`GRANT`、最小权限、密钥管理、按租户隔离 | 避免所有服务都用超级用户访问数据库 |
| 运维 | 备份恢复、autovacuum、监控、慢查询排查 | 数据出问题时能够恢复，并定位性能瓶颈 |

现有 `01` 到 `06` 文档覆盖了上表的前半部分。后续章节会补齐 Agent 开发中最容易遗漏的内容。

### 1.2 出现对应需求后深入

这些知识很重要，但不需要在第一个 Agent 项目开始前全部掌握：

| 知识点 | 何时学习 |
| --- | --- |
| Row-Level Security（RLS） | 一个数据库服务多个用户、团队或租户，并且必须在数据库层隔离数据时 |
| 表分区 partitioning | 单张消息表、运行事件表或日志表增长到很大，维护和查询开始变慢时 |
| 读副本、流复制、高可用 | 需要容灾、读扩展或严格可用性指标时 |
| 逻辑复制、CDC | 需要把 PostgreSQL 变更同步到搜索引擎、数仓或事件系统时 |
| advisory lock | 需要对“业务资源”加锁，但资源不适合直接映射为某一行时 |
| 物化视图 | 统计查询代价高，但允许定期刷新而不是每次实时计算时 |
| 自定义函数、触发器 | 数据规则必须在数据库端集中执行，并且团队能承担调试复杂度时 |

### 1.3 暂时不必深入

下面内容不是 Agent 应用入门阶段的优先项：

- PostgreSQL 内核实现细节。
- 自定义索引访问方法。
- 自定义数据类型。
- 复杂存储参数调优。
- 手工管理 WAL 文件。

知道这些能力存在即可。先把数据建模、查询、事务、索引和运维基本功练扎实。

## 2. Agent 应用中的数据不是只有聊天记录

一个实际 Agent 系统通常需要区分以下数据：

| 数据类别 | 典型内容 | 是否适合放 PostgreSQL |
| --- | --- | --- |
| 身份数据 | 用户、团队、租户、API key 元数据 | 适合 |
| 会话数据 | conversation、thread、message | 适合 |
| 运行数据 | run、step、tool call、状态、错误信息 | 适合 |
| 检查点 | Agent 在某一步的可恢复状态 | 适合，常用 `jsonb` |
| 知识库元数据 | 文档来源、标题、更新时间、标签、权限 | 适合 |
| 文档切片 | chunk 文本、顺序、metadata、embedding | 适合 |
| 原始大文件 | PDF、图片、音视频 | 通常放对象存储，PostgreSQL 保存地址和元数据 |
| 队列消息 | 待执行任务、重试任务 | 可以保存状态，但高吞吐队列通常还需要专用队列系统 |

关键原则：

> PostgreSQL 是 Agent 应用的事实来源之一，但不是所有问题的唯一工具。

例如，文档原文件可以保存在对象存储中；PostgreSQL 保存文件地址、解析状态、切片和检索字段。这样既能可靠查询结构化数据，也不必让数据库承担不适合它的超大二进制文件存储。

## 3. 数据建模：先确定实体，再决定列

当前工程的三张表体现了最基本的一对多关系：

```text
users 1 ──── N conversations 1 ──── N messages
```

对应源码：

| 表 | 源码 |
| --- | --- |
| `users` | [`init-scripts/create_tables.sql` L5-L9](../create_tables.sql#L5) |
| `conversations` | [`init-scripts/create_tables.sql` L12-L20](../create_tables.sql#L12) |
| `messages` | [`init-scripts/create_tables.sql` L23-L33](../create_tables.sql#L23) |

扩展 Agent 项目时，可以继续识别新的实体：

```text
users
  └── conversations
        ├── messages
        └── agent_runs
              └── tool_calls

knowledge_documents
  └── knowledge_chunks
        └── embedding
```

一个用于理解的设计草图：

```sql
CREATE TABLE agent_runs (
  id UUID PRIMARY KEY,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id),
  status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
  input JSONB NOT NULL DEFAULT '{}'::jsonb,
  output JSONB,
  error_message TEXT,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tool_calls (
  id UUID PRIMARY KEY,
  run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  tool_name TEXT NOT NULL,
  arguments JSONB NOT NULL,
  result JSONB,
  status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded', 'failed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

这段 SQL 是学习用草图，不是要求你立刻修改当前工程。它体现了几个必须掌握的建模习惯：

- 稳定字段使用普通列，例如 `status`、`created_at`。
- 结构可能随工具变化的参数和结果使用 `jsonb`。
- 有限状态使用 `CHECK` 约束。
- 父子关系使用外键。
- 子记录失去父记录后没有意义时，考虑 `ON DELETE CASCADE`。

## 4. 必须掌握的数据类型

### 4.1 `text`

适合保存消息、标题、错误信息和文档切片。当前工程使用：

- [`users.name`](../create_tables.sql#L7)
- [`conversations.title`](../create_tables.sql#L15)
- [`messages.content`](../create_tables.sql#L27)

不要因为字符串“看起来可能不长”就过早限制长度。业务确实要求长度上限时，再使用约束明确限制。

### 4.2 `timestamptz`

当前工程的 `TIMESTAMP WITH TIME ZONE` 与 `timestamptz` 是同一种类型：

```sql
created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
```

源码见 [`init-scripts/create_tables.sql` L8](../create_tables.sql#L8)。

Agent 应用经常需要回答：

- 一次运行何时开始、何时结束？
- 哪些消息属于某个时间范围？
- 哪个 worker 最后一次续租任务是什么时间？
- 哪个知识库文档需要重新生成 embedding？

统一使用带时区的时间类型，可以减少跨时区部署时的歧义。

### 4.3 `uuid`

当前入门工程使用 `SERIAL`，这便于学习。真实分布式系统经常使用 `uuid`。PostgreSQL 16 可以直接使用内置的 `gen_random_uuid()`：

```sql
CREATE TABLE example_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid()
);
```

常见理由：

- 多个服务可以独立生成 ID。
- 对外暴露时不直接泄露记录数量和递增顺序。
- 跨系统合并数据时较少发生冲突。

不要机械地把所有主键都改为 UUID。内部小表、枚举表和教学项目继续使用自增主键没有问题。

如果新表确实需要数据库生成的自增整数，也可以优先了解 SQL 标准 identity 写法：

```sql
id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
```

当前工程使用的 `SERIAL` 更适合入门阅读；identity 列更明确地表达“这一列由数据库生成”。

### 4.4 `jsonb`

Agent 的工具参数、运行状态、模型响应元数据和文档 metadata 经常具有半结构化特征。`jsonb` 可以保存 JSON，并支持查询和索引。

适合使用 `jsonb`：

```sql
metadata JSONB NOT NULL DEFAULT '{}'::jsonb
```

不适合全部塞进 `jsonb`：

```sql
payload JSONB
-- 把用户 ID、状态、创建时间、正文、租户 ID 全部藏进去
```

需要频繁过滤、关联、排序或强约束的字段应该使用普通列。变化较快、不同工具结构不同的补充信息再放入 `jsonb`。

### 4.5 `vector(n)`

当前工程使用：

```sql
embedding vector(1024)
```

源码见 [`init-scripts/create_tables.sql` L28](../create_tables.sql#L28)。

必须理解：

- `1024` 是向量维度，不是文本长度。
- 写入的向量维度必须与列定义一致。
- 更换 embedding 模型时，维度和语义空间都可能改变。
- 不同模型生成的向量不能直接混在一起比较。

## 5. 约束不是多余的重复校验

当前工程同时在 JavaScript 和 PostgreSQL 中限制消息角色：

- JavaScript 校验：[`src/messages.mjs` L5-L25](../src/messages.mjs#L5)
- SQL 约束：[`init-scripts/create_tables.sql` L26](../create_tables.sql#L26)

两层校验职责不同：

| 层级 | 作用 |
| --- | --- |
| 应用校验 | 尽早返回友好的错误信息 |
| 数据库约束 | 阻止任何入口写入非法数据，包括脚本、后台任务和其他服务 |

Agent 系统可能有 API 服务、worker、离线脚本和 migration。只在某一个 JavaScript 函数里做校验，无法保护所有写入入口。

## 6. Agent 数据库设计中容易忽略的字段

### 6.1 租户字段

“租户”是多租户系统中的概念。你可以先把它理解为：

> 同一个应用系统里的一组数据归属单位。

这个归属单位可能是：

- 一个个人用户。
- 一个团队。
- 一个公司。
- 一个工作区 workspace。
- 一个组织 organization。

例如一个 Agent 平台同时服务两家公司：

```text
tenant A：上海测试公司
  ├── 用户 Alice
  ├── 会话、消息、知识库、工具调用记录
  └── API key、账单、运行日志

tenant B：北京测试公司
  ├── 用户 Bob
  ├── 会话、消息、知识库、工具调用记录
  └── API key、账单、运行日志
```

这两个租户使用同一套后端代码，甚至可能共享同一个 PostgreSQL 数据库，但它们的数据必须互相隔离。Alice 不能检索到 Bob 公司知识库里的文档，Bob 也不能看到 Alice 公司的 Agent 运行记录。

#### 6.1.1 用户和租户不是同一个概念

入门时很容易把“用户”和“租户”混在一起。它们不是一回事。

| 概念 | 含义 | 例子 |
| --- | --- | --- |
| 用户 user | 具体登录系统的人或账号 | `alice@example.com` |
| 租户 tenant | 数据归属的组织或空间 | `上海测试公司`、`AI 研发工作区` |

一个租户可以有多个用户：

```text
tenant 1
  ├── user 1
  ├── user 2
  └── user 3
```

一个用户也可能加入多个租户：

```text
user alice
  ├── tenant A
  └── tenant B
```

所以真实项目里经常会有类似关系：

```sql
CREATE TABLE tenants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE tenant_members (
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  role TEXT NOT NULL CHECK (role IN ('owner', 'admin', 'member')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (tenant_id, user_id)
);
```

这表示：用户通过 `tenant_members` 加入某个租户，并拥有某个角色。

#### 6.1.2 为什么业务表要保存 `tenant_id`

如果一个系统服务多个用户、团队或公司，核心业务表通常需要明确保存：

```sql
tenant_id UUID NOT NULL
```

例如 Agent 知识库切片表可以设计成：

```sql
CREATE TABLE knowledge_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id UUID NOT NULL REFERENCES tenants(id),
  document_id UUID NOT NULL,
  content TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  embedding vector(1024),
  created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

`tenant_id` 的作用是告诉数据库：

```text
这一行数据属于哪个租户
```

没有 `tenant_id`，你只能依赖应用代码在更高层判断数据归属。一旦某条 SQL 忘记限制范围，就可能读到别人的数据。

#### 6.1.3 多租户常见三种数据库模型

多租户隔离不只有一种做法。常见模型如下：

| 模型 | 做法 | 优点 | 缺点 |
| --- | --- | --- | --- |
| 共享数据库、共享表 | 所有租户共用表，通过 `tenant_id` 区分 | 成本低，开发和运维简单 | 必须非常重视租户过滤和权限隔离 |
| 共享数据库、独立 schema | 每个租户一个 schema | 隔离更清晰 | migration、连接和运维复杂度上升 |
| 独立数据库 | 每个租户一个数据库 | 隔离最强，适合大客户 | 成本和运维复杂度最高 |

学习和大多数早期 Agent 项目，通常先使用：

```text
共享数据库、共享表、每张核心表保存 tenant_id
```

这个模型最容易理解，也最容易在本地练习。

#### 6.1.4 查询时必须带租户过滤

只要表中有 `tenant_id`，查询业务数据时通常都应该带上：

```sql
WHERE tenant_id = $1
```

例如查询某个租户的最近会话：

```sql
SELECT id, title, created_at
FROM conversations
WHERE tenant_id = $1
ORDER BY created_at DESC
LIMIT 20;
```

知识库向量检索也不能例外。错误写法：

```sql
SELECT id, content
FROM knowledge_chunks
ORDER BY embedding <=> $1::vector
LIMIT 5;
```

这条 SQL 只按相似度搜索，没有限制租户。结果可能把其他租户的知识库内容召回给当前用户。

正确写法：

```sql
SELECT id, content
FROM knowledge_chunks
WHERE tenant_id = $2
ORDER BY embedding <=> $1::vector
LIMIT 5;
```

核心原则：

```text
先限制数据归属范围
再做业务过滤、排序、全文检索或向量检索
```

#### 6.1.5 `tenant_id` 应该是普通列，不应该藏进 JSONB

不要这样设计：

```sql
CREATE TABLE knowledge_chunks (
  id UUID PRIMARY KEY,
  content TEXT NOT NULL,
  metadata JSONB NOT NULL
);
```

然后把租户藏在：

```json
{
  "tenant_id": "..."
}
```

原因是 `tenant_id` 通常会参与：

- 高频过滤。
- 权限隔离。
- 复合索引。
- 外键关联。
- 唯一约束。
- RLS 策略。

这些都更适合普通列：

```sql
tenant_id UUID NOT NULL REFERENCES tenants(id)
```

`jsonb` 更适合保存结构不固定的补充信息，例如工具参数、文档来源 metadata、模型响应中的可选字段。

#### 6.1.6 租户字段常见索引

如果常见查询是：

```sql
WHERE tenant_id = $1
ORDER BY created_at DESC
LIMIT 20
```

可以考虑复合索引：

```sql
CREATE INDEX idx_conversations_tenant_created
  ON conversations (tenant_id, created_at DESC);
```

如果常见查询是：

```sql
WHERE tenant_id = $1
  AND status = 'running'
ORDER BY created_at DESC
```

可以考虑：

```sql
CREATE INDEX idx_agent_runs_tenant_status_created
  ON agent_runs (tenant_id, status, created_at DESC);
```

索引顺序不是随便写的。一般把高频等值过滤字段放前面：

```text
tenant_id、status 这类等值过滤字段
  ↓
created_at 这类排序或范围字段
```

但最终仍然要用 `EXPLAIN ANALYZE` 看真实执行计划。

#### 6.1.7 租户隔离和 RLS 的关系

应用代码里写：

```sql
WHERE tenant_id = $1
```

属于应用层隔离。它简单、直观，但依赖每一条 SQL 都写对。

Row-Level Security（RLS）属于数据库层防线。它可以在数据库内部限制：

```text
当前连接只能看到当前租户的数据
```

第 09 篇会单独介绍 RLS。入门阶段先记住：

- `tenant_id` 是多租户隔离的基础字段。
- 应用查询必须带 `tenant_id`。
- 重要系统可以进一步使用 RLS 作为数据库层保护。
- RLS 不能替代清晰的数据建模和测试。

#### 6.1.8 Agent 项目中特别容易出错的地方

Agent 检索链路经常会组合很多条件：

```text
租户过滤
权限过滤
文档标签过滤
关键词检索
向量相似度排序
时间范围
```

其中最不能漏的是租户过滤。比如混合检索时，不应该先全库向量召回，再在应用内过滤租户。更稳妥的思路是让数据库查询本身就包含租户条件：

```sql
SELECT id, content
FROM knowledge_chunks
WHERE tenant_id = $2
  AND metadata @> '{"source": "manual"}'::jsonb
ORDER BY embedding <=> $1::vector
LIMIT 10;
```

这样数据库返回的数据从一开始就被限制在当前租户范围内。

### 6.2 幂等键

网络重试、任务重试和消息重复投递很常见。可以为外部请求保存幂等键：

```sql
idempotency_key TEXT UNIQUE
```

然后配合 `INSERT ... ON CONFLICT` 避免重复写入。详细用法见 [08-高级查询、JSONB 与混合检索](./08-advanced-query-jsonb-and-hybrid-search.md)。

### 6.3 embedding 版本

知识库切片不仅要保存向量，还应该记录：

```sql
embedding_model TEXT NOT NULL,
embedding_version TEXT,
embedded_at TIMESTAMPTZ
```

原因：

- 更换模型后，需要知道哪些记录应该重新生成向量。
- 相同维度不代表向量来自相同语义空间。
- 排查检索质量问题时，需要知道实际使用了哪个模型。

当前工程的 SQL 注释与代码默认模型并不完全一致：

- SQL 注释：[`init-scripts/create_tables.sql` L28](../create_tables.sql#L28)
- JavaScript 默认模型：[`src/messages.mjs` L12](../src/messages.mjs#L12)

这正说明 embedding 配置不能只存在于代码注释里。

### 6.4 软删除和审计字段

有些数据不能立即物理删除，可以使用：

```sql
deleted_at TIMESTAMPTZ
```

查询时只读取：

```sql
WHERE deleted_at IS NULL
```

但不要默认给所有表都加软删除。它会增加查询条件、唯一约束设计和索引复杂度。只有业务确实需要恢复、审计或延迟清理时再使用。

## 7. PostgreSQL 在 Agent 系统中的四个角色

### 7.1 事实来源

用户、会话、运行状态和权限应该以数据库中的记录为准。应用进程重启后，状态不能只存在内存里。

### 7.2 检索引擎的一部分

PostgreSQL 可以组合：

- 普通结构化过滤。
- `jsonb` metadata 过滤。
- 全文关键词检索。
- pgvector 语义检索。

这非常适合中小规模 Agent 知识库。详细内容见 [08-高级查询、JSONB 与混合检索](./08-advanced-query-jsonb-and-hybrid-search.md)。

### 7.3 并发协调点

多个 worker 竞争任务时，可以利用事务和行锁保证一条任务只被一个 worker 领取。详细内容见 [09-并发、性能与生产运维](./09-concurrency-performance-and-operations.md)。

### 7.4 可恢复状态存储

长时间运行的 Agent 不能假设一次请求永远成功。把关键步骤、检查点和错误信息写入 PostgreSQL，失败后才能继续运行或安全重试。

## 8. 不要把 PostgreSQL 当作专用消息队列

PostgreSQL 可以保存任务表，也支持 `LISTEN` / `NOTIFY`。但 `NOTIFY` 更适合作为“有新数据可检查”的提示，不应该被理解为完整的持久化消息队列。

设计任务处理时至少要保存：

```sql
status
attempt_count
available_at
locked_at
locked_by
last_error
```

这样即使 worker 崩溃，任务记录仍然存在，可以重新领取。高吞吐、复杂路由或严格消息语义出现后，再评估 Redis、RabbitMQ、Kafka 等专用系统。

## 9. 推荐学习顺序

完成当前 `01` 到 `06` 后，按下面顺序继续：

| 阶段 | 文档 | 目标 |
| --- | --- | --- |
| 1 | 本章 | 建立 Agent 数据库存储全景，明确哪些知识必须掌握 |
| 2 | [08-高级查询、JSONB 与混合检索](./08-advanced-query-jsonb-and-hybrid-search.md) | 掌握复杂 SQL、半结构化 metadata、关键词检索和混合召回 |
| 3 | [09-并发、性能与生产运维](./09-concurrency-performance-and-operations.md) | 掌握事务并发、索引、迁移、安全、备份和监控 |
| 4 | `typeorm-pg-crud` 学习文档 | 理解 ORM 如何映射实体、关系和迁移 |

## 10. 学完本章后的检查项

- [ ] 我能区分事实数据、检索数据、运行状态和原始大文件。
- [ ] 我知道普通列与 `jsonb` 各自适合保存什么。
- [ ] 我能解释为什么 Agent 运行状态不能只放在进程内存里。
- [ ] 我知道为什么需要保存 embedding 模型和版本。
- [ ] 我知道幂等键解决的是哪类重复写入问题。
- [ ] 我知道 PostgreSQL 可以参与任务协调，但不等于专用消息队列。
- [ ] 我能根据项目阶段区分“必须掌握”和“出现需求后深入”的知识。

## 官方参考资料

- [PostgreSQL 16 Data Types](https://www.postgresql.org/docs/16/datatype.html)
- [PostgreSQL 16 JSON Types](https://www.postgresql.org/docs/16/datatype-json.html)
- [PostgreSQL 16 Constraints](https://www.postgresql.org/docs/16/ddl-constraints.html)
- [PostgreSQL 16 Date/Time Types](https://www.postgresql.org/docs/16/datatype-datetime.html)
- [PostgreSQL 16 UUID Type](https://www.postgresql.org/docs/16/datatype-uuid.html)
- [pgvector README](https://github.com/pgvector/pgvector)
