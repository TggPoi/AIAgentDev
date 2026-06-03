# 01. NestJS 操作 PostgreSQL 必学知识

学习 NestJS 数据库开发时，不应该只记住装饰器写法。必须理解 HTTP 请求、应用对象、ORM 和 PostgreSQL 之间如何协作。

## 1. 整体调用链

```text
HTTP 请求
  ↓
Controller：读取 URL、查询参数和请求体
  ↓
DTO + Pipe：转换并校验输入
  ↓
Service：执行业务规则
  ↓
Repository / EntityManager / QueryBuilder / 原生 SQL
  ↓
TypeORM DataSource 和连接池
  ↓
PostgreSQL
```

每一层都有明确职责。不要在 Controller 中直接拼接 SQL，也不要因为使用 ORM 就忽略数据库约束和执行计划。

## 2. 必须掌握的 NestJS 知识

| 知识点 | 必须理解的问题 | 对应源码 |
| --- | --- | --- |
| Module | 一个功能模块注册了哪些 Controller、Provider 和 Repository？ | [`learning.module.ts` L7-L11](../src/learning/learning.module.ts#L7) |
| Controller | URL、HTTP 方法、路径参数、查询参数和 Body 如何映射到方法参数？ | [`learning.controller.ts` L19-L75](../src/learning/learning.controller.ts#L19) |
| Provider | 为什么 Service 由 NestJS 容器创建，而不是手动 `new`？ | [`learning.service.ts` L17-L24](../src/learning/learning.service.ts#L17) |
| 依赖注入 | Repository 和 DataSource 如何注入 Service？ | [`learning.service.ts` L18-L24](../src/learning/learning.service.ts#L18) |
| DTO | TypeScript 类型为什么不能替代运行时输入校验？ | [`create-agent-task.dto.ts` L10-L37](../src/learning/dto/create-agent-task.dto.ts#L10) |
| Pipe | 如何转换和拒绝非法参数？ | [`main.ts` L8-L14](../src/main.ts#L8) |
| Exception | 如何将业务失败转换为 `400`、`404`、`409`？ | [`learning.service.ts` L58-L61](../src/learning/learning.service.ts#L58) |
| ConfigModule | 为什么不能将数据库密码硬编码在模块中？ | [`database.config.ts` L3-L11](../src/config/database.config.ts#L3) |

### 2.1 DTO 类型不等于运行时校验

TypeScript 类型只在编译期间存在。客户端仍然可以发送：

```json
{
  "externalKey": "",
  "title": 123,
  "unexpected": true
}
```

全局管道：

```ts
new ValidationPipe({
  whitelist: true,
  forbidNonWhitelisted: true,
  transform: true,
})
```

源码见 [`src/main.ts` L8-L14](../src/main.ts#L8)。

含义：

| 配置 | 作用 |
| --- | --- |
| `whitelist: true` | 只接受 DTO 中具有校验装饰器的字段 |
| `forbidNonWhitelisted: true` | 出现未声明字段时直接返回错误 |
| `transform: true` | 将网络中的字符串转换为 DTO 期望的基础类型 |

### 2.2 配置属于运行环境，不属于业务代码

原教程将数据库地址直接写在 `app.module.ts` 中。扩展代码改为：

```ts
ConfigModule.forRoot({
  isGlobal: true,
})
```

以及：

```ts
TypeOrmModule.forRootAsync({
  imports: [ConfigModule.forFeature(databaseConfig)],
  inject: [databaseConfig.KEY],
  useFactory: (config) => ({
    ...config,
    entities: [...],
  }),
})
```

源码见 [`src/app.module.ts` L16-L27](../src/app.module.ts#L16)。

本地默认值便于练习，但生产环境必须从安全配置系统注入密码。

## 3. 必须掌握的 TypeORM 知识

| 知识点 | 作用 | 对应源码 |
| --- | --- | --- |
| Entity | 将表、列、索引和关系描述为 TypeScript 类 | [`agent-task.entity.ts` L20-L76](../src/learning/entities/agent-task.entity.ts#L20) |
| Repository | 操作一种 Entity，依赖更明确，便于测试 | [`learning.service.ts` L18-L22](../src/learning/learning.service.ts#L18) |
| EntityManager | 在事务中操作多种 Entity | [`learning.service.ts` L150-L168](../src/learning/learning.service.ts#L150) |
| QueryBuilder | 构造动态查询、稳定分页和聚合 | [`learning.service.ts` L64-L87](../src/learning/learning.service.ts#L64) |
| DataSource | 持有数据库配置和连接池入口 | [`typeorm.datasource.ts` L10-L20](../src/database/typeorm.datasource.ts#L10) |
| QueryRunner | 独占一条连接并手工控制事务 | [`learning.service.ts` L174-L209](../src/learning/learning.service.ts#L174) |
| Migration | 版本化管理数据库结构变化 | [`1760000000000-CreateLearningAgentTables.ts` L8-L84](../src/migrations/1760000000000-CreateLearningAgentTables.ts#L8) |
| 原生 SQL | 表达 PostgreSQL 扩展、锁和精确优化需求 | [`learning.service.ts` L180-L202](../src/learning/learning.service.ts#L180) |

### 3.1 Repository 与 EntityManager 如何选择

Repository 只操作一个 Entity：

```ts
@InjectRepository(AgentTask)
private readonly tasks: Repository<AgentTask>
```

适合任务 CRUD、分页和统计。

事务中需要同时创建 `AgentRun` 并更新 `AgentTask`，使用事务回调参数中的 manager：

```ts
return this.dataSource.transaction(async (manager) => {
  // 所有事务内操作都使用 manager
});
```

源码见 [`src/learning/learning.service.ts` L149-L170](../src/learning/learning.service.ts#L149)。



### 3.2 ORM 不会取代 SQL

**以下需求仍然适合原生 SQL：**

- **pgvector 的 `<=>` 距离运算符。**
- `FOR UPDATE SKIP LOCKED`。
- 复杂 CTE。
- 需要精确检查执行计划的查询。
- **数据库扩展特有能力。**

原教程 pgvector 查询见 [`conversations.service.ts` L89-L100](../src/conversations/conversations.service.ts#L89)。

新增任务领取查询见 [`learning.service.ts` L180-L202](../src/learning/learning.service.ts#L180)。



## 4. 必须掌握的 PostgreSQL 知识

前一个 `pgsql-test` 工程已经覆盖基础 SQL。迁移到 NestJS 后，仍然必须继续掌握：

| 知识点 | Agent 场景 |
| --- | --- |
| 主键、外键和唯一约束 | 运行记录必须属于有效任务；幂等键不能重复 |
| `jsonb` | 保存不同 Agent 或工具结构不同的输入输出 |
| `timestamptz` | 保存任务创建、可领取、锁定和更新时间 |
| 索引 | 加速待领取任务、运行记录和列表分页 |
| `INSERT ... ON CONFLICT` | 实现重复请求安全重试 |
| 事务 | 一次业务动作涉及多张表时保持原子性 |
| MVCC 和锁 | 多个 worker 并发领取任务时避免重复执行 |
| `EXPLAIN ANALYZE` | 判断 ORM 生成 SQL 是否需要优化 |
| migration | 已有数据不能依赖删除数据目录重新初始化 |
| 最小权限、备份和监控 | 生产环境不能只关注代码能否运行 |

### 4.1 为什么使用 JSONB

[`AgentTask.metadata`](../src/learning/entities/agent-task.entity.ts#L36) 和 [`AgentRun.input`](../src/learning/entities/agent-run.entity.ts#L34) 使用 `jsonb`。

适合放入 JSONB：

```json
{
  "agent": "research-agent",
  "priority": "high",
  "tags": ["postgresql", "nestjs"]
}
```

不适合藏入 JSONB：

- 经常过滤的 `status`。
- 需要唯一约束的 `externalKey`。
- 需要排序的 `availableAt`。
- 关系外键 `taskId`。

这些字段应该使用普通列，便于添加约束和索引。

### 4.2 为什么需要幂等键

外部请求可能因为超时而重试。第一次请求已经写入成功，但客户端没有收到响应；第二次请求再次提交同一任务。

扩展代码使用：

```ts
conflictPaths: ['externalKey']
```

源码见 [`src/learning/learning.service.ts` L36-L49](../src/learning/learning.service.ts#L36)。

数据库中的唯一约束见 [`agent-task.entity.ts` L28-L29](../src/learning/entities/agent-task.entity.ts#L28)。

两者共同保证重复请求更新同一任务，而不是创建两条重复记录。

### 4.3 为什么任务领取需要锁

两个 worker 同时查询：

```sql
SELECT id
FROM learning_agent_tasks
WHERE status = 'queued'
LIMIT 1;
```

可能读到同一条任务。

扩展代码使用：

```sql
FOR UPDATE SKIP LOCKED
```

含义：

| 片段 | 作用 |
| --- | --- |
| `FOR UPDATE` | 锁定当前事务领取的任务行 |
| `SKIP LOCKED` | 遇到其他 worker 已锁定的任务时跳过，不等待 |

源码见 [`src/learning/learning.service.ts` L180-L202](../src/learning/learning.service.ts#L180)。

## 5. 按需深入的知识

完成基础学习后，根据项目需求继续深入：

| 需求 | 继续学习 |
| --- | --- |
| 多租户 Agent 平台 | `tenant_id`、Row-Level Security、按租户复合索引 |
| 大规模知识库 | 文档切片、metadata GIN、pgvector HNSW、全文检索和混合召回 |
| 大量后台任务 | 专用消息队列、任务重试、死信队列、超时恢复 |
| 长时间 Agent 运行 | checkpoint、状态机、续租和可恢复执行 |
| 高频统计 | 慢 SQL、`EXPLAIN ANALYZE`、物化视图、分区 |
| 多实例部署 | 连接池总量、超时、健康检查和优雅关闭 |
| 线上结构升级 | migration 回滚策略、兼容发布、备份恢复演练 |

## 6. 学习完成标准

- [ ] 我能画出请求从 Controller 到 PostgreSQL 的完整调用链。
- [ ] 我能解释为什么 DTO 需要运行时校验装饰器。
- [ ] 我能区分 Repository、EntityManager、QueryBuilder 和 QueryRunner。
- [ ] 我知道 Entity 不是数据库本身，migration 才是生产结构演进记录。
- [ ] 我能解释 JSONB 与普通列的边界。
- [ ] 我能解释 UPSERT、乐观锁和行锁分别解决什么并发问题。
- [ ] 我知道 ORM 生成 SQL 后仍然需要理解 PostgreSQL。

## 官方参考资料

- [NestJS Database Techniques](https://docs.nestjs.com/techniques/database)
- [NestJS Validation](https://docs.nestjs.com/techniques/validation)
- [NestJS Configuration](https://docs.nestjs.com/techniques/configuration)
- [TypeORM Repository](https://typeorm.io/docs/working-with-entity-manager/working-with-repository)
- [TypeORM Repository APIs](https://typeorm.io/docs/working-with-entity-manager/repository-api)
- [TypeORM Transactions](https://typeorm.io/docs/advanced-topics/transactions/)
- [TypeORM QueryRunner](https://typeorm.io/docs/query-runner)
- [PostgreSQL JSON Types](https://www.postgresql.org/docs/16/datatype-json.html)
- [PostgreSQL Explicit Locking](https://www.postgresql.org/docs/16/explicit-locking.html)
