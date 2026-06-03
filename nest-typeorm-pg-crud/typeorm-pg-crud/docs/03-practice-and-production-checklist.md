# 03. 运行练习与生产化边界

本章用于实际运行新增学习接口。练习表使用 `learning_agent_*` 前缀，与教程原有的 `users`、`conversations`、`messages` 分开。

## 1. 启动前检查

共享 PostgreSQL 由旧工程提供：

```powershell
cd D:\AI_Agent_Project\pgsql-test
docker compose up -d
docker compose ps
```

回到当前工程：

```powershell
cd D:\AI_Agent_Project\nest-typeorm-pg-crud\typeorm-pg-crud
pnpm.cmd run start:dev
```

本地学习默认使用：

```dotenv
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USERNAME=user
DATABASE_PASSWORD=123456
DATABASE_NAME=hello_pg
DATABASE_SYNCHRONIZE=true
DATABASE_LOGGING=true
```

参考配置见 [`.env.example`](../.env.example)。

启动后，TypeORM 会根据 Entity 创建学习表。查看：

```powershell
docker exec -it pg_vector_db psql -U user -d hello_pg
```

在 `psql` 中执行：

```sql
\dt learning_agent*
\d learning_agent_tasks
\d learning_agent_runs
```

## 2. DTO 校验实验

发送非法请求：

```powershell
$body = @{
  externalKey = ""
  title = 123
  unexpected = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:3005/learning/tasks `
  -ContentType "application/json" `
  -Body $body
```

预期：返回 `400 Bad Request`。

原因：

- `externalKey` 不能为空。
- `title` 必须是字符串。
- `unexpected` 不在 DTO 中，并且全局管道启用了 `forbidNonWhitelisted`。

对应源码：

