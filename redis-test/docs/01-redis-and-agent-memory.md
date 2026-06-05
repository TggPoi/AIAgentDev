# 01. Redis 必须掌握的知识地图

如果你没有学过 Redis，不要一开始就背几十个命令。Redis 最重要的是理解它的模型：**Redis 是一个运行在内存中的数据结构服务器**。你通过 TCP 连接给它发送命令，它在内存里找到某个 key，对这个 key 关联的数据结构执行操作，然后返回结果。

这句话里面有四个关键词：

- **内存**：Redis 的主要读写发生在内存中，所以速度很快；但也意味着要关注内存占用、过期策略和持久化。
- **数据结构**：Redis 不只是 `GET/SET`，它有 String、Hash、List、Set、Sorted Set、Stream 等结构。
- **服务器**：Redis 是独立服务，不是 Node.js 进程里的变量。多个进程、多个 Agent 实例可以共享它。
- **命令**：Redis 的每个操作都是命令，例如 `SET`、`GET`、`HSET`、`LPUSH`、`ZADD`。

## 1. Redis 的基本工作流程

以这条命令为例：

```redis
SET agent:session:demo:messages "[{\"role\":\"user\",\"content\":\"hello\"}]" EX 1800
```

Redis 做的事情可以理解为：

1. 客户端通过网络把命令发送给 Redis。
2. Redis 解析命令：要操作 key `agent:session:demo:messages`。
3. Redis 在内存 keyspace 中写入 value。
4. `EX 1800` 表示这个 key 1800 秒后过期。
5. Redis 返回 `OK`。

这里的 value 看起来是 JSON，但对 Redis 来说它只是字符串。JSON 的解析和对象恢复是你的应用代码负责的，这也是当前工程里 `JSON.stringify`、`JSON.parse` 和 LangChain message 转换函数存在的原因。

## 2. 为什么 Redis 快

Redis 快不是因为它“神奇”，而是因为它做了很多工程取舍：

- 大多数数据在内存中，避免了频繁磁盘随机 IO。
- 单条命令执行时是原子的，减少锁竞争。
- 使用事件循环处理大量连接，避免一个连接一个线程的沉重模型。
- 数据结构为常见场景做了专门优化，例如 List、Hash、Sorted Set。
- 协议简单，命令执行路径短。

但是快也有代价：

- 内存比磁盘贵，不能无限保存所有数据。
- Redis 不适合复杂关系查询，比如多表 JOIN。
- Redis 的持久化不是传统关系数据库事务日志的完整替代。
- Redis key 设计不好时，后期很难维护。

所以 Redis 的正确定位通常是：**缓存、短期状态、实时计数、队列、锁、排行榜、会话、Agent 短期记忆**。

## 3. Redis 和 PostgreSQL 的边界

你之前已经学习过 PostgreSQL。学习 Redis 时必须建立一个边界意识：Redis 和 PostgreSQL 不是谁替代谁。

| 问题 | 更适合 Redis | 更适合 PostgreSQL |
| --- | --- | --- |
| 保存用户账号、订单、审计记录 | 否 | 是 |
| 保存 30 分钟会话上下文 | 是 | 也可以，但 Redis 更轻 |
| 快速缓存工具调用结果 | 是 | 通常不需要 |
| 查询用户和订单的复杂关系 | 否 | 是 |
| 排行榜、优先级队列 | 是 | 可以，但不如 Redis 直接 |
| 需要严格事务和长期一致性 | 通常否 | 是 |
| Agent 运行中的临时状态 | 是 | 可用于最终落库 |

在 Agent 项目里，一个常见组合是：

```text
PostgreSQL:
  保存长期数据、用户、会话记录、向量、审计日志

Redis:
  保存短期记忆、缓存、限流计数器、运行状态、临时锁、任务队列
```

不要把 Agent 所有数据都塞进 Redis。Redis 中的很多数据应该有 TTL，过期后业务仍然能继续运行。

## 4. Redis 必须掌握的基础知识

### 4.1 Key-value 模型

Redis 里所有数据都从 key 开始。

```redis
GET user:1:name
HGETALL agent:task:1001
LRANGE agent:session:demo:messages 0 -1
```

你不是先选表，再查行，而是直接通过 key 找 value。Redis 没有 SQL 的 `WHERE`、`JOIN`、`GROUP BY`。如果你需要这些能力，通常应该用 PostgreSQL。

### 4.2 Key 命名

Redis key 应该表达业务边界：

```text
业务:模块:实体:id:字段
```

示例：

```text
agent:memory:demo_user_001:messages
agent:tool_cache:weather:beijing
agent:rate_limit:user_001:minute
agent:lock:session:demo_user_001
```

好的 key 命名能解决三个问题：

- 看到 key 就知道它属于哪个业务。
- 可以用 `SCAN` 按前缀排查问题。
- 不同业务不会互相覆盖 key。

### 4.3 数据结构选择

Redis 的 value 不是只有字符串。你必须掌握这些结构：

