# 02. learning 模块代码导读

本章逐步拆解新增的 `learning` 模块。该模块不是教程原代码的替代品，而是一组可以运行的数据库工程化练习。

## 1. 模块结构

```text
src/
  config/
    database.config.ts
  database/
    typeorm.datasource.ts
  learning/
    dto/
      claim-agent-task.dto.ts
      create-agent-run.dto.ts
      create-agent-task.dto.ts
      list-agent-tasks.dto.ts
      update-agent-task.dto.ts
    entities/
      agent-run.entity.ts
      agent-task.entity.ts
    learning.controller.ts
    learning.module.ts
    learning.service.ts
  migrations/
    1760000000000-CreateLearningAgentTables.ts
```

## 2. 数据模型

新增两张表：

```text
learning_agent_tasks 1 ──── N learning_agent_runs
```

### 2.1 AgentTask

源码：[`src/learning/entities/agent-task.entity.ts` L20-L76](../src/learning/entities/agent-task.entity.ts#L20)

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `id` | UUID | 主键 |
| `externalKey` | `text` + unique | 外部幂等键 |
| `title` | `text` | 任务标题 |
| `description` | nullable `text` | 可选说明 |
| `metadata` | `jsonb` | 可变化的补充信息 |
| `status` | enum | `queued`、`running`、`succeeded`、`failed` |
| `attemptCount` | integer | 领取或重试次数 |
| `availableAt` | `timestamptz` | 任务最早可以被领取的时间 |
| `lockedAt` | nullable `timestamptz` | worker 领取时间 |
| `lockedBy` | nullable `text` | 领取任务的 worker |
| `version` | integer | 乐观锁版本号 |
| `createdAt`、`updatedAt` | `timestamptz` | 审计时间 |

### 2.2 AgentRun

源码：[`src/learning/entities/agent-run.entity.ts` L19-L56](../src/learning/entities/agent-run.entity.ts#L19)

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `id` | UUID | 主键 |
| `taskId` | UUID 外键 | 所属任务 |
| `status` | enum | 一次运行的状态 |
| `input` | `jsonb` | Agent 输入 |
| `output` | nullable `jsonb` | Agent 输出 |
| `errorMessage` | nullable `text` | 错误信息 |
| `createdAt`、`updatedAt` | `timestamptz` | 审计时间 |

关系定义：

```ts
@ManyToOne(() => AgentTask, (task) => task.runs, { onDelete: 'CASCADE' })
@JoinColumn({ name: 'task_id' })
task: AgentTask;
```

删除任务时，其学习运行记录也会删除。真实 Agent 产品是否允许级联删除，需要根据审计和合规要求重新评估。

## 3. Module 与 Repository 注入

源码：[`src/learning/learning.module.ts` L7-L11](../src/learning/learning.module.ts#L7)

```ts
@Module({
  imports: [TypeOrmModule.forFeature([AgentTask, AgentRun])],
  controllers: [LearningController],
  providers: [LearningService],
})
export class LearningModule {}
```

`forFeature()` 将两个 Repository 注册到当前模块。Service 才能注入：

```ts
@InjectRepository(AgentTask)
private readonly tasks: Repository<AgentTask>
```

源码见 [`src/learning/learning.service.ts` L18-L24](../src/learning/learning.service.ts#L18)。

## 4. DTO 校验

创建任务 DTO：[`create-agent-task.dto.ts` L10-L37](../src/learning/dto/create-agent-task.dto.ts#L10)

```ts
@IsString()
@IsNotEmpty()
@MaxLength(200)
externalKey: string;
```

请求体进入 Controller 之前，全局 `ValidationPipe` 会执行这些规则。

列表 DTO：[`list-agent-tasks.dto.ts` L11-L29](../src/learning/dto/list-agent-tasks.dto.ts#L11)

```ts
@Type(() => Number)
@IsInt()
@Min(1)
@Max(100)
limit?: number;
```

HTTP 查询参数默认是字符串。`@Type(() => Number)` 将 `"20"` 转换为数字 `20`，再执行整数和范围校验。

## 5. 基础 CRUD

Controller 路由：[`learning.controller.ts` L23-L64](../src/learning/learning.controller.ts#L23)

| HTTP | 路由 | Service 方法 |
| --- | --- | --- |
| `POST` | `/learning/tasks` | `create()` |
| `GET` | `/learning/tasks` | `findAll()` |
| `GET` | `/learning/tasks/:id` | `findOne()` |
| `PATCH` | `/learning/tasks/:id` | `update()` |
| `DELETE` | `/learning/tasks/:id` | `remove()` |

创建任务：

```ts
const task = this.tasks.create({
  ...dto,
  metadata: dto.metadata ?? {},
});

return this.tasks.save(task);
```

源码见 [`src/learning/learning.service.ts` L26-L34](../src/learning/learning.service.ts#L26)。

理解区别：

| 方法 | 作用 |
| --- | --- |
| `repository.create()` | 在内存中创建 Entity 对象，不会立即发送 SQL |
| `repository.save()` | 根据 Entity 状态执行持久化 SQL |

## 6. 幂等 UPSERT

从本章开始，会出现比普通 CRUD 更接近真实项目的概念。建议按下面的顺序读：

1. 先理解它解决什么问题。
2. 再看数据库需要什么约束。
3. 最后再看 TypeORM 代码怎么写。

### 6.1 先理解“重复请求”问题

假设前端或外部系统调用：

```text
POST /learning/tasks
```

创建一个任务：

```json
{
  "externalKey": "import-file-001",
  "title": "导入文件 001"
}
```

可能发生这种情况：

```text
客户端发送请求
  ↓
服务端已经成功写入数据库
  ↓
网络超时，客户端没有收到响应
  ↓
客户端以为失败，又发送了一次相同请求
```

如果后端每次都普通 `INSERT`，数据库中可能出现两条业务上相同的任务：

```text
id | external_key    | title
---+-----------------+--------------
1  | import-file-001 | 导入文件 001
2  | import-file-001 | 导入文件 001
```

这就是重复写入。

### 6.2 幂等是什么意思

幂等的意思是：

> 同一个业务请求执行一次和执行多次，最终结果应该一致。

对创建任务来说，理想行为是：

```text
第一次请求：创建任务
第二次相同请求：不要再创建第二条任务，而是复用或更新原来的任务
```

因此需要一个业务上稳定的唯一标识。当前工程使用：

```ts
externalKey: string;
```

源码见 [`AgentTask.externalKey` L28-L29](../src/learning/entities/agent-task.entity.ts#L28)：

```ts
@Column({ type: 'text', name: 'external_key', unique: true })
externalKey: string;
```

`unique: true` 非常关键。它会在数据库层要求 `external_key` 不能重复。

### 6.3 UPSERT 是什么

UPSERT 可以理解为：

```text
尝试 INSERT
  ↓
如果没有冲突：插入新记录
  ↓
如果唯一约束冲突：执行 UPDATE
```

PostgreSQL 中常见 SQL 是：

```sql
INSERT INTO learning_agent_tasks (external_key, title)
VALUES ('import-file-001', '导入文件 001')
ON CONFLICT (external_key)
DO UPDATE SET title = EXCLUDED.title;
```

拆开理解：

| 片段 | 含义 |
| --- | --- |
| `INSERT INTO ...` | 先尝试插入 |
| `ON CONFLICT (external_key)` | 如果 `external_key` 唯一约束冲突 |
| `DO UPDATE SET ...` | 不报错，改为更新已有记录 |
| `EXCLUDED.title` | 本次原本准备插入的新值 |

### 6.4 TypeORM 中的 upsert

路由：

```text
POST /learning/tasks/upsert
```

Controller 入口见 [`learning.controller.ts` L28-L31](../src/learning/learning.controller.ts#L28)：

```ts
@Post('upsert')
upsert(@Body() dto: CreateAgentTaskDto) {
  return this.learningService.upsert(dto);
}
```

Service 源码见 [`learning.service.ts` L36-L49](../src/learning/learning.service.ts#L36)。先看去掉类型断言后的核心逻辑：

```ts
await this.tasks.upsert(
  {
    ...dto,
    metadata: dto.metadata ?? {},
    availableAt: dto.availableAt ? new Date(dto.availableAt) : new Date(),
  },
  {
    conflictPaths: ['externalKey'],
    skipUpdateIfNoValuesChanged: true,
  },
);
```

逐项理解：

| 代码 | 含义 |
| --- | --- |
| `this.tasks` | `AgentTask` 的 Repository |
| `upsert(...)` | 插入或更新 |
| `{ ...dto }` | 将请求体字段作为要写入的数据 |
| `metadata: dto.metadata ?? {}` | 如果请求没传 metadata，就写入空对象 |
| `availableAt: ...` | 如果没传可领取时间，就用当前时间 |
| `conflictPaths: ['externalKey']` | 发生 `externalKey` 冲突时走更新逻辑 |
| `skipUpdateIfNoValuesChanged: true` | 新旧值没有变化时尽量跳过更新 |

它依赖数据库中 `external_key` 的唯一约束。没有唯一约束，数据库不知道“冲突”应该按什么字段判断。

实际源码中 `metadata` 字段会多一段类型断言：

```ts
metadata: (dto.metadata ?? {}) as QueryDeepPartialEntity<Record<string, unknown>>,
```

这不是 PostgreSQL 的知识点，而是 TypeScript 类型检查需要的写法。你学习 UPSERT 时先理解成：

```ts
metadata: dto.metadata ?? {}
```

即可。

### 6.5 为什么 upsert 后又查询一次

源码中还有：

```ts
return this.tasks.findOneByOrFail({ externalKey: dto.externalKey });
```

原因是 `upsert()` 返回的是数据库执行结果，不一定直接包含完整 Entity。为了接口响应中返回完整任务，代码再按 `externalKey` 查询一次。

### 6.6 什么时候不要用 UPSERT

UPSERT 不是所有写入都应该使用。

适合：

- 外部请求可能重试。
- 业务上存在稳定唯一键，例如订单号、任务 key、webhook event id。
- 重复请求应该复用同一条记录。

不适合：

- 每次点击都应该创建一条新记录。
- 没有可靠唯一业务键。
- 冲突时不应该更新，而应该报错让调用方处理。

## 7. 稳定游标分页

### 7.1 为什么需要分页

如果直接查询全部任务：

```sql
SELECT *
FROM learning_agent_tasks;
```

数据少时没问题。数据多时会有几个问题：

- 响应很大。
- 数据库压力变高。
- 前端一次也显示不完。
- 新数据不断写入时，翻页容易重复或遗漏。

所以接口通常只返回一页：

```text
GET /learning/tasks?limit=20
```

### 7.2 OFFSET 分页先理解

最容易理解的分页是：

```sql
SELECT *
FROM learning_agent_tasks
ORDER BY created_at DESC
LIMIT 20
OFFSET 40;
```

含义：

```text
先排序
跳过前 40 条
取接下来的 20 条
```

它的问题是：

- `OFFSET` 很大时，数据库仍然要算出并跳过前面的很多行。
- 如果翻页期间插入了新数据，第二页可能重复或漏掉数据。

### 7.3 游标分页是什么

游标分页不说“跳过多少条”，而是说：

> 从上一页最后一条记录之后继续查。

第一页：

```text
GET /learning/tasks?limit=20
```

响应中会返回：

```json
{
  "items": [...],
  "nextCursor": {
    "beforeCreatedAt": "2026-06-03T10:00:00.000Z",
    "beforeId": "..."
  }
}
```

第二页：

```text
GET /learning/tasks?limit=20&beforeCreatedAt=...&beforeId=...
```

### 7.4 为什么排序要用 createdAt + id

源码见 [`learning.service.ts` L64-L67](../src/learning/learning.service.ts#L64)：

```ts
const query = this.tasks
  .createQueryBuilder('task')
  .orderBy('task.createdAt', 'DESC')
  .addOrderBy('task.id', 'DESC')
  .take(limit);
```

排序规则是：

```text
先按 createdAt 从新到旧
如果 createdAt 相同，再按 id 从大到小
```

为什么不能只用 `createdAt`？

因为多条记录可能在同一时间创建。如果只写：

```sql
ORDER BY created_at DESC
```

那么创建时间相同的两条记录，数据库没有收到明确要求，谁先谁后不稳定。

加上 `id` 后：

```sql
ORDER BY created_at DESC, id DESC
```

排序就稳定了。

### 7.5 下一页条件怎么读

源码见 [`learning.service.ts` L69-L78](../src/learning/learning.service.ts#L69)：

```ts
query.andWhere(
  '(task.createdAt < :beforeCreatedAt OR (task.createdAt = :beforeCreatedAt AND task.id < :beforeId))',
  {
    beforeCreatedAt: dto.beforeCreatedAt,
    beforeId: dto.beforeId,
  },
);
```

对应 SQL 思路：

```sql
WHERE created_at < 上一页最后一条的 created_at
   OR (
     created_at = 上一页最后一条的 created_at
     AND id < 上一页最后一条的 id
   )
```

拆开理解：

| 条件 | 作用 |
| --- | --- |
| `created_at < beforeCreatedAt` | 找比上一页最后一条更旧的数据 |
| `created_at = beforeCreatedAt AND id < beforeId` | 如果时间相同，就继续用 id 判断下一批 |

这必须和排序条件保持一致：

```text
排序：createdAt DESC, id DESC
游标：beforeCreatedAt, beforeId
```

### 7.6 为什么两个游标参数必须同时提供

源码见 [`learning.service.ts` L53-L61](../src/learning/learning.service.ts#L53)：

```ts
const hasCreatedAt = dto.beforeCreatedAt !== undefined;
const hasId = dto.beforeId !== undefined;

if (hasCreatedAt !== hasId) {
  throw new BadRequestException('beforeCreatedAt 和 beforeId 必须同时提供');
}
```

如果只提供 `beforeCreatedAt`，遇到同一时间的多条记录时无法稳定翻页。

如果只提供 `beforeId`，又不知道它对应的创建时间，也无法判断排序位置。

因此两个值必须一起出现。

### 7.7 QueryBuilder 在这里做什么

`createQueryBuilder('task')` 不是立即查询数据库。它只是开始构造 SQL。

```ts
.orderBy(...)
.addOrderBy(...)
.take(limit)
.andWhere(...)
```

这些方法一步步拼出查询。

真正执行查询的是：

```ts
const items = await query.getMany();
```

源码见 [`learning.service.ts` L81](../src/learning/learning.service.ts#L81)。

## 8. 乐观锁更新

### 8.1 先理解“覆盖更新”问题

假设两个客户端同时打开同一个任务：

```text
数据库当前任务：
title = "旧标题"
version = 1
```

客户端 A 读取到：

```text
title = "旧标题"
version = 1
```

客户端 B 也读取到：

```text
title = "旧标题"
version = 1
```

如果没有任何保护：

```text
客户端 A 修改 title = "A 的标题"
  ↓
数据库更新成功

客户端 B 修改 title = "B 的标题"
  ↓
数据库也更新成功
  ↓
A 的修改被静默覆盖
```

这就是覆盖更新，也叫 lost update。

### 8.2 乐观锁是什么

乐观锁的思路是：

> 我先假设没有别人同时修改；但真正更新时，检查版本号是否还是我读取时的版本。

Entity 中有版本列：

```ts
@VersionColumn()
version: number;
```

源码见 [`agent-task.entity.ts` L64-L65](../src/learning/entities/agent-task.entity.ts#L64)。

客户端更新时必须带上自己看到的版本：

```json
{
  "expectedVersion": 1,
  "title": "修改后的标题"
}
```

DTO 见 [`update-agent-task.dto.ts` L14-L39](../src/learning/dto/update-agent-task.dto.ts#L14)。

### 8.3 当前代码如何检查版本

源码见 [`learning.service.ts` L108-L138](../src/learning/learning.service.ts#L108)：

```ts
const result = await this.tasks.update(
  { id, version: dto.expectedVersion },
  patch,
);
```

这不是只按 `id` 更新，而是按两个条件更新：

```text
id 必须匹配
version 也必须等于 expectedVersion
```

可以理解成 SQL：

```sql
UPDATE learning_agent_tasks
SET title = '新标题',
    version = version + 1
WHERE id = '...'
  AND version = 1;
```

如果更新成功：

```text
result.affected = 1
```

如果任务不存在，或者版本已经被别人改过：

```text
result.affected = 0
```

此时代码抛出：

```ts
throw new ConflictException(
  '任务不存在或版本已经变化，请重新读取后再更新',
);
```

HTTP 响应就是 `409 Conflict`。

### 8.4 patch 对象是什么

源码中先创建：

```ts
const patch: QueryDeepPartialEntity<AgentTask> = {
  version: () => '"version" + 1',
};
```

`patch` 表示“这次要修改哪些字段”。

如果请求传了 `title`：

```ts
patch.title = dto.title;
```

如果请求传了 `metadata`：

```ts
patch.metadata = dto.metadata as QueryDeepPartialEntity<Record<string, unknown>>;
```

最终只更新请求中出现的字段，不会把没传的字段改成空值。

`version: () => '"version" + 1'` 表示让数据库执行：

```sql
version = version + 1
```

而不是先把旧版本查到应用内存里再加一。

### 8.5 乐观锁适合什么场景

适合：

- 用户编辑表单。
- 管理后台修改任务配置。
- 更新不频繁，但不能接受静默覆盖。

不适合：

- 高并发扣库存。
- worker 抢任务。
- 必须强制串行执行的关键资源。

这些场景通常需要事务、行锁或更专门的并发控制。

## 9. 事务：创建运行记录并更新任务状态

### 9.1 为什么需要事务

接口：

```text
POST /learning/tasks/:id/runs
```

业务目标不是只插入一条运行记录，还要同步修改任务状态：

```text
创建 learning_agent_runs
  ↓
把 learning_agent_tasks.status 改成 running
```

如果不用事务，可能发生：

```text
运行记录创建成功
  ↓
更新任务状态失败
  ↓
数据库留下不一致状态
```

例如：

```text
learning_agent_runs 中已经有一条 running 记录
但 learning_agent_tasks.status 仍然是 queued
```

这会让后续 worker 误以为任务还没开始。

### 9.2 事务保证什么

事务保证：

> 一组数据库操作要么全部成功，要么全部失败。

成功：

```text
INSERT run 成功
UPDATE task 成功
COMMIT
```

失败：

```text
INSERT run 成功
UPDATE task 失败
ROLLBACK
刚才插入的 run 也撤销
```

### 9.3 TypeORM 事务写法

源码见 [`learning.service.ts` L149-L170](../src/learning/learning.service.ts#L149)：

```ts
return this.dataSource.transaction(async (manager) => {
  const task = await manager.findOneBy(AgentTask, { id: taskId });

  if (!task) {
    throw new NotFoundException(`Learning task ${taskId} not found`);
  }

  const run = manager.create(AgentRun, {
    taskId,
    status: AgentRunStatus.RUNNING,
    input: dto.input ?? {},
  });

  const savedRun = await manager.save(run);

  await manager.update(AgentTask, taskId, {
    status: AgentTaskStatus.RUNNING,
  });

  return savedRun;
});
```

逐步理解：

| 步骤 | 代码 | 含义 |
| --- | --- | --- |
| 1 | `dataSource.transaction(...)` | 开启事务 |
| 2 | `manager.findOneBy(...)` | 在事务中查询任务 |
| 3 | `manager.create(...)` | 创建运行记录对象 |
| 4 | `manager.save(run)` | 插入运行记录 |
| 5 | `manager.update(...)` | 更新任务状态 |
| 6 | `return savedRun` | 全部成功后提交事务并返回 |

### 9.4 为什么必须使用 manager

事务回调中传入的：

```ts
manager
```

代表当前事务绑定的数据库连接。

因此事务内部要用：

```ts
manager.save(...)
manager.update(...)
```

不要使用外部注入的：

```ts
this.tasks.save(...)
this.runs.save(...)
```

原因是外部 Repository 可能使用连接池中的另一条连接。事务只对当前连接有效，如果混用连接，就可能出现“以为在事务里，其实某些 SQL 不在同一个事务里”的问题。

### 9.5 事务里不要做什么

不要在事务中执行耗时外部调用，例如：

- 调用大模型 API。
- 调用第三方 HTTP 服务。
- 等待用户输入。
- 执行长时间文件处理。

更合理的方式：

```text
短事务：把任务状态改为 running
事务外：调用模型或工具
短事务：保存结果并改成 succeeded / failed
```

事务应该尽量短，减少锁等待和连接占用。

## 10. QueryRunner 与任务领取

### 10.1 为什么普通查询不能安全领取任务

假设有两个 worker 同时执行：

```sql
SELECT id
FROM learning_agent_tasks
WHERE status = 'queued'
ORDER BY available_at ASC
LIMIT 1;
```

两个 worker 可能都读到同一条任务：

```text
worker A 读到 task-1
worker B 也读到 task-1
```

然后两个 worker 都去处理同一任务。这就是重复消费。

### 10.2 任务领取需要做到什么

领取任务必须是一个原子动作：

```text
找到一条 queued 任务
  ↓
锁住它
  ↓
把它改成 running
  ↓
记录 locked_by 和 locked_at
```

中间不能让另一个 worker 插进来领取同一条任务。

### 10.3 QueryRunner 是什么

`QueryRunner` 是 TypeORM 提供的底层工具。可以把它理解为：

> 手动拿到一条数据库连接，并手动控制这条连接上的事务。

源码见 [`learning.service.ts` L173-L179](../src/learning/learning.service.ts#L173)：

```ts
const queryRunner = this.dataSource.createQueryRunner();

await queryRunner.connect();
await queryRunner.startTransaction();
```

含义：

| 代码 | 含义 |
| --- | --- |
| `createQueryRunner()` | 创建一个手动控制连接的对象 |
| `connect()` | 从连接池中拿到一条数据库连接 |
| `startTransaction()` | 在这条连接上开启事务 |

### 10.4 核心 SQL 怎么读

源码见 [`learning.service.ts` L180-L202](../src/learning/learning.service.ts#L180)：

```sql
WITH next_task AS (
  SELECT id
  FROM learning_agent_tasks
  WHERE status = $1
    AND available_at <= CURRENT_TIMESTAMP
  ORDER BY available_at ASC, id ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE learning_agent_tasks AS task
SET status = $2,
    locked_at = CURRENT_TIMESTAMP,
    locked_by = $3,
    attempt_count = task.attempt_count + 1,
    version = task.version + 1,
    updated_at = CURRENT_TIMESTAMP
FROM next_task
WHERE task.id = next_task.id
RETURNING task.*
```

分成两部分看。

第一部分，找到一条可领取任务：

```sql
WITH next_task AS (
  SELECT id
  FROM learning_agent_tasks
  WHERE status = $1
    AND available_at <= CURRENT_TIMESTAMP
  ORDER BY available_at ASC, id ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
```

| 片段 | 含义 |
| --- | --- |
| `status = $1` | 只找 `queued` 任务 |
| `available_at <= CURRENT_TIMESTAMP` | 只找已经到可领取时间的任务 |
| `ORDER BY available_at ASC, id ASC` | 最早可领取的任务优先 |
| `FOR UPDATE` | 锁住选中的行 |
| `SKIP LOCKED` | 如果某行已经被别的 worker 锁住，就跳过 |
| `LIMIT 1` | 一次只领取一条任务 |

第二部分，把这条任务改成 running：

```sql
UPDATE learning_agent_tasks AS task
SET status = $2,
    locked_at = CURRENT_TIMESTAMP,
    locked_by = $3,
    attempt_count = task.attempt_count + 1,
    version = task.version + 1,
    updated_at = CURRENT_TIMESTAMP
FROM next_task
WHERE task.id = next_task.id
RETURNING task.*
```

| 片段 | 含义 |
| --- | --- |
| `status = $2` | 改成 `running` |
| `locked_at = CURRENT_TIMESTAMP` | 记录领取时间 |
| `locked_by = $3` | 记录哪个 worker 领取 |
| `attempt_count + 1` | 领取次数加一 |
| `version + 1` | 版本号加一 |
| `RETURNING task.*` | 返回被领取的完整任务 |

### 10.5 FOR UPDATE SKIP LOCKED 怎么防止重复领取

假设同时有两个 worker：

```text
worker A 开启事务
worker B 开启事务
```

worker A 执行查询时锁住 task-1：

```text
task-1 被 worker A 锁住
```

worker B 执行同样查询时：

```text
看到 task-1 已被锁住
由于 SKIP LOCKED，不等待，直接跳过 task-1
继续寻找 task-2
```

结果：

```text
worker A 领取 task-1
worker B 领取 task-2
```

### 10.6 为什么必须 commit、rollback、release

源码见 [`learning.service.ts` L204-L210](../src/learning/learning.service.ts#L204)：

```ts
await queryRunner.commitTransaction();
return rows[0] ?? null;
```

如果成功，提交事务。

```ts
await queryRunner.rollbackTransaction();
throw error;
```

如果失败，回滚事务。

```ts
await queryRunner.release();
```

无论成功失败，都释放连接。

如果忘记 `release()`，连接池中的连接会被占住，后续请求可能拿不到连接。

### 10.7 QueryRunner 与 dataSource.transaction 的区别

| 写法 | 适合场景 |
| --- | --- |
| `dataSource.transaction(async manager => ...)` | 普通事务，TypeORM 帮你管理连接、提交和回滚 |
| `QueryRunner` | 你需要手动控制连接、事务、原生 SQL、锁或更细的生命周期 |

当前 `createRun()` 使用 `dataSource.transaction()` 就够了。

当前 `claimNextQueuedTask()` 使用 `QueryRunner`，因为它需要一段明确的锁定 SQL，并且要手动控制事务边界。

## 11. GROUP BY 状态统计

### 11.1 这个接口统计什么

路由：

```text
GET /learning/tasks/stats
```

它想回答：

> 当前每种任务状态分别有多少条？

例如：

```text
queued: 10
running: 2
succeeded: 35
failed: 1
```

### 11.2 QueryBuilder 写法

源码见 [`learning.service.ts` L213-L220](../src/learning/learning.service.ts#L213)：

```ts
return this.tasks
  .createQueryBuilder('task')
  .select('task.status', 'status')
  .addSelect('COUNT(*)::int', 'count')
  .groupBy('task.status')
  .orderBy('task.status', 'ASC')
  .getRawMany<{ status: AgentTaskStatus; count: number }>();
```

逐项理解：

| 代码 | 含义 |
| --- | --- |
| `createQueryBuilder('task')` | 以 `task` 作为表别名构造 SQL |
| `select('task.status', 'status')` | 输出状态字段，别名为 `status` |
| `addSelect('COUNT(*)::int', 'count')` | 统计每组行数，别名为 `count` |
| `groupBy('task.status')` | 按任务状态分组 |
| `orderBy('task.status', 'ASC')` | 按状态升序排列 |
| `getRawMany()` | 返回原始查询结果，不转换成 Entity |

### 11.3 对应 SQL

上面的 QueryBuilder 接近：

```sql
SELECT
  status,
  COUNT(*)::int AS count
FROM learning_agent_tasks
GROUP BY status
ORDER BY status ASC;
```

分组过程：

```text
所有 task 行
  ↓ GROUP BY status
queued 组
running 组
succeeded 组
failed 组
  ↓ COUNT(*)
每组有多少行
```

### 11.4 为什么这里用 COUNT(*)

这里的目标是：

> 统计每个状态分组里有多少行任务。

因此 `COUNT(*)` 正确。

它不是“统计所有字段”，而是“统计行数”。

如果你写：

```sql
COUNT(status)
```

在当前表中结果通常也一样，因为 `status` 是非空字段。但 `COUNT(*)` 更直接表达“我要数行”。

### 11.5 为什么使用 getRawMany

普通：

```ts
getMany()
```

会尝试返回 `AgentTask` Entity。

但统计结果不是完整任务，而是这种形状：

```json
[
  { "status": "queued", "count": 10 },
  { "status": "running", "count": 2 }
]
```

所以使用：

```ts
getRawMany()
```

表示“我要原始查询结果”。

## 12. Migration

### 12.1 为什么需要 migration

前面学习时默认使用：

```dotenv
DATABASE_SYNCHRONIZE=true
```

这表示应用启动时，TypeORM 会根据 Entity 尝试同步数据库结构。

本地学习很方便，但真实项目不能依赖它。原因：

- 数据库结构变化需要审查。
- 生产数据库已有真实数据，不能让应用启动时自动乱改表。
- 复杂索引、扩展、数据迁移经常需要手写 SQL。
- 每个环境需要按同样顺序执行结构变更。

Migration 的目标是：

> 把数据库结构变化写成有版本的文件，按顺序执行。

### 12.2 Entity 与 migration 的区别

| 概念 | 作用 |
| --- | --- |
| Entity | 告诉 TypeORM 应用代码如何理解表和列 |
| Migration | 告诉数据库应该如何创建、修改或删除结构 |

Entity 是“映射描述”。

Migration 是“结构变更记录”。

### 12.3 当前 migration 文件做了什么

源码：[`src/migrations/1760000000000-CreateLearningAgentTables.ts` L8-L84](../src/migrations/1760000000000-CreateLearningAgentTables.ts#L8)

`up()` 表示升级数据库结构。

它创建：

1. `learning_agent_tasks_status_enum` 枚举类型。
2. `learning_agent_runs_status_enum` 枚举类型。
3. `learning_agent_tasks` 表。
4. `learning_agent_runs` 表。
5. `learning_agent_runs.task_id` 到 `learning_agent_tasks.id` 的外键。
6. `idx_learning_agent_tasks_status_available` 普通索引。
7. `idx_learning_agent_tasks_queued_available` 部分索引。
8. `idx_learning_agent_runs_task_created` 普通索引。

`down()` 表示回滚数据库结构。

它会删除：

1. `learning_agent_runs` 表。
2. `learning_agent_tasks` 表。
3. `learning_agent_runs_status_enum` 枚举类型。
4. `learning_agent_tasks_status_enum` 枚举类型。

### 12.4 为什么 down 的顺序和 up 相反

创建时可以先创建父表，再创建子表和外键。

删除时必须反过来：

```text
先删除依赖父表的子表
再删除父表
最后删除枚举类型
```

如果先删除父表，数据库会发现子表外键仍然引用它，删除会失败。

### 12.5 当前学习环境的注意点

当前本地学习默认开启：

```dotenv
DATABASE_SYNCHRONIZE=true
```

如果你已经启动过应用，TypeORM 可能已经自动创建了：

```text
learning_agent_tasks
learning_agent_runs
```

这时不要在同一个数据库里直接执行创建这些表的 migration，否则可能出现“表已存在”。

练习 migration 时建议：

1. 使用单独的练习数据库。
2. 或确认只清理 `learning_agent_*` 学习表和相关枚举。
3. 设置 `DATABASE_SYNCHRONIZE=false`。
4. 再执行 migration。

### 12.6 常用 migration 命令

查看 migration 状态：

```powershell
pnpm.cmd exec typeorm-ts-node-commonjs `
  -d src/database/typeorm.datasource.ts `
  migration:show
```

执行 migration：

```powershell
pnpm.cmd exec typeorm-ts-node-commonjs `
  -d src/database/typeorm.datasource.ts `
  migration:run
```

回滚最近一次 migration：

```powershell
pnpm.cmd exec typeorm-ts-node-commonjs `
  -d src/database/typeorm.datasource.ts `
  migration:revert
```

### 12.7 什么时候必须写 migration

真实项目中，下面这些变化都应该写 migration：

- 新增表。
- 新增列。
- 修改列类型。
- 新增索引。
- 新增唯一约束。
- 新增外键。
- 创建 pgvector HNSW 索引。
- 从旧结构迁移已有数据。

不要依赖生产环境的 `synchronize: true` 自动处理这些变化。

## 13. 阅读完成标准

- [ ] 我能解释 `forFeature()` 与 `@InjectRepository()` 如何配合。
- [ ] 我能解释 `create()` 与 `save()` 的区别。
- [ ] 我能解释什么是重复请求，以及为什么需要幂等。
- [ ] 我能解释 UPSERT 的 `INSERT` 和 `ON CONFLICT DO UPDATE` 两部分。
- [ ] 我能解释 UPSERT 为什么必须依赖唯一约束。
- [ ] 我能解释 OFFSET 分页和游标分页的区别。
- [ ] 我能解释稳定分页为什么使用 `createdAt + id`。
- [ ] 我能解释乐观锁解决的覆盖更新问题。
- [ ] 我能解释 `expectedVersion` 为什么必须由客户端传入。
- [ ] 我能解释事务为什么能避免“一半成功一半失败”。
- [ ] 我能解释事务回调为什么必须使用 manager。
- [ ] 我能解释 QueryRunner 为什么要手动 connect、commit、rollback 和 release。
- [ ] 我能解释 `FOR UPDATE SKIP LOCKED` 如何避免多个 worker 重复领取任务。
- [ ] 我知道 `COUNT(*)` 在状态统计中的含义。
- [ ] 我能区分 Entity 和 migration。

## 官方参考资料

- [TypeORM Repository](https://typeorm.io/docs/working-with-entity-manager/working-with-repository)
- [TypeORM Repository APIs](https://typeorm.io/docs/working-with-entity-manager/repository-api)
- [TypeORM Select QueryBuilder](https://typeorm.io/docs/query-builder/select-query-builder)
- [TypeORM Transactions](https://typeorm.io/docs/advanced-topics/transactions/)
- [TypeORM QueryRunner](https://typeorm.io/docs/query-runner)
- [TypeORM Migrations](https://typeorm.io/docs/advanced-topics/migrations)
- [PostgreSQL Explicit Locking](https://www.postgresql.org/docs/16/explicit-locking.html)