- [`src/main.ts` L8-L14](../src/main.ts#L8)
- [`src/learning/dto/create-agent-task.dto.ts` L10-L37](../src/learning/dto/create-agent-task.dto.ts#L10)

## 3. 创建任务

```powershell
$body = @{
  externalKey = "learn-task-001"
  title = "学习 NestJS Repository"
  description = "观察 create 和 save"
  metadata = @{
    agent = "study-agent"
    tags = @("nestjs", "typeorm")
  }
} | ConvertTo-Json -Depth 5

$task = Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:3005/learning/tasks `
  -ContentType "application/json" `
  -Body $body

$task
```

记录：

```powershell
$taskId = $task.id
$taskVersion = $task.version
```

检查项：

- [ ] 我能在响应中找到 UUID 主键。
- [ ] 我知道 metadata 保存为 JSONB。
- [ ] 我能在 TypeORM 日志中找到 `INSERT`。

## 4. 幂等 UPSERT

第一次调用：

```powershell
$body = @{
  externalKey = "learn-upsert-001"
  title = "第一次写入"
  metadata = @{ source = "first" }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:3005/learning/tasks/upsert `
  -ContentType "application/json" `
  -Body $body
```

使用同一个 `externalKey` 再次调用：

```powershell
$body = @{
  externalKey = "learn-upsert-001"
  title = "重复请求更新同一任务"
  metadata = @{ source = "retry" }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:3005/learning/tasks/upsert `
  -ContentType "application/json" `
  -Body $body
```

进入 `psql` 验证：

```sql
SELECT id, external_key, title, metadata
FROM learning_agent_tasks
WHERE external_key = 'learn-upsert-001';
```

预期：只有一行，标题和 metadata 已更新。

## 5. 稳定游标分页

第一页：

```powershell
$page1 = Invoke-RestMethod `
  -Uri "http://localhost:3005/learning/tasks?limit=2"

$page1
```

如果 `nextCursor` 不为空：

```powershell
$createdAt = [uri]::EscapeDataString($page1.nextCursor.beforeCreatedAt)
$id = $page1.nextCursor.beforeId

$page2 = Invoke-RestMethod `
  -Uri "http://localhost:3005/learning/tasks?limit=2&beforeCreatedAt=$createdAt&beforeId=$id"

$page2
```

检查项：

- [ ] 我能解释为什么排序字段包含 `createdAt` 和 `id`。
- [ ] 我知道 `beforeCreatedAt` 与 `beforeId` 必须同时提供。
- [ ] 我知道大偏移量列表为什么更适合游标分页。

## 6. 乐观锁更新

使用创建任务时记录的版本：

```powershell
$body = @{
  expectedVersion = $taskVersion
  title = "使用乐观锁更新"
} | ConvertTo-Json

$updatedTask = Invoke-RestMethod `
  -Method Patch `
  -Uri "http://localhost:3005/learning/tasks/$taskId" `
  -ContentType "application/json" `
  -Body $body

$updatedTask
```

再次使用旧版本提交相同请求：

```powershell
Invoke-RestMethod `
  -Method Patch `
  -Uri "http://localhost:3005/learning/tasks/$taskId" `
  -ContentType "application/json" `
  -Body $body
```

预期：第二次返回 `409 Conflict`。

检查项：

- [ ] 我知道 `expectedVersion` 解决的是并发覆盖问题。
- [ ] 我能解释为什么第二次更新失败。

## 7. 事务：创建运行记录

```powershell
$body = @{
  input = @{
    query = "解释 TypeORM 事务"
    mode = "learning"
  }
} | ConvertTo-Json -Depth 5

Invoke-RestMethod `
  -Method Post `
  -Uri "http://localhost:3005/learning/tasks/$taskId/runs" `
  -ContentType "application/json" `
  -Body $body
```

读取任务：

```powershell
Invoke-RestMethod -Uri "http://localhost:3005/learning/tasks/$taskId"
```

预期：

- 返回任务的 `status` 为 `running`。
- `runs` 数组包含新建的运行记录。

对应源码：[`src/learning/learning.service.ts` L149-L170](../src/learning/learning.service.ts#L149)。

## 8. 任务领取与行锁

先创建两条 queued 任务：

```powershell
1..2 | ForEach-Object {
  $body = @{
    externalKey = "learn-claim-00$_"
    title = "待领取任务 $_"
  } | ConvertTo-Json

  Invoke-RestMethod `
    -Method Post `
    -Uri http://localhost:3005/learning/tasks `
    -ContentType "application/json" `
    -Body $body
}
```

领取：

```powershell
$body = @{ workerId = "worker-01" } | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:3005/learning/tasks/claim `
  -ContentType "application/json" `
  -Body $body
```

再使用另一个 worker：

```powershell
$body = @{ workerId = "worker-02" } | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:3005/learning/tasks/claim `
  -ContentType "application/json" `
  -Body $body
```

检查领取结果：

```sql
SELECT
  external_key,
  status,
  locked_by,
  attempt_count
FROM learning_agent_tasks
WHERE external_key LIKE 'learn-claim-%'
ORDER BY external_key;
```

检查项：

- [ ] 我能解释 `FOR UPDATE` 为什么要放在事务中。
- [ ] 我能解释 `SKIP LOCKED` 为什么适合多个 worker。
- [ ] 我知道连接必须在 `finally` 中释放。

## 9. GROUP BY 状态统计

```powershell
Invoke-RestMethod -Uri http://localhost:3005/learning/tasks/stats
```

对应 SQL 语义：

```sql
SELECT status, COUNT(*)::int AS count
FROM learning_agent_tasks
GROUP BY status
ORDER BY status ASC;
```

检查项：

- [ ] 我知道这里为什么使用 `COUNT(*)`。
- [ ] 我能解释每种状态如何形成一个分组。

## 10. 删除任务与级联删除

删除前，先确认任务具有运行记录：

```powershell
Invoke-RestMethod -Uri "http://localhost:3005/learning/tasks/$taskId"
```

删除：

```powershell
Invoke-RestMethod `
  -Method Delete `
  -Uri "http://localhost:3005/learning/tasks/$taskId"
```

进入 `psql` 验证对应 `learning_agent_runs` 已被级联删除。

## 11. synchronize 与 migration 练习边界

### 11.1 快速学习模式

```dotenv
DATABASE_SYNCHRONIZE=true
```

适合本地快速创建学习表。

### 11.2 migration 模式

```dotenv
DATABASE_SYNCHRONIZE=false
```

使用 migration 前，应该选择：

1. 新建独立练习数据库。
2. 或者确认只删除 `learning_agent_*` 学习表和相关枚举，不影响教程数据。

查看 migration：

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

不要在生产环境使用 `synchronize: true`。

## 12. 生产项目仍然需要补充什么

本次扩展用于学习，不等于完整生产实现。真实项目继续补充：

### 配置和安全

- [ ] 不使用源码默认密码。
- [ ] 通过安全系统注入凭据。
- [ ] 应用 role 使用最小权限。
- [ ] 多租户查询强制加入 `tenant_id` 过滤。
- [ ] 根据业务评估 Row-Level Security。

### 任务系统

- [ ] 设计 worker 崩溃后的锁超时和重新领取。
- [ ] 设计最大重试次数、退避时间和死信处理。
- [ ] 评估 PostgreSQL 任务表与专用队列的边界。
- [ ] 外部模型 API 调用不要占用长事务。

### 数据库结构

- [ ] 使用 migration 管理所有结构变化。
- [ ] 为真实查询使用 `EXPLAIN ANALYZE` 验证索引。
- [ ] 监控连接池、锁等待、慢 SQL 和 autovacuum。
- [ ] 定期执行备份恢复演练。

### 测试

- [ ] 使用独立测试数据库。
- [ ] 为 DTO 非法输入增加 e2e 测试。
- [ ] 为事务失败增加回滚测试。
- [ ] 为重复 UPSERT 增加幂等测试。
- [ ] 使用两个并发连接验证任务不会重复领取。
- [ ] mock 嵌入模型，避免测试依赖外部 API。

## 13. 学习完成标准

- [ ] 我实际调用过所有新增学习接口。
- [ ] 我从 TypeORM 日志中找到过 `INSERT`、`UPDATE`、`SELECT` 和事务 SQL。
- [ ] 我使用 `psql` 查看过学习表、索引和约束。
- [ ] 我能解释 DTO、Repository、QueryBuilder、事务和 QueryRunner 的边界。
- [ ] 我能解释 UPSERT、乐观锁和行锁分别处理什么问题。
- [ ] 我能解释 `synchronize` 与 migration 的差异。
- [ ] 我知道本次学习模块距离生产系统还缺少什么。

## 官方参考资料

- [NestJS Validation](https://docs.nestjs.com/techniques/validation)
- [NestJS Configuration](https://docs.nestjs.com/techniques/configuration)
- [TypeORM Transactions](https://typeorm.io/docs/advanced-topics/transactions/)
- [TypeORM QueryRunner](https://typeorm.io/docs/query-runner)
- [TypeORM Migrations](https://typeorm.io/docs/advanced-topics/migrations)
- [PostgreSQL INSERT / ON CONFLICT](https://www.postgresql.org/docs/16/sql-insert.html)
- [PostgreSQL Explicit Locking](https://www.postgresql.org/docs/16/explicit-locking.html)
