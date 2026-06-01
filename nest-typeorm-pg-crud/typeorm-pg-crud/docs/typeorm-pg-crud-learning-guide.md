# TypeORM + NestJS + PostgreSQL 工程学习指南

本文档用于学习教程后半部分实现的 `typeorm-pg-crud` 工程。

实际工程路径：

```text
D:\AI_Agent_Project\nest-typeorm-pg-crud\typeorm-pg-crud
```

这不是一份 TypeORM API 百科。它会围绕当前工程解释必须掌握的知识，并补充从学习示例走向真实项目时不能忽略的内容。

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
| 配置 PostgreSQL 连接 | [`TypeOrmModule.forRoot()` L12-L22](../src/app.module.ts#L12) |
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
  TypeOrmModule.forRoot({ ... }),
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

## 6. TypeOrmModule.forRoot：连接 PostgreSQL

[`src/app.module.ts` L12-L22](../src/app.module.ts#L12) 注册 TypeORM：

```ts
TypeOrmModule.forRoot({
  type: 'postgres',
  host: 'localhost',
  port: 5432,
  username: 'user',
  password: '123456',
  database: 'hello_pg',
  synchronize: true,
  logging: true,
  entities: [User, Conversation, Message],
})
```

逐项理解：

| 配置 | 当前值 | 含义 |
| --- | --- | --- |
| `type` | `'postgres'` | 使用 PostgreSQL 驱动 |
| `host` | `'localhost'` | NestJS 在 Windows 主机运行，通过映射端口连接数据库 |
| `port` | `5432` | PostgreSQL 端口 |
| `username` | `'user'` | 数据库用户 |
| `password` | `'123456'` | 数据库密码 |
| `database` | `'hello_pg'` | 连接的数据库 |
| `entities` | 三个实体类 | 告诉 TypeORM 需要管理哪些表 |
| `logging` | `true` | 在终端输出 TypeORM 执行的 SQL |
| `synchronize` | `true` | 启动时根据实体尝试同步表结构 |

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

当前写法便于学习：

```ts
password: '123456'
```

真实项目应使用环境变量和配置模块，例如：

```dotenv
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_USER=user
DATABASE_PASSWORD=123456
DATABASE_NAME=hello_pg
```

再通过 NestJS 的 `@nestjs/config` 和 `TypeOrmModule.forRootAsync()` 读取配置。

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

## 8. 一对多关系：拥有方和反向关系

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

### 8.1 onDelete: 'CASCADE' 与 cascade: true 不同

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

当前 DTO：

```ts
export class SemanticSearchDto {
  query: string;
  limit?: number;
}
```

对应源码：[`semantic-search.dto.ts` L2-L6](../src/conversations/dto/semantic-search.dto.ts#L2)。

它为 TypeScript 提供类型提示，但不会自动验证运行时 HTTP 输入。

需要区分：

| 能力 | 当前 DTO 是否具备 |
| --- | --- |
| 编译时类型提示 | 是 |
| 自动拒绝空字符串 | 否 |
| 自动拒绝负数 `limit` | 否 |
| 自动拒绝额外字段 | 否 |
| 自动限制最大返回数量 | 否 |

真实项目应该安装：

```powershell
pnpm.cmd install class-validator class-transformer
```

并改造 DTO：

```ts
import { IsInt, IsNotEmpty, IsOptional, IsString, Max, Min } from 'class-validator';

export class SemanticSearchDto {
  @IsString()
  @IsNotEmpty()
  query: string;

  @IsOptional()
  @IsInt()
  @Min(1)
  @Max(50)
  limit?: number;
}
```

在 [`src/main.ts` L4-L8](../src/main.ts#L4) 注册全局校验：

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

当前工程尚未安装这两个校验依赖，也尚未注册 `ValidationPipe`。这是学习示例走向真实接口时必须补足的内容。

## 13. pgvector：为什么仍然需要原生 SQL

实体能够映射向量列：

```ts
@Column('vector', { length: 1024, nullable: true })
embedding: number[] | null;
```

对应源码：[`Message.embedding` L34-L35](../src/conversations/entities/message.entity.ts#L34)。

但语义检索使用 pgvector 特有运算符：

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

当前 NestJS 工程使用：

```ts
synchronize: true
```

应用启动时，TypeORM 根据实体尝试同步结构。

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

> 事务回调中所有数据库操作都必须使用 `transactionalEm`，不要继续使用外部的 `this.em`。

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

已经实现：

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

## 20. 当前工程尚未实现什么

尚未实现：

- 用户、会话和消息的完整 HTTP CRUD。
- 写入消息时自动生成 embedding 的 HTTP 接口。
- 请求体运行时校验。
- 数据库配置环境变量化。
- 正式 migration。
- HNSW 索引 migration。
- 角色数据库约束 migration。
- 业务接口测试。
- 独立测试数据库。
- 嵌入模型调用的 mock。

这并不代表教程实现错误。教程聚焦的是 TypeORM 关系映射和 pgvector 检索。你需要知道学习示例与生产代码之间还有哪些工作。

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

按以下顺序扩展当前工程：

1. 为 `SemanticSearchDto` 添加运行时校验。
2. 使用环境变量替换数据库硬编码配置。
3. 新增创建用户接口。
4. 新增创建会话接口。
5. 新增写入消息并生成 embedding 的接口。
6. 将 `synchronize` 改为 `false`，建立 migration。
7. 在 migration 中创建 HNSW 索引和数据库约束。
8. 增加业务接口 e2e 测试。

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
