# TypeORM + NestJS + PostgreSQL 工程学习指南

本文档用于学习教程后半部分实现的 `typeorm-pg-crud` 工程。

实际工程路径：

```text
D:\AI_Agent_Project\nest-typeorm-pg-crud\typeorm-pg-crud
```

这不是一份 TypeORM API 百科。它会围绕当前工程解释必须掌握的知识，并补充从学习示例走向真实项目时不能忽略的内容。

完成本指南后，继续按照 [docs 系统学习路线](./README.md) 学习新增的 `learning` 模块。扩展文档和代码会进一步覆盖 Repository CRUD、DTO 运行时校验、环境配置、游标分页、UPSERT、事务、乐观锁、`FOR UPDATE SKIP LOCKED` 和 migration。

## 1. 学习前提

开始本工程前，应该先理解：

- PostgreSQL 服务、数据库、schema、表、行和列。
- `SELECT`、`INSERT`、`UPDATE`、`DELETE`。
- 主键、外键和 `ON DELETE CASCADE`。
- 一对多关系和 `JOIN`。
- 事务的 `BEGIN`、`COMMIT`、`ROLLBACK`。
- pgvector 的 `vector(1024)`、余弦距离运算符 `<=>` 和 HNSW 索引。

这些内容可以先阅读旧工程中的 [PostgreSQL 学习路线](../../../pgsql-test/docs/README.md#L1)。

## 2. 这个工程解决什么问题

前一个 `pgsql-test` 工程使用 Node.js 的 `pg` 驱动手写 SQL：

```js
await query(
  "SELECT * FROM conversations WHERE user_id = $1 ORDER BY created_at DESC",
  [userId]
);
```

当前工程使用 NestJS + TypeORM 将数据库表映射为 TypeScript 类，再通过对象形式表达大部分普通查询：

```ts
const user = await this.em.findOne(User, {
  where: { id: userId },
  relations: { conversations: true },
  order: { conversations: { createdAt: 'DESC' } },
});
```

但是，pgvector 的向量距离运算符属于 PostgreSQL 扩展语法。当前工程仍然为语义检索保留了原生 SQL：

```ts
await this.em.query(
  `SELECT id, conversation_id, role, content, created_at,
          1 - (embedding <=> $1::vector) AS similarity
   FROM messages
   WHERE conversation_id = $2 AND embedding IS NOT NULL
   ORDER BY embedding <=> $1::vector
   LIMIT $3`,
  [JSON.stringify(vector), conversationId, limit],
);
```

需要建立一个重要认识：

> ORM 可以减少普通 CRUD 的重复代码，但不会取代数据库知识，也不应该阻止你在必要时使用原生 SQL。

## 3. 整体架构

当前请求链路：

```text
HTTP 请求
  ↓
ConversationsController
  ↓
ConversationsService
  ↓
TypeORM EntityManager
  ↓
PostgreSQL hello_pg
```

语义搜索还会调用嵌入模型：

```text
POST /conversations/:id/search
  ↓
ConversationsController.search()
  ↓
ConversationsService.searchSimilarMessages()
  ↓
OpenAIEmbeddings.embedQuery()
  ↓
查询向量
  ↓
EntityManager.query()
  ↓
PostgreSQL + pgvector
```

工程核心文件：

| 文件 | 职责 |
| --- | --- |
| [`src/main.ts` L4](../src/main.ts#L4) | 创建 Nest 应用并监听 `3005` 端口 |
| [`src/app.module.ts` L10](../src/app.module.ts#L10) | 注册 TypeORM 数据库连接和业务模块 |
| [`src/conversations/conversations.module.ts` L5](../src/conversations/conversations.module.ts#L5) | 组织会话领域的 Controller 和 Service |
| [`src/conversations/conversations.controller.ts` L14](../src/conversations/conversations.controller.ts#L14) | 接收 HTTP 请求并提取参数 |
| [`src/conversations/conversations.service.ts` L24](../src/conversations/conversations.service.ts#L24) | 执行业务查询和语义检索 |
| [`src/conversations/entities/user.entity.ts` L10](../src/conversations/entities/user.entity.ts#L10) | 将 `users` 表映射为 `User` 类 |
| [`src/conversations/entities/conversation.entity.ts` L13](../src/conversations/entities/conversation.entity.ts#L13) | 将 `conversations` 表映射为 `Conversation` 类 |
| [`src/conversations/entities/message.entity.ts` L17](../src/conversations/entities/message.entity.ts#L17) | 将 `messages` 表映射为 `Message` 类 |
| [`src/conversations/dto/semantic-search.dto.ts` L3](../src/conversations/dto/semantic-search.dto.ts#L3) | 描述语义搜索请求体 |

### 3.1 关键实现源码导航

| 知识点 | 对应源码 |
| --- | --- |
| 创建 Nest 应用 | [`NestFactory.create()` L5](../src/main.ts#L5) |
| 监听 `3005` 端口 | [`app.listen()` L6](../src/main.ts#L6) |
| 配置 PostgreSQL 连接 | [`TypeOrmModule.forRootAsync()` L20-L27](../src/app.module.ts#L20) |
| 数据库环境变量映射 | [`database.config.ts` L3-L11](../src/config/database.config.ts#L3) |
| 注册业务模块 | [`ConversationsModule` L23](../src/app.module.ts#L23) |
| 注册 Controller 和 Service | [`@Module()` L5-L8](../src/conversations/conversations.module.ts#L5) |
| `User` 实体 | [`User` L10-L22](../src/conversations/entities/user.entity.ts#L10) |
| `Conversation` 实体 | [`Conversation` L13-L32](../src/conversations/entities/conversation.entity.ts#L13) |
| `Message` 实体 | [`Message` L17-L44](../src/conversations/entities/message.entity.ts#L17) |
| 用户到会话关系 | [`@ManyToOne()` L27-L29](../src/conversations/entities/conversation.entity.ts#L27) |
| 会话到消息关系 | [`@ManyToOne()` L40-L44](../src/conversations/entities/message.entity.ts#L40) |
| 查询用户会话 | [`findConversationsByUserId()` L34-L46](../src/conversations/conversations.service.ts#L34) |
| 查询会话消息 | [`findMessagesByConversationId()` L49-L75](../src/conversations/conversations.service.ts#L49) |
| pgvector 语义检索 | [`searchSimilarMessages()` L78-L107](../src/conversations/conversations.service.ts#L78) |
| 创建嵌入模型客户端 | [`getEmbeddings()` L109-L125](../src/conversations/conversations.service.ts#L109) |
| 查询用户会话路由 | [`GET /conversations/users/:userId` L18-L22](../src/conversations/conversations.controller.ts#L18) |
| 查询会话消息路由 | [`GET /conversations/:id/messages` L24-L28](../src/conversations/conversations.controller.ts#L24) |
| 语义搜索路由 | [`POST /conversations/:id/search` L30-L43](../src/conversations/conversations.controller.ts#L30) |

## 4. 启动工程

### 4.1 启动共享 PostgreSQL

数据库由旧的 `pgsql-test` 工程提供。在 PowerShell 中执行：

```powershell
cd D:\AI_Agent_Project\pgsql-test
docker compose up -d
docker compose ps
```

`pg_vector_db` 应显示为 `healthy`。

### 4.2 启动 NestJS 服务

```powershell
cd D:\AI_Agent_Project\nest-typeorm-pg-crud\typeorm-pg-crud
pnpm.cmd run start:dev
```

如果你的 PowerShell 允许执行 `pnpm.ps1`，也可以使用：

```powershell
pnpm run start:dev
```

当前 Windows 环境中，直接调用 `pnpm` 可能被 PowerShell 执行策略阻止。使用 `pnpm.cmd` 可以绕过这个脚本入口问题。

### 4.3 验证基础接口

另开一个 PowerShell 窗口：

```powershell
Invoke-RestMethod -Uri http://localhost:3005/
```

应返回：

```text
Hello World!
```

端口来自 [`src/main.ts` L4-L8](../src/main.ts#L4)：

```ts
await app.listen(process.env.PORT ?? 3005);
```

## 5. NestJS 基础：Module、Controller、Provider

NestJS 使用模块组织应用。

### 5.1 Module

[`src/conversations/conversations.module.ts` L5-L9](../src/conversations/conversations.module.ts#L5)：

```ts
@Module({
  controllers: [ConversationsController],
  providers: [ConversationsService],
})
export class ConversationsModule {}
```

含义：

| 配置 | 含义 |
| --- | --- |
| `controllers` | 注册处理 HTTP 请求的控制器 |
| `providers` | 注册可以被依赖注入系统创建和管理的对象 |

根模块 [`src/app.module.ts` L10-L28](../src/app.module.ts#L10) 导入业务模块：

```ts
imports: [
  TypeOrmModule.forRootAsync({ ... }),
  ConversationsModule,
]
```

### 5.2 Controller

Controller 负责 HTTP 层：

```ts
@Controller('conversations')
export class ConversationsController {
  constructor(private readonly conversationsService: ConversationsService) {}
}
```

`@Controller('conversations')` 表示该控制器下的路由都以 `/conversations` 开头。

### 5.3 Provider 和依赖注入

Service 使用 `@Injectable()` 声明为 Provider：

```ts
@Injectable()
export class ConversationsService {}
```

Controller 不需要手动执行：

```ts
new ConversationsService();
```

它只需要在构造函数中声明依赖：

```ts
constructor(private readonly conversationsService: ConversationsService) {}
```

NestJS 会根据模块注册信息创建 Service，并将实例注入 Controller。

这称为依赖注入，简称 DI。

### 5.4 请求流

以查询用户会话为例：

```text
GET /conversations/users/1
  ↓
ConversationsController.findByUser(1)
  ↓
ConversationsService.findConversationsByUserId(1)
  ↓
EntityManager.findOne(User, ...)
  ↓
PostgreSQL
```

Controller 的职责应该尽量薄：

- 提取请求参数。
- 进行输入转换和基础校验。
- 调用 Service。
- 返回结果。

业务查询、事务和外部服务调用应该放在 Service 中。



## 6. TypeOrmModule.forRootAsync：连接 PostgreSQL

教程最初使用 `TypeOrmModule.forRoot({ ... })` 直接写入数据库配置。扩展代码已经改为 [`src/app.module.ts` L20-L27](../src/app.module.ts#L20)：

```ts
TypeOrmModule.forRootAsync({
  imports: [ConfigModule.forFeature(databaseConfig)],
  inject: [databaseConfig.KEY],
  useFactory: (config) => ({
    ...config,
    entities: [User, Conversation, Message, AgentTask, AgentRun],
  }),
})
```

**在当前文件里，你要分两层看：**

```ts
TypeOrmModule.forRootAsync({
  imports: [ConfigModule.forFeature(databaseConfig)],
  inject: [databaseConfig.KEY],
  useFactory: (config: ConfigType<typeof databaseConfig>) => ({
    ...config,
    entities: [User, Conversation, Message, AgentTask, AgentRun],
  }),
})
```

## 1. `forRootAsync({ ... })` 外层需要什么？

外层是 NestJS 的“异步配置写法”，常见配置是：

| 配置项       | 当前代码                                  | 作用                                                |
| ------------ | ----------------------------------------- | --------------------------------------------------- |
| `imports`    | `ConfigModule.forFeature(databaseConfig)` | 先加载 `databaseConfig` 这组配置                    |
| `inject`     | `[databaseConfig.KEY]`                    | 告诉 NestJS 把 `databaseConfig` 注入给 `useFactory` |
| `useFactory` | `(config) => ({ ... })`                   | 返回真正给 TypeORM 使用的数据库配置                 |

也就是说，外层不是数据库配置本身，而是告诉 NestJS：

> 我要异步生成 TypeORM 配置，生成配置前先注入 `databaseConfig`。

## 2. `useFactory` 返回值需要什么？

`useFactory` 里面返回的对象，才是真正的 TypeORM 数据库连接配置：

```ts
{
  ...config,
  entities: [User, Conversation, Message, AgentTask, AgentRun],
}
```

其中 `...config` 来自：

```ts
registerAs('database', () => ({
  type: 'postgres' as const,
  host: process.env.DATABASE_HOST ?? 'localhost',
  port: Number.parseInt(process.env.DATABASE_PORT ?? '5432', 10),
  username: process.env.DATABASE_USERNAME ?? 'user',
  password: process.env.DATABASE_PASSWORD ?? '123456',
  database: process.env.DATABASE_NAME ?? 'hello_pg',
  synchronize: (process.env.DATABASE_SYNCHRONIZE ?? 'true') === 'true',
  logging: (process.env.DATABASE_LOGGING ?? 'true') === 'true',
}));
```

所以最终传给 TypeORM 的配置大概等价于：

```ts
{
  type: 'postgres',
  host: 'localhost',
  port: 5432,
  username: 'user',
  password: '123456',
  database: 'hello_pg',
  synchronize: true,
  logging: true,
  entities: [User, Conversation, Message, AgentTask, AgentRun],
}
```

## 3. 哪些是必须的？

对当前 PostgreSQL 连接，核心必须有：

```ts
type: 'postgres'
host: 'localhost'
port: 5432
username: 'user'
password: '123456'
database: 'hello_pg'
entities: [...]
```

否则 TypeORM 不知道：

- 用什么数据库驱动。
- 连接哪个 PostgreSQL。
- 用哪个账号密码。
- 连接哪个 database。
- 哪些 Entity 需要被 ORM 管理。

## 4. 哪些是常用但不是绝对必填？

```ts
synchronize: true
logging: true
```

含义：

- `synchronize`：启动时根据 Entity 自动同步表结构。本地学习方便，生产环境不要开。
- `logging`：打印 SQL，学习时很有用。

生产环境通常改成：

```ts
synchronize: false
logging: false
```

再用 migration 管理表结构。

## 5. 怎么知道 `forRootAsync` 需要哪些配置？

有三个判断来源。

第一，看 TypeScript 类型提示。

在 VS Code 里把鼠标放到：

```ts
TypeOrmModule.forRootAsync
```

通常会看到它需要：

```ts
TypeOrmModuleAsyncOptions
```

这个类型决定了外层可以写：

```ts
imports
inject
useFactory
useClass
useExisting
```

第二，看 `useFactory` 返回值类型。

`useFactory` 返回的是 TypeORM 连接配置，接近：

```ts
TypeOrmModuleOptions
```

它内部包含 TypeORM 的 `DataSourceOptions`，也就是数据库连接需要的配置。

第三，看当前代码实际拆分。

当前项目把配置拆成了两部分：

```ts
// database.config.ts
type, host, port, username, password, database, synchronize, logging
```

加上：

```ts
// app.module.ts
entities
```

所以你读当前文件时可以这样判断：

```text
forRootAsync 外层：NestJS 如何拿到配置
useFactory 返回值：TypeORM 如何连接数据库
database.config.ts：数据库连接参数从哪里来
entities：哪些表实体交给 TypeORM 管理
```

一句话总结：

> `forRootAsync` 需要的不是一组固定“业务字段”，而是 NestJS 异步配置外壳 + TypeORM 数据库连接配置。当前项目中，数据库连接参数来自 `database.config.ts`，Entity 列表在 `app.module.ts` 中补上。



配置值集中定义在 [`src/config/database.config.ts` L3-L11](../src/config/database.config.ts#L3)：

```ts
export default registerAs('database', () => ({
  type: 'postgres' as const,
  host: process.env.DATABASE_HOST ?? 'localhost',
  port: Number.parseInt(process.env.DATABASE_PORT ?? '5432', 10),
  username: process.env.DATABASE_USERNAME ?? 'user',
  password: process.env.DATABASE_PASSWORD ?? '123456',
  database: process.env.DATABASE_NAME ?? 'hello_pg',
  synchronize: (process.env.DATABASE_SYNCHRONIZE ?? 'true') === 'true',
  logging: (process.env.DATABASE_LOGGING ?? 'true') === 'true',
}));
```

`registerAs` 是 `@nestjs/config` 提供的配置命名工具，用来把一组配置注册成一个“有名字的配置块”。

在当前工程里类似这样：

这里：

```ts
registerAs('database', () => ({ ... }))
```

含义是：

- `'database'`：给这组配置起名，叫 `database`。
- `() => ({ ... })`：返回真正的配置对象。
- 这个配置对象会从 `process.env` 读取环境变量。
- 如果环境变量不存在，就使用本地学习默认值。

它的作用是让数据库配置集中管理，而不是直接写在 `app.module.ts` 里。

在 `app.module.ts` 中一般这样使用：

```ts
ConfigModule.forFeature(databaseConfig)
```

然后注入：

```ts
inject: [databaseConfig.KEY]
```

再拿到配置：

```ts
useFactory: (config: ConfigType<typeof databaseConfig>) => ({
  ...config,
  entities: [User, Conversation, Message, AgentTask, AgentRun],
})
```

简单说：

> `registerAs` 就是给一组配置起名字，并让 NestJS 可以按这个名字注入这组配置。

当前这里注册的是数据库配置。



逐项理解：

| 配置 | 本地默认值 | 含义 |
| --- | --- | --- |
| `type` | `'postgres'` | 使用 PostgreSQL 驱动 |
| `host` | `'localhost'` | NestJS 在 Windows 主机运行，通过映射端口连接数据库 |
| `port` | `5432` | PostgreSQL 端口 |
| `username` | `'user'` | 数据库用户 |
| `password` | `'123456'` | 仅用于本地学习的默认密码 |
| `database` | `'hello_pg'` | 连接的数据库 |
| `entities` | 五个实体类 | 三个教程实体和两个 `learning` 实体 |
| `logging` | `true` | 在终端输出 TypeORM 执行的 SQL |
| `synchronize` | `true` | 本地默认开启；启动时根据实体尝试同步表结构 |



## 5.1、TypeOrmModuleAsyncOptions 配置的查询使用

`TypeOrmModuleAsyncOptions` 不需要一开始就背。你可以按“官方文档 + 本地类型定义 + 当前代码”三步查。

### 1. 官方文档在哪里看？

优先看 NestJS 官方文档：

- NestJS Database Techniques  
  https://docs.nestjs.com/techniques/database

这个页面讲 `@nestjs/typeorm`、`TypeOrmModule.forRoot()`、`forRootAsync()`、`forFeature()` 等用法。

再看配置模块：

- NestJS Configuration  
  https://docs.nestjs.com/techniques/configuration

因为你当前代码里的：

```ts
ConfigModule.forRoot()
ConfigModule.forFeature(databaseConfig)
registerAs(...)
```

都属于配置模块内容。

TypeORM 本身的数据库连接配置看这里：

- TypeORM DataSource Options / Getting Started  
  https://typeorm.io/docs/getting-started/

### 2. `TypeOrmModuleAsyncOptions` 是什么？

它是 `@nestjs/typeorm` 中定义的 TypeScript 类型，用来描述：

```ts
TypeOrmModule.forRootAsync({
  ...
})
```

这个对象里可以写哪些字段。

你当前用的是这一种写法：

```ts
TypeOrmModule.forRootAsync({
  imports: [ConfigModule.forFeature(databaseConfig)],
  inject: [databaseConfig.KEY],
  useFactory: (config: ConfigType<typeof databaseConfig>) => ({
    ...config,
    entities: [User, Conversation, Message, AgentTask, AgentRun],
  }),
})
```

这正是 `TypeOrmModuleAsyncOptions` 的常见用法。

### 3. 它常见有哪些字段？

常见字段如下：

| 字段                | 作用                                                         |
| ------------------- | ------------------------------------------------------------ |
| `imports`           | 先导入某些模块，让当前配置可以使用这些**模块提供的 Provider** |
| `inject`            | 指定要注入给 `useFactory` 的**依赖**                         |
| `useFactory`        | 一个函数，返回真正的 TypeORM 配置                            |
| `useClass`          | 使用某个类来创建 TypeORM 配置                                |
| `useExisting`       | 复用已经存在的配置类                                         |
| `name`              | 多数据库连接时给连接起名                                     |
| `dataSourceFactory` | 自定义如何创建 TypeORM `DataSource`                          |

你现在只需要先掌握三个：

```ts
imports
inject
useFactory
```

其他的等遇到多数据库、配置类、定制 DataSource 时再学。

### 4. 当前代码怎么理解？

```ts
imports: [ConfigModule.forFeature(databaseConfig)]
```

意思是：

> 当前 TypeORM 配置需要用到 `databaseConfig`，所以先导入它。

```ts
inject: [databaseConfig.KEY]
```

意思是：

> 把名为 `database` 的配置对象注入进来。

```ts
useFactory: (config: ConfigType<typeof databaseConfig>) => ({
  ...config,
  entities: [User, Conversation, Message, AgentTask, AgentRun],
})
```

意思是：

> 拿到数据库配置后，返回 TypeORM 真正需要的连接配置。

最终结果大概是：

```ts
{
  type: 'postgres',
  host: 'localhost',
  port: 5432,
  username: 'user',
  password: '123456',
  database: 'hello_pg',
  synchronize: true,
  logging: true,
  entities: [User, Conversation, Message, AgentTask, AgentRun],
}
```

### 5. 在本地源码里怎么查类型？

如果你想看最准确的类型定义，可以在工程里搜索：

```powershell
rg "interface TypeOrmModuleAsyncOptions" node_modules/@nestjs/typeorm
```

或者在 VS Code 中：

1. 按住 `Ctrl`
2. 点击 `forRootAsync`
3. 跳到类型定义
4. 找 `TypeOrmModuleAsyncOptions`

你会看到它大概长这样：

```ts
export interface TypeOrmModuleAsyncOptions {
  imports?: any[];
  inject?: any[];
  useFactory?: (...args: any[]) => TypeOrmModuleOptions | Promise<TypeOrmModuleOptions>;
  useClass?: Type<TypeOrmOptionsFactory>;
  useExisting?: Type<TypeOrmOptionsFactory>;
  name?: string;
  dataSourceFactory?: TypeOrmDataSourceFactory;
}
```

不同版本字段可能略有差异，所以本地 `node_modules` 里的类型定义是当前项目最准确的。

### 6. 学习顺序建议

你现在按这个顺序学就够了：

1. `TypeOrmModule.forRoot()`：同步、直接写死配置。
2. `ConfigModule` + `registerAs()`：把配置集中管理。
3. `TypeOrmModule.forRootAsync()`：异步读取配置后再创建数据库连接。
4. `TypeOrmModule.forFeature()`：在业务模块中注入 Repository。
5. `@InjectRepository()`：在 Service 中拿到某个 Entity 的 Repository。

一句话总结：

> `TypeOrmModuleAsyncOptions` 就是 `forRootAsync()` 的参数类型。你现在不用背它，只要知道当前项目用的是 `imports + inject + useFactory` 这条主线即可。





### 6.1 为什么 logging: true 适合学习

启动服务后调用接口，观察终端中的 SQL。

例如，TypeORM 的对象查询：

```ts
relations: { conversations: true }
```

最终仍然会转换为数据库可以执行的 SQL。观察日志可以帮助你将 ORM 写法与 SQL 对应起来。

### 6.2 synchronize: true 的边界

`synchronize: true` 适合本地学习和快速原型，但不应该用于生产环境。

原因：

- 实体变更会在应用启动时自动影响数据库结构。
- 自动同步行为不适合作为可审核的数据库变更记录。
- 复杂索引、数据库扩展和数据迁移无法只依赖自动同步可靠管理。
- 错误的实体修改可能造成生产数据风险。

生产环境应使用迁移 migration。后文会展开。

### 6.3 不要在真实项目中硬编码密码

本地默认值便于学习：

```ts
password: process.env.DATABASE_PASSWORD ?? '123456'
```

真实项目应使用环境变量和配置模块，例如：

```dotenv
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USERNAME=user
DATABASE_PASSWORD=123456
DATABASE_NAME=hello_pg
```

当前工程已经通过 NestJS 的 `@nestjs/config` 和 `TypeOrmModule.forRootAsync()` 读取配置。参考 [`.env.example`](../.env.example)。

## 7. Entity：将表映射为 TypeScript 类

Entity 是 ORM 的核心概念。

```text
数据库表 users
  ↕
TypeScript 类 User
```

### 7.1 User 实体

[`src/conversations/entities/user.entity.ts` L10-L23](../src/conversations/entities/user.entity.ts#L10)：

```ts
@Entity('users')
export class User {
  @PrimaryGeneratedColumn()
  id: number;

  @Column({ type: 'text' })
  name: string;

  @CreateDateColumn({ type: 'timestamptz', name: 'created_at' })
  createdAt: Date;

  @OneToMany(() => Conversation, (conversation) => conversation.user)
  conversations: Conversation[];
}
```

装饰器含义：

| 装饰器 | 含义 |
| --- | --- |
| `@Entity('users')` | 该类映射到 `users` 表 |
| `@PrimaryGeneratedColumn()` | 自动生成的主键 |
| `@Column({ type: 'text' })` | 普通文本列 |
| `@CreateDateColumn(...)` | 创建时自动写入时间 |
| `@OneToMany(...)` | 一个用户拥有多个会话 |

TypeScript 属性可以使用驼峰命名：

```ts
createdAt
```

数据库列仍然使用下划线命名：

```text
created_at
```

映射关系通过 `name: 'created_at'` 明确指定。

### 7.2 Conversation 实体

[`src/conversations/entities/conversation.entity.ts` L13-L33](../src/conversations/entities/conversation.entity.ts#L13)：

```ts
@Entity('conversations')
export class Conversation {
  @PrimaryGeneratedColumn()
  id: number;

  @Column({ name: 'user_id' })
  userId: number;

  @Column({ type: 'text', nullable: true })
  title: string | null;

  @ManyToOne(() => User, (user) => user.conversations, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'user_id' })
  user: User;

  @OneToMany(() => Message, (message) => message.conversation)
  messages: Message[];
}
```

这里同时保存了：

```ts
userId: number;
user: User;
```

两者用途不同：

| 属性 | 用途 |
| --- | --- |
| `userId` | 直接访问外键值，例如 `conversation.userId` |
| `user` | 在加载关联后访问完整用户对象，例如 `conversation.user.name` |

### 7.3 Message 实体

[`src/conversations/entities/message.entity.ts` L11-L45](../src/conversations/entities/message.entity.ts#L11)：

```ts
export enum MessageRole {
  USER = 'user',
  ASSISTANT = 'assistant',
  SYSTEM = 'system',
}

@Entity('messages')
export class Message {
  @PrimaryGeneratedColumn()
  id: number;

  @Column({ name: 'conversation_id' })
  conversationId: number;

  @Column({
    type: 'text',
    enum: MessageRole,
  })
  role: MessageRole;

  @Column({ type: 'text' })
  content: string;

  @Column('vector', { length: 1024, nullable: true })
  embedding: number[] | null;

  @ManyToOne(() => Conversation, (conversation) => conversation.messages, {
    onDelete: 'CASCADE',
  })
  @JoinColumn({ name: 'conversation_id' })
  conversation: Conversation;
}
```

重点：

- `role` 在 TypeScript 层使用枚举。
- `embedding` 映射到 pgvector 的 `vector(1024)`。
- `embedding` 可以为空，因为不是每条消息都必须立即向量化。
- 消息属于某一个会话。



## 8.【重点】 一对多关系：拥有方和反向关系

当前工程中：

```text
User 1 ─── N Conversation
Conversation 1 ─── N Message
```

以用户和会话为例：

```ts
// User
@OneToMany(() => Conversation, (conversation) => conversation.user)
conversations: Conversation[];

// Conversation
@ManyToOne(() => User, (user) => user.conversations, { onDelete: 'CASCADE' })
@JoinColumn({ name: 'user_id' })
user: User;
```

需要理解：

- `@ManyToOne` 一侧保存外键，属于关系拥有方。
- `@JoinColumn({ name: 'user_id' })` 指定实际外键列。
- `@OneToMany` 是反向关系，方便从用户对象访问会话数组。
- `@OneToMany` 本身不会在 `users` 表中增加一列。

对应源码：

- [`User.conversations` L21-L22](../src/conversations/entities/user.entity.ts#L21)
- [`Conversation.user` L27-L29](../src/conversations/entities/conversation.entity.ts#L27)
- [`Conversation.messages` L31-L32](../src/conversations/entities/conversation.entity.ts#L31)
- [`Message.conversation` L40-L44](../src/conversations/entities/message.entity.ts#L40)



这三个装饰器是 TypeORM 用来描述“表关系”的。

用当前工程关系举例：

```text
users 1 ──── N conversations
conversations 1 ──── N messages
```

也就是：

- 一个用户可以有多个会话。
- 一个会话只属于一个用户。
- 一个会话可以有多条消息。
- 一条消息只属于一个会话。



## 8.1. `@ManyToOne`

`@ManyToOne` 表示：

> 当前这张表的很多行，都属于另一张表的一行。

例如 `Conversation`：

```ts
@ManyToOne(() => User, (user) => user.conversations, { onDelete: 'CASCADE' })
@JoinColumn({ name: 'user_id' })
user: User;
```

含义：

```text
多个 conversations 属于一个 user
```

数据库里真正保存外键的是 `conversations.user_id`。

所以 `ManyToOne` 这一侧通常是“外键所在的一侧”。

对应表结构：

```sql
conversations
-------------
id
user_id  ← 外键，指向 users.id
title
created_at
```



## 8.2. `@OneToMany`

`@OneToMany` 表示：

> 当前这张表的一行，可以对应另一张表的很多行。

例如 `User`：

```ts
@OneToMany(() => Conversation, (conversation) => conversation.user)
conversations: Conversation[];
```

含义：

```text
一个 user 有多个 conversations
```

注意：

**`@OneToMany` 这一侧通常不保存外键。**

`users` 表里不会多出一个 `conversations` 字段。

**它只是告诉 TypeORM：**

> **如果我要从 User 对象访问会话列表，可以通过 `conversations` 这个属性拿到。**



## 8.3. `@JoinColumn`

`@JoinColumn` 用来说明：

> **当前关系使用数据库中的哪一个外键列连接。**

例如：

```ts
@JoinColumn({ name: 'user_id' })
user: User;
```

意思是：

```text
Conversation.user 这个关系，使用 conversations 表里的 user_id 列连接 users.id
```

没有它，TypeORM 可能会按照默认命名规则猜列名，比如 `userId` 或 `user_id`。你显式写出来，关系更清楚，也能匹配现有数据库字段。



## 4. 三者放在一起看

### User 实体

```ts
@Entity('users')
export class User {
  @PrimaryGeneratedColumn()
  id: number;

  @OneToMany(() => Conversation, (conversation) => conversation.user)
  conversations: Conversation[];
}
```

意思：

```text
一个 User 有多个 Conversation
```

但 `users` 表不保存外键。

### Conversation 实体

```ts
@Entity('conversations')
export class Conversation {
  @Column({ name: 'user_id' })
  userId: number;

  @ManyToOne(() => User, (user) => user.conversations, { onDelete: 'CASCADE' })
  @JoinColumn({ name: 'user_id' })
  user: User;
}
```

意思：

```text
多个 Conversation 属于一个 User
```

并且使用：

```text
conversations.user_id
```

连接：

```text
users.id
```

## 5. 最重要的理解

| 装饰器        | 含义                         | 是否保存外键       |
| ------------- | ---------------------------- | ------------------ |
| `@OneToMany`  | 一的一侧，可以访问多个子记录 | 否                 |
| `@ManyToOne`  | 多的一侧，属于某个父记录     | 通常是             |
| `@JoinColumn` | 指定当前关系使用哪个外键列   | 用在拥有外键的一侧 |

一句话记忆：

> 外键通常在 `@ManyToOne` 那一侧，`@OneToMany` 只是反向访问列表，`@JoinColumn` 指明外键列名。





### 8.1 【重点】onDelete: 'CASCADE' 与 cascade: true 不同

当前实体使用：

```ts
{ onDelete: 'CASCADE' }
```

对应源码：

- [`Conversation.user` 的 `onDelete` L27](../src/conversations/entities/conversation.entity.ts#L27)
- [`Message.conversation` 的 `onDelete` L40-L42](../src/conversations/entities/message.entity.ts#L40)

它表示数据库删除行为：

```text
删除 users 行
  ↓
数据库自动删除关联 conversations 行
  ↓
数据库自动删除关联 messages 行
```

TypeORM 关系还支持另一种配置：

```ts
{ cascade: true }
```

它主要影响 ORM 保存关联对象时，是否自动插入或更新关联实体。

不要混淆：

| 配置 | 关注点 |
| --- | --- |
| `onDelete: 'CASCADE'` | 删除数据库记录时的外键行为 |
| `cascade: true` | ORM 保存关联对象时是否联动保存 |



## 9. EntityManager：操作多个实体

[`src/conversations/conversations.service.ts` L24-L31](../src/conversations/conversations.service.ts#L24) 注入：

```ts
constructor(
  @InjectEntityManager()
  private readonly em: EntityManager,
) {}
```

`EntityManager` 可以操作当前连接中的多个实体：

```ts
this.em.findOne(User, ...)
this.em.findOne(Conversation, ...)
this.em.query(...)
```

当前 Service 同时查询用户、会话和消息，使用 `EntityManager` 是合理的学习写法。

### 9.1 查询用户的会话

```ts
const user = await this.em.findOne(User, {
  where: { id: userId },
  relations: { conversations: true },
  order: { conversations: { createdAt: 'DESC' } },
});
```

对应源码：[`findConversationsByUserId()` L34-L46](../src/conversations/conversations.service.ts#L34)。

逐项理解：

| 选项 | 含义 |
| --- | --- |
| `User` | 查询 `users` 表对应的实体 |
| `where: { id: userId }` | 按用户主键过滤 |
| `relations: { conversations: true }` | 同时加载该用户的会话 |
| `order` | 会话按创建时间倒序排列 |

没有找到用户时：

```ts
throw new NotFoundException(`User #${userId} not found`);
```

对应源码：[`NotFoundException` L41-L43](../src/conversations/conversations.service.ts#L41)。

NestJS 会将它转换为 HTTP `404 Not Found` 响应。

### 9.2 查询会话的消息

```ts
const conversation = await this.em.findOne(Conversation, {
  where: { id: conversationId },
  relations: { messages: true },
  order: { messages: { createdAt: 'ASC' } },
});
```

对应源码：[`findMessagesByConversationId()` L49-L75](../src/conversations/conversations.service.ts#L49)。

消息按创建时间正序排列，因为聊天记录通常需要从旧到新展示。

返回前进行映射：

```ts
messages: conversation.messages.map(
  ({ id, conversationId, role, content, createdAt }) => ({
    id,
    conversationId,
    role,
    content,
    createdAt,
  }),
),
```

对应源码：[`messages.map()` L65-L73](../src/conversations/conversations.service.ts#L65)。

这样不会将 `embedding` 返回给客户端。向量通常体积较大，普通聊天记录接口没有必要返回它。

## 10. EntityManager 与 Repository 如何选择

TypeORM 还支持 Repository：

```ts
const userRepository = dataSource.getRepository(User);
```

在 NestJS 中，常见写法是：

```ts
@Module({
  imports: [TypeOrmModule.forFeature([User, Conversation, Message])],
  providers: [ConversationsService],
})
export class ConversationsModule {}
```

Service 中注入：

```ts
constructor(
  @InjectRepository(User)
  private readonly usersRepository: Repository<User>,
) {}
```

两种方式都可以使用：

| 方式 | 适合场景 |
| --- | --- |
| `EntityManager` | 一个 Service 需要跨多个实体操作，或需要执行原生 SQL |
| `Repository<Entity>` | 一个 Service 主要围绕单个实体组织 CRUD，便于明确依赖和单元测试 |

当前工程使用全局 `EntityManager`，因此 [`conversations.module.ts` L5-L8](../src/conversations/conversations.module.ts#L5) 没有导入 `TypeOrmModule.forFeature(...)`。

## 11. Controller：路由、参数和 Pipe

[`src/conversations/conversations.controller.ts` L14-L44](../src/conversations/conversations.controller.ts#L14) 暴露三个接口。

### 11.1 查询用户的会话

```ts
@Get('users/:userId')
findByUser(@Param('userId', ParseIntPipe) userId: number) {
  return this.conversationsService.findConversationsByUserId(userId);
}
```

对应源码：[`GET /conversations/users/:userId` L18-L22](../src/conversations/conversations.controller.ts#L18)。

请求：

```text
GET /conversations/users/1
```

`ParseIntPipe` 将 URL 中的字符串 `"1"` 转换为数字 `1`。如果传入 `abc`，NestJS 会返回 `400 Bad Request`。

### 11.2 查询会话中的消息

```ts
@Get(':id/messages')
findMessages(@Param('id', ParseIntPipe) id: number) {
  return this.conversationsService.findMessagesByConversationId(id);
}
```

对应源码：[`GET /conversations/:id/messages` L24-L28](../src/conversations/conversations.controller.ts#L24)。

请求：

```text
GET /conversations/1/messages
```

### 11.3 语义检索

```ts
@Post(':id/search')
search(
  @Param('id', ParseIntPipe) id: number,
  @Body() dto: SemanticSearchDto,
  @Query('limit', new DefaultValuePipe(5), ParseIntPipe) queryLimit?: number,
) {
  const limit = dto.limit ?? queryLimit ?? 5;
  return this.conversationsService.searchSimilarMessages(
    id,
    dto.query,
    limit,
  );
}
```

对应源码：[`POST /conversations/:id/search` L30-L43](../src/conversations/conversations.controller.ts#L30)。

请求：

```text
POST /conversations/1/search?limit=5
Content-Type: application/json

{
  "query": "如何查询向量相似度？",
  "limit": 3
}
```

优先级：

```text
请求体 dto.limit
  ↓ 如果没有
URL 查询参数 queryLimit
  ↓ 如果没有
默认值 5
```

## 12. DTO 与运行时校验

教程最初的 DTO 只有 TypeScript 字段声明。扩展代码已经为语义检索 DTO 添加运行时校验：

```ts
import { Type } from 'class-transformer';
import {
  IsInt,
  IsNotEmpty,
  IsOptional,
  IsString,
  Max,
  MaxLength,
  Min,
} from 'class-validator';

export class SemanticSearchDto {
  @IsString()
  @IsNotEmpty()
  @MaxLength(2000)
  query: string;

  @IsOptional()
  @Type(() => Number)
  @IsInt()
  @Min(1)
  @Max(100)
  limit?: number;
}
```

对应源码：[`semantic-search.dto.ts` L1-L25](../src/conversations/dto/semantic-search.dto.ts#L1)。

当前 DTO 具备：

| 能力 | 当前 DTO 是否具备 |
| --- | --- |
| 编译时类型提示 | 是 |
| 自动拒绝空字符串 | 是 |
| 自动拒绝负数 `limit` | 是 |
| 自动拒绝额外字段 | 是 |
| 自动限制最大返回数量 | 是，最大值为 `100` |

[`src/main.ts` L8-L14](../src/main.ts#L8) 已注册全局校验：

```ts
import { ValidationPipe } from '@nestjs/common';

app.useGlobalPipes(
  new ValidationPipe({
    whitelist: true,
    forbidNonWhitelisted: true,
    transform: true,
  }),
);
```

配置含义：

| 选项 | 含义 |
| --- | --- |
| `whitelist: true` | 移除 DTO 未声明的字段 |
| `forbidNonWhitelisted: true` | 遇到额外字段时直接返回错误 |
| `transform: true` | 尝试转换输入类型 |

新增 `learning` 模块的 DTO 也采用相同规则。详见 [learning 模块代码导读：DTO 校验](./02-learning-module-code-guide.md#4-dto-校验)。

## 13. pgvector：为什么仍然需要原生 SQL

实体能够映射向量列：

```ts
@Column('vector', { length: 1024, nullable: true })
embedding: number[] | null;
```

对应源码：[`Message.embedding` L34-L35](../src/conversations/entities/message.entity.ts#L34)。



**但语义检索使用 pgvector 特有运算符：**

```sql
embedding <=> $1::vector
```

当前 Service 使用：

```ts
const rows: SemanticSearchResult[] = await this.em.query(
  `SELECT id, conversation_id, role, content, created_at,
          1 - (embedding <=> $1::vector) AS similarity
   FROM messages
   WHERE conversation_id = $2 AND embedding IS NOT NULL
   ORDER BY embedding <=> $1::vector
   LIMIT $3`,
  [JSON.stringify(vector), conversationId, limit],
);
```

对应源码：[`EntityManager.query()` L93-L101](../src/conversations/conversations.service.ts#L93)。

理解参数：

| 参数 | 值 |
| --- | --- |
| `$1` | 搜索文本生成的向量 |
| `$2` | 会话 ID |
| `$3` | 最大返回数量 |

`$1`、`$2`、`$3` 是参数化查询，不应改成字符串拼接。

### 13.1 搜索流程

```text
搜索文本
  ↓
OpenAIEmbeddings.embedQuery(searchText)
  ↓
1024 维查询向量
  ↓
PostgreSQL 计算 embedding <=> queryVector
  ↓
按余弦距离升序排列
  ↓
返回前 N 条
```

### 13.2 嵌入模型维度必须匹配

数据库列：

```text
vector(1024)
```

嵌入模型必须输出 `1024` 个数字。否则写入或查询会失败。

模型配置来自环境变量：

```ts
model: process.env.EMBEDDING_MODEL || 'text-embedding-v3'
```

对应源码：[`getEmbeddings()` L116-L122](../src/conversations/conversations.service.ts#L116)。



### 13.3 延迟创建 embeddings 客户端

当前 Service：

```ts
private embeddings: OpenAIEmbeddings | null = null;
```

对应源码：[`embeddings` 字段 L26](../src/conversations/conversations.service.ts#L26)。

只有第一次需要语义搜索时才创建客户端：

```ts
if (!this.embeddings) {
  this.embeddings = new OpenAIEmbeddings({ ... });
}
```

对应源码：[`getEmbeddings()` L109-L125](../src/conversations/conversations.service.ts#L109)。

这种方式避免普通关联查询依赖嵌入模型配置。



## 14. 数据库结构管理：初始化脚本、同步和迁移

当前学习环境同时出现三种数据库结构管理方式。

### 14.1 Docker 初始化脚本

旧工程使用：

```text
pgsql-test/init-scripts/create_tables.sql
```

它只在 PostgreSQL 数据目录首次初始化时自动执行。

### 14.2 synchronize: true

当前 NestJS 工程在本地默认使用：

```ts
synchronize: (process.env.DATABASE_SYNCHRONIZE ?? 'true') === 'true'
```

应用启动时，TypeORM 根据实体尝试同步结构。生产环境应显式设置：

```dotenv
DATABASE_SYNCHRONIZE=false
```

### 14.3 migration

真实项目应该使用迁移：

```text
数据库当前结构
  ↓
按顺序执行 migration
  ↓
数据库升级到目标结构
```

迁移的价值：

- 变更有记录。
- 可以审核。
- 可以在不同环境中重复执行。
- 可以明确管理复杂 SQL。
- 可以设计回滚方式。

## 15. 当前实体无法完整表达的数据库结构

旧工程初始化脚本包含：

```sql
role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system'))
```

对应旧工程源码：[`create_tables.sql` L26](../../../pgsql-test/init-scripts/create_tables.sql#L26)。

以及：

```sql
CREATE INDEX IF NOT EXISTS idx_messages_embedding
    ON messages USING hnsw (embedding vector_cosine_ops);
```

对应旧工程源码：[`create_tables.sql` L35-L37](../../../pgsql-test/init-scripts/create_tables.sql#L35)。

当前 Entity 虽然有 TypeScript 枚举：

```ts
enum: MessageRole
```

对应当前工程源码：[`Message.role` L25-L29](../src/conversations/entities/message.entity.ts#L25)。

但在 2026-06-01 核对运行中数据库时，没有看到对应 `CHECK` 约束，也没有看到 HNSW 索引。

需要理解：

- TypeScript 枚举不等于数据库约束。
- 实体映射向量列不等于已经创建向量索引。
- HNSW 是 PostgreSQL 扩展索引，应该通过明确的迁移 SQL 管理。
- 只依赖 `synchronize: true` 不足以管理真实项目结构。

检查实际结构：

```sql
SELECT
  tablename,
  indexname,
  indexdef
FROM pg_indexes
WHERE schemaname = 'public'
ORDER BY tablename, indexname;
```

```sql
SELECT
  conrelid::regclass AS table_name,
  conname,
  contype,
  pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE connamespace = 'public'::regnamespace
ORDER BY conrelid::regclass::text, conname;
```

HNSW 索引对应 SQL：

```sql
CREATE INDEX IF NOT EXISTS idx_messages_embedding
    ON messages USING hnsw (embedding vector_cosine_ops);
```

真实项目中，应将这类 SQL 写入 migration，而不是依赖开发人员手动执行。



## 16. 事务：多个写操作必须原子化

当前接口主要执行读取操作。未来实现“创建会话并写入第一条消息”时，应该使用事务。

错误场景：

```text
创建 conversations 成功
  ↓
创建 messages 失败
  ↓
数据库留下没有第一条消息的会话
```

使用事务：

```ts
await this.em.transaction(async (transactionalEm) => {
  const conversation = transactionalEm.create(Conversation, {
    userId,
    title,
  });
  await transactionalEm.save(conversation);

  const message = transactionalEm.create(Message, {
    conversationId: conversation.id,
    role: MessageRole.USER,
    content,
  });
  await transactionalEm.save(message);
});
```

必须注意：

> **事务回调中所有数据库操作都必须使用 `transactionalEm`，不要继续使用外部的 `this.em`。**

这样任意一步失败时，整个事务都会回滚。

## 17. 准备接口练习数据

在 2026-06-01 核对时，共享数据库中的三张表都是空表。调用会话接口前，需要先插入数据。

进入 PostgreSQL：

```powershell
docker exec -it pg_vector_db psql -U user -d hello_pg
```

插入演示数据：

```sql
INSERT INTO users (name)
VALUES ('TypeORM 学习用户')
RETURNING id;
```

记下返回的用户 ID。下面假设是 `1`：

```sql
INSERT INTO conversations (user_id, title)
VALUES (1, 'TypeORM 学习会话')
RETURNING id;
```

记下返回的会话 ID。下面假设是 `1`：

```sql
INSERT INTO messages (conversation_id, role, content)
VALUES
  (1, 'user', '什么是 TypeORM？'),
  (1, 'assistant', 'TypeORM 用于将 TypeScript 对象映射到数据库表。');
```



## 18. 调用接口

保持 NestJS 服务运行，在另一个 PowerShell 窗口执行。

### 18.1 查询用户会话

```powershell
Invoke-RestMethod `
  -Uri http://localhost:3005/conversations/users/1
```

### 18.2 查询会话消息

```powershell
Invoke-RestMethod `
  -Uri http://localhost:3005/conversations/1/messages
```

### 18.3 测试错误输入

```powershell
Invoke-RestMethod `
  -Uri http://localhost:3005/conversations/users/abc
```

应返回 HTTP `400`，因为 `ParseIntPipe` 无法将 `abc` 转换为整数。

查询不存在的用户：

```powershell
Invoke-RestMethod `
  -Uri http://localhost:3005/conversations/users/999999
```

应返回 HTTP `404`，因为 Service 抛出了 `NotFoundException`。

### 18.4 语义搜索

只有数据库中存在带 embedding 的消息，并且 `.env` 中的嵌入模型配置有效时，语义搜索才会返回结果：

```powershell
$body = @{
  query = '如何进行向量相似度搜索？'
  limit = 3
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:3005/conversations/1/search `
  -ContentType 'application/json' `
  -Body $body
```

只插入普通消息不会自动生成 embedding。当前 NestJS 工程只有搜索逻辑，没有“写入消息并生成 embedding”的 HTTP 接口。

可以使用旧 `pgsql-test` 工程中的 [`src/index.mjs` L66-L109](../../../pgsql-test/src/index.mjs#L66) 生成带向量的演示消息，或者继续扩展当前工程。

## 19. 当前工程已经实现了什么

教程 `conversations` 模块已经实现：

- NestJS 服务启动。
- PostgreSQL 连接。
- 三个 Entity。
- 用户到会话的一对多映射。
- 会话到消息的一对多映射。
- 查询用户的全部会话。
- 查询会话的全部消息。
- 基于 pgvector 的会话内语义搜索。
- `ParseIntPipe` 路径参数转换。
- `NotFoundException` 错误响应。

新增 `learning` 模块进一步实现：

- 数据库配置环境变量化。
- 全局 `ValidationPipe`。
- DTO 运行时校验。
- Repository CRUD。
- QueryBuilder 游标分页。
- 基于 `externalKey` 的 UPSERT。
- 基于 `version` 的乐观锁更新。
- 使用事务同时创建运行记录并更新任务状态。
- 使用 `QueryRunner` 和 `FOR UPDATE SKIP LOCKED` 领取任务。
- 学习表 migration。

新增代码与配套文档入口见 [docs 系统学习路线](./README.md)。

## 20. 当前工程尚未实现什么

教程原有的 `users`、`conversations`、`messages` 领域仍未实现：

- 用户、会话和消息的完整 HTTP CRUD。
- 写入消息时自动生成 embedding 的 HTTP 接口。
- HNSW 索引 migration。
- 角色数据库约束 migration。
- 业务接口测试。
- 独立测试数据库。
- 嵌入模型调用的 mock。

新增 `learning` 模块提供了部分工程化示例，但仍然不是完整生产系统。它没有实现多租户隔离、任务锁超时恢复、最大重试次数、专用测试数据库和生产凭据管理。详细边界见 [运行练习与生产化边界](./03-practice-and-production-checklist.md#12-生产项目仍然需要补充什么)。

## 21. 测试必须掌握的边界

当前 [`test/app.e2e-spec.ts` L19-L24](../test/app.e2e-spec.ts#L19) 只验证：

```text
GET /
```

返回：

```text
Hello World!
```

后续应增加：

| 测试 | 目标 |
| --- | --- |
| `GET /conversations/users/:userId` | 返回用户和按时间排序的会话 |
| 用户不存在 | 返回 `404` |
| `userId=abc` | 返回 `400` |
| `GET /conversations/:id/messages` | 返回消息但不返回 embedding |
| 语义检索 | mock 嵌入模型后验证排序和参数 |

真实项目应使用独立测试数据库，避免测试修改开发数据。

## 22. 推荐学习步骤

### 阶段 1：观察启动和 SQL 日志

1. 启动 PostgreSQL。
2. 启动 NestJS。
3. 调用 `/`。
4. 插入演示数据。
5. 调用两个关联查询接口。
6. 观察 `logging: true` 输出的 SQL。

完成标准：

- [ ] 我能解释 NestJS 如何连接 PostgreSQL。
- [ ] 我能从 TypeORM 日志中认出查询 SQL。

### 阶段 2：读懂三个 Entity

按顺序阅读：

1. [`user.entity.ts` L10-L22](../src/conversations/entities/user.entity.ts#L10)
2. [`conversation.entity.ts` L13-L32](../src/conversations/entities/conversation.entity.ts#L13)
3. [`message.entity.ts` L17-L44](../src/conversations/entities/message.entity.ts#L17)

完成标准：

- [ ] 我能解释 `@Entity`、`@Column`、`@PrimaryGeneratedColumn`。
- [ ] 我能解释 `@ManyToOne`、`@OneToMany`、`@JoinColumn`。
- [ ] 我知道哪一侧保存外键。
- [ ] 我能区分 `onDelete` 和 `cascade`。

### 阶段 3：读懂 Controller 和 Service

完成标准：

- [ ] 我能从 URL 找到对应 Controller 方法。
- [ ] 我知道 Controller 为什么不直接写数据库查询。
- [ ] 我能解释 `relations` 和 `order`。
- [ ] 我知道 `EntityManager` 的职责。

### 阶段 4：读懂 pgvector 搜索

完成标准：

- [ ] 我知道 TypeORM 如何映射 `vector(1024)`。
- [ ] 我知道为什么搜索仍然使用原生 SQL。
- [ ] 我能解释 `$1`、`$2`、`$3`。
- [ ] 我能解释 `<=>` 和 `1 - distance`。

### 阶段 5：补足工程化知识

完成标准：

- [ ] 我知道 DTO 类型不等于运行时校验。
- [ ] 我知道 `synchronize: true` 不应直接用于生产。
- [ ] 我知道迁移解决什么问题。
- [ ] 我知道多个写操作为什么需要事务。
- [ ] 我知道测试为什么需要独立数据库和 mock。

## 23. 建议的后续实践

先按照 [docs 系统学习路线](./README.md) 运行新增 `learning` 模块。完成后，再按以下顺序继续扩展教程原有领域：

1. 新增创建用户接口。
2. 新增创建会话接口。
3. 新增写入消息并生成 embedding 的接口。
4. 将 `DATABASE_SYNCHRONIZE` 设为 `false`。
5. 在 migration 中创建 HNSW 索引和数据库约束。
6. 增加业务接口 e2e 测试。
7. 使用独立测试数据库和嵌入模型 mock。

每完成一步，都使用 `psql` 查看数据库实际结构，并观察 TypeORM SQL 日志。

## 24. 官方参考资料

- [NestJS Controllers](https://docs.nestjs.com/controllers)
- [NestJS Providers](https://docs.nestjs.com/providers)
- [NestJS Modules](https://docs.nestjs.com/modules)
- [NestJS Database Techniques](https://docs.nestjs.com/techniques/database)
- [NestJS Validation](https://docs.nestjs.com/techniques/validation)
- [NestJS Configuration](https://docs.nestjs.com/techniques/configuration)
- [TypeORM Entities](https://typeorm.io/docs/entity/entities)
- [TypeORM Many-to-one / one-to-many relations](https://typeorm.io/docs/relations/many-to-one-one-to-many-relations/)
- [TypeORM Find Options](https://typeorm.io/docs/working-with-entity-manager/find-options/)
- [TypeORM EntityManager](https://typeorm.io/docs/working-with-entity-manager/working-with-entity-manager)
- [TypeORM Transactions](https://typeorm.io/docs/advanced-topics/transactions/)
- [TypeORM Migration Setup](https://typeorm.io/docs/migrations/setup)
- [TypeORM Indexes](https://dev.typeorm.io/docs/indexes/)
- [pgvector README](https://github.com/pgvector/pgvector)