| 数据结构 | 适合保存什么 | Agent 场景 |
| --- | --- | --- |
| String | 单个值、JSON、计数器 | 会话 JSON、工具缓存、限流计数 |
| Hash | 一个对象的多个字段 | Agent run 状态、任务元数据 |
| List | 有顺序的列表 | 最近 N 条消息、简单队列 |
| Set | 不重复集合 | 去重、活跃 session、权限标签 |
| Sorted Set | 带分数的有序集合 | 优先级队列、排行榜、延迟任务 |
| Bitmap | 大量布尔状态 | 用户签到、是否访问过 |
| HyperLogLog | 近似去重计数 | 大规模 UV 统计 |
| Geo | 地理位置 | 附近位置查询 |
| Stream | 追加日志和消费组 | Agent 异步任务流、事件日志 |

### 4.4 TTL

TTL 是 Redis 学习的核心。很多 Redis 数据都不应该永久存在。

```redis
SET agent:memory:demo:messages "..." EX 1800
TTL agent:memory:demo:messages
```

Agent 短期记忆非常适合 TTL：用户半小时不对话，短期上下文可以自动清理。真正需要长期保存的内容应该写入 PostgreSQL 或文件系统。

### 4.5 原子命令

Redis 单条命令是原子的。例如：

```redis
INCR agent:rate_limit:user_001:minute
SET agent:lock:session:001 worker-1 NX EX 30
```

这意味着多个请求同时执行 `INCR`，Redis 会一个一个处理，不会把计数加丢。Agent 限流、锁、计数器都依赖这个特性。

## 5. Redis 必须掌握的进阶知识

你不需要第一天就完全掌握进阶知识，但必须知道它们解决什么问题。

### 5.1 Pipeline

Pipeline 用于减少网络往返。比如一次读取 100 个 key，如果逐个 `await redis.get(key)`，会产生 100 次网络等待；Pipeline 可以批量发送命令。

适合场景：

- 批量读取多个缓存。
- 批量写入多个状态。
- 初始化测试数据。

### 5.2 Transaction

Redis 的 `MULTI/EXEC` 可以把多条命令放在一个事务块里执行。它保证命令按顺序执行，但和 PostgreSQL 的事务不是一回事：**Redis 不提供复杂回滚机制**。

适合场景：

- 同时更新多个相关 key。
- 需要避免命令被其他客户端插队。

### 5.3 Lua 脚本

Lua 可以把多步逻辑放到 Redis 服务端一次执行，常用于更复杂的原子操作。

适合场景：

- 释放锁时必须判断锁是不是自己持有的。
- 限流逻辑需要“读、判断、写”保持原子。

### 5.4 Pub/Sub 和 Stream

Pub/Sub 是实时广播，消息不会长期保存；Stream 是可持久化的追加日志，支持消费组。

Agent 场景中：

- 临时通知可以用 Pub/Sub。
- 可靠任务流、事件日志更适合 Stream。

### 5.5 持久化和内存淘汰

Redis 虽然是内存数据库，但可以通过 RDB/AOF 持久化到磁盘。你还必须理解 Redis 内存满了以后怎么处理 key，例如 `allkeys-lru`、`volatile-ttl` 等淘汰策略。

这决定了 Redis 适不适合保存某类数据。

## 6. Agent 开发必须掌握的 Redis 能力

Agent 开发中，Redis 最常见的用途不是“保存最终数据”，而是保存运行时状态。

### 6.1 短期记忆

当前工程的核心就是短期记忆：

```text
用户输入
  -> 从 Redis 读取历史 messages
  -> 拼接本轮 HumanMessage
  -> 调用 agent.invoke
  -> 把 result.messages 写回 Redis
  -> 设置 TTL
```

源码入口：

- [RedisMessageStore](../src/agent-with-redis-memory.mjs#L44)
- [loadMessages](../src/agent-with-redis-memory.mjs#L55)
- [saveMessages](../src/agent-with-redis-memory.mjs#L61)

### 6.2 工具结果缓存

Agent 经常调用搜索、天气、数据库查询、HTTP API。很多结果短时间内可以复用。

```text
agent:tool_cache:weather:beijing
agent:tool_cache:web_search:hash_of_query
```

缓存必须设置 TTL，否则旧结果会误导 Agent。

### 6.3 限流

Agent 调用模型和工具都有成本。Redis 可以用 `INCR + EXPIRE` 做分钟级限流。

```redis
INCR agent:rate_limit:user_001:minute
EXPIRE agent:rate_limit:user_001:minute 60
```

### 6.4 锁

如果同一个 session 同时触发两个 Agent run，可能互相覆盖记忆。可以用 Redis 锁保护：

```redis
SET agent:lock:session:demo_user_001 worker-1 NX EX 30
```

### 6.5 队列和事件

Agent 可能有耗时任务，例如网页抓取、文档解析、向量化。Redis List、Sorted Set、Stream 都可以用于任务分发，但可靠性要求越高，越应该考虑 Stream 或专门队列系统。

## 7. 学习路线总结

如果你要系统掌握 Redis，建议按这个顺序学习：

1. 理解 Redis 是内存数据结构服务器。
2. 学会 key 命名和 TTL。
3. 掌握 String、Hash、List、Set、Sorted Set。
4. 学会在 Node.js 中用 `ioredis` 连接 Redis。
5. 学会 JSON 序列化和 LangChain message 转换。
6. 学会 Pipeline、Transaction、Lua 的使用边界。
7. 学会 Redis 在 Agent 里的短期记忆、缓存、限流、锁、队列。
8. 学会排查 Redis 内存、慢命令、连接、过期策略问题。

下一章开始从最基础的 key、value、TTL 讲起。
