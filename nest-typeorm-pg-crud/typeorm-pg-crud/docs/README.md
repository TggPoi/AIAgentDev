# NestJS + TypeORM + PostgreSQL 系统学习路线

当前工程来自教程后半部分。原始教程代码已经展示：

- NestJS 如何启动 HTTP 服务。
- TypeORM 如何连接 PostgreSQL。
- Entity 如何映射 `users`、`conversations`、`messages`。
- `ManyToOne` 与 `OneToMany` 如何表达一对多关系。
- TypeORM 如何查询关联数据。
- pgvector 语义检索为什么仍然需要原生 SQL。

原教程代码保留在 `conversations` 模块中。为了系统学习，工程新增独立的 `learning` 模块和 `learning_agent_*` 表，不会改变原有接口语义。

## 1. 学习顺序

| 顺序 | 文档 | 目标 |
| --- | --- | --- |
| 1 | [教程工程导读](./typeorm-pg-crud-learning-guide.md) | 读懂教程原本实现的 Entity、关系、Controller、Service 和 pgvector 查询 |
| 2 | [NestJS 操作 PostgreSQL 必学知识](./01-nest-typeorm-postgresql-must-know.md) | 建立系统知识地图，区分必须掌握和按需深入内容 |
| 3 | [learning 模块代码导读](./02-learning-module-code-guide.md) | 阅读扩展代码，掌握 Repository、DTO 校验、分页、事务、UPSERT 和锁 |
| 4 | [运行练习与生产化边界](./03-practice-and-production-checklist.md) | 调用新增接口，观察 SQL，并理解 migration、安全、测试和运维边界 |

旧工程 PostgreSQL 基础文档仍然可以作为查询手册：

- [`pgsql-test/docs/README.md`](../../../pgsql-test/docs/README.md)
- [`pgsql-test/docs/07-agent-development-postgresql-roadmap.md`](../../../pgsql-test/docs/07-agent-development-postgresql-roadmap.md)
- [`pgsql-test/docs/09-concurrency-performance-and-operations.md`](../../../pgsql-test/docs/09-concurrency-performance-and-operations.md)

## 2. 新增学习代码导航

| 源码 | 学习目标 |
| --- | --- |
| [`src/main.ts` L1-L18](../src/main.ts#L1) | 注册全局 `ValidationPipe` |
| [`src/config/database.config.ts` L1-L12](../src/config/database.config.ts#L1) | 将数据库配置改为环境变量 |
| [`src/app.module.ts` L16-L31](../src/app.module.ts#L16) | 使用 `ConfigModule` 和 `TypeOrmModule.forRootAsync()` |
| [`src/learning/learning.module.ts` L1-L17](../src/learning/learning.module.ts#L1) | 使用 `TypeOrmModule.forFeature()` 注册 Repository |
| [`src/learning/entities/agent-task.entity.ts` L22-L98](../src/learning/entities/agent-task.entity.ts#L22) | 学习 UUID、JSONB、枚举、索引和版本列 |
| [`src/learning/entities/agent-run.entity.ts` L20-L67](../src/learning/entities/agent-run.entity.ts#L20) | 学习运行记录和多对一关系 |
| [`src/learning/learning.controller.ts` L19-L95](../src/learning/learning.controller.ts#L19) | 学习 CRUD、分页、UPSERT、事务和领取任务路由 |
| [`src/learning/learning.service.ts` L30-L66](../src/learning/learning.service.ts#L30) | 学习 Repository 创建和幂等 UPSERT |
| [`src/learning/learning.service.ts` L69-L115](../src/learning/learning.service.ts#L69) | 学习 QueryBuilder 游标分页 |
| [`src/learning/learning.service.ts` L133-L173](../src/learning/learning.service.ts#L133) | 学习乐观锁更新 |
| [`src/learning/learning.service.ts` L190-L215](../src/learning/learning.service.ts#L190) | 学习事务回调 |
| [`src/learning/learning.service.ts` L218-L267](../src/learning/learning.service.ts#L218) | 学习 `QueryRunner` 和 `FOR UPDATE SKIP LOCKED` |
| [`src/migrations/1760000000000-CreateLearningAgentTables.ts` L1-L84](../src/migrations/1760000000000-CreateLearningAgentTables.ts#L1) | 学习 migration 的 `up()` 和 `down()` |

## 3. 原教程接口与新增学习接口

原教程接口：

```text
GET  /conversations/users/:userId
GET  /conversations/:id/messages
POST /conversations/:id/search
```

新增学习接口：

```text
POST   /learning/tasks
POST   /learning/tasks/upsert
POST   /learning/tasks/claim
GET    /learning/tasks/stats
GET    /learning/tasks
GET    /learning/tasks/:id
PATCH  /learning/tasks/:id
DELETE /learning/tasks/:id
POST   /learning/tasks/:id/runs
```

新增接口用于学习数据库工程化模式，不是完整的 Agent 产品 API。

## 4. 两种数据库结构管理方式

本地学习默认保留：

```dotenv
DATABASE_SYNCHRONIZE=true
```

启动 NestJS 时，TypeORM 会根据 Entity 创建学习表，便于快速运行示例。

生产思维必须切换为：

```dotenv
DATABASE_SYNCHRONIZE=false
```

并执行 migration。新增 migration 文件：

```text
src/migrations/1760000000000-CreateLearningAgentTables.ts
```

不要在同一个已有数据库中先让 `synchronize` 创建学习表，再直接运行创建相同表的 migration。具体练习方式见 [运行练习与生产化边界](./03-practice-and-production-checklist.md)。

## 5. 学完后的能力目标

- [ ] 我能解释 NestJS 的 Module、Controller、Provider 和依赖注入。
- [ ] 我能使用 DTO 和 `ValidationPipe` 拒绝非法请求。
- [ ] 我能区分 `EntityManager`、`Repository`、`QueryBuilder` 和原生 SQL。
- [ ] 我能解释 Entity 关系哪一侧保存外键。
- [ ] 我能解释稳定分页为什么需要第二排序字段。
- [ ] 我能解释 `UPSERT` 如何解决重复请求。
- [ ] 我能解释事务回调为什么必须使用回调参数中的 manager。
- [ ] 我能解释 `FOR UPDATE SKIP LOCKED` 如何防止 worker 重复领取任务。
- [ ] 我能区分 `synchronize` 和 migration。
- [ ] 我知道生产环境还需要独立测试数据库、权限管理、备份和监控。

## 官方参考资料

- [NestJS Database Techniques](https://docs.nestjs.com/techniques/database)
- [NestJS Validation](https://docs.nestjs.com/techniques/validation)
- [NestJS Configuration](https://docs.nestjs.com/techniques/configuration)
- [TypeORM Repository](https://typeorm.io/docs/working-with-entity-manager/working-with-repository)
- [TypeORM Transactions](https://typeorm.io/docs/advanced-topics/transactions/)
- [TypeORM Migrations](https://typeorm.io/docs/advanced-topics/migrations)
- [PostgreSQL Explicit Locking](https://www.postgresql.org/docs/16/explicit-locking.html)
