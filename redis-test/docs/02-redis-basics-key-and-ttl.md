# 02. Redis 基础、Key 设计与 TTL

这一章只学习 Redis 最基础但最重要的内容：key、value、String、计数器、TTL。很多新手会急着学 List、Set、Stream，但在真实项目中，Redis 出问题最多的地方往往是 key 命名混乱、TTL 设置错误、缓存数据永不过期、JSON 序列化不一致。

当前工程的 Docker 配置在 [docker-compose.yml](../docker-compose.yml#L1)。

## 1. 启动并连接 Redis

启动 Redis：

```powershell
docker compose up -d redis
```

进入 Redis CLI：

```powershell
docker exec -it agent_redis redis-cli
```

测试服务是否正常：

```redis
PING
```

预期输出：

```text
PONG
```

RedisInsight 可视化页面：

```text
http://localhost:5540
```

CLI 和 RedisInsight 都只是客户端。真正保存数据的是 Redis server，也就是 Docker 容器里的 Redis 进程。

## 2. Redis 的 keyspace

Redis 的所有数据都保存在 keyspace 里。你可以把 keyspace 粗略理解成一个巨大的字典：

```js
{
  "agent:memory:demo:messages": "...",
  "agent:rate_limit:user_001:minute": "3",
  "agent:task:1001": { "status": "running" }
}
```

**但 Redis 不是 JavaScript 对象。Redis key 是字符串，value 可以是 Redis 支持的数据结构。**

查看所有 key 不建议用 `KEYS *`，因为它会阻塞 Redis：

```redis
KEYS *
```

学习阶段可以用，但生产环境应该用 `SCAN`：

```redis
SCAN 0 MATCH agent:* COUNT 20
```

区别：

| 命令 | 特点 | 是否适合生产 |
| --- | --- | --- |
| `KEYS pattern` | 一次性扫描全部 key，可能阻塞 | 不适合 |
| `SCAN cursor MATCH pattern COUNT n` | 分批扫描 | 更适合 |

## 3. Key 命名设计

Redis 没有表结构，所以 key 命名就是你的“逻辑表结构”。命名随意会导致后期无法排查、无法批量清理、容易覆盖。

推荐格式：

```text
业务:模块:实体:id:字段
```

当前 Agent 记忆场景可以这样设计：

```text
agent:short_memory:demo_user_001:messages
agent:summary:demo_user_001
agent:tool_cache:weather:beijing
agent:rate_limit:demo_user_001:minute
agent:lock:session:demo_user_001
```

不要这样写：

```text
messages
cache
user1
tmp
```

这些 key 的问题是：

- 不知道属于哪个业务。
- 不知道保存什么数据。
- 容易被其他代码覆盖。
- 难以按前缀清理。

## 4. Key 设计中的实体边界

Redis key 经常需要包含业务 id。例如：

```text
agent:memory:{sessionId}:messages
```

这里的 `{sessionId}` 很重要。如果没有 session id，所有用户会共用同一份记忆。

错误设计：

```text
agent:memory:messages
```

后果：

```text
用户 A 的消息写入 Redis
用户 B 读取 Redis
用户 B 拿到了用户 A 的上下文
```

Agent 开发中这是严重问题，因为模型会把别人的上下文当成当前用户的上下文。

## 5. String 类型

String 是 Redis 最基础的数据类型。它可以保存：

- 普通文本。
- JSON 字符串。
- 数字字符串。
- 二进制数据。

基础命令：

```redis
SET learn:string "hello redis"
GET learn:string
DEL learn:string
```

`SET` 会覆盖旧值：

```redis
SET learn:string "first"
SET learn:string "second"
GET learn:string
```

输出：

```text
"second"
```

所以如果你的业务不能允许覆盖，就不能直接用普通 `SET`，而应该考虑 `SET NX`。

## 6. JSON 保存方式

Redis 不理解 JavaScript 对象。下面这个对象不能直接保存：

```js
const message = {
  role: "user",
  content: "hello",
};
```

你必须先序列化：

```js
await redis.set(
  "agent:memory:demo:latest",
  JSON.stringify(message),
  "EX",
  1800,
);
```

读取时再反序列化：

```js
const raw = await redis.get("agent:memory:demo:latest");
const message = raw ? JSON.parse(raw) : null;
```

这里有一个重要边界：Redis 只负责保存字符串，JSON 结构是否正确由你的应用负责。

当前工程的 `saveMessages` 就是这个思路：

- 先把 LangChain message 对象转换成普通对象。
- 再 `JSON.stringify`。
- 最后写入 Redis。

源码见 [saveMessages](../src/agent-with-redis-memory.mjs#L61)。

## 7. 计数器和原子递增

Redis String 可以保存数字，并使用 `INCR` 原子递增：

```redis
SET learn:counter 0
INCR learn:counter
INCR learn:counter
GET learn:counter
```

输出：

```text
"2"
```

`INCR` 的重点不是“加 1”，而是**原子性**。

如果你在 Node.js 里这样写：

```js
const raw = await redis.get(key);
const count = Number(raw ?? 0);
await redis.set(key, String(count + 1));
```

多个请求并发时可能会丢失更新：

```text
请求 A 读取 count = 1
请求 B 读取 count = 1
请求 A 写入 2
请求 B 写入 2
最终结果是 2，但实际上执行了两次加 1
```

使用 `INCR` 时，Redis 会在服务端完成加 1：

```js
const count = await redis.incr(key);
```

这就是限流、访问统计、任务编号常用 `INCR` 的原因。

## 8. TTL 是什么

TTL 是 Time To Live，表示 key 还能存活多久。

设置 60 秒过期：

```redis
SET learn:ttl "temporary value" EX 60
```

查看剩余时间：

```redis
TTL learn:ttl
```

删除过期时间，让 key 永久存在：

```redis
PERSIST learn:ttl
```

手动设置过期时间：

```redis
EXPIRE learn:ttl 300
```

毫秒级过期：

```redis
SET learn:ttl-ms "value" PX 5000
PTTL learn:ttl-ms
```

## 9. TTL 返回值

`TTL key` 的返回值有三种常见情况：

| 返回值 | 含义 |
| --- | --- |
| 正整数 | key 还剩多少秒过期 |
| `-1` | key 存在，但没有过期时间 |
| `-2` | key 不存在 |

练习：

```redis
DEL learn:ttl-demo
TTL learn:ttl-demo

SET learn:ttl-demo "hello"
TTL learn:ttl-demo

EXPIRE learn:ttl-demo 60
TTL learn:ttl-demo
```

你应该分别看到：

```text
-2
-1
60 左右的正整数
```

## 10. SET 对 TTL 的影响

这是 Redis 新手很容易踩坑的地方：普通 `SET` 会清除原来的 TTL。

示例：

```redis
SET learn:ttl-reset "v1" EX 60
TTL learn:ttl-reset

SET learn:ttl-reset "v2"
TTL learn:ttl-reset
```

第二次 `TTL` 会返回 `-1`，因为普通 `SET` 把过期时间清掉了。

如果希望更新值时继续保留 TTL，可以使用：

```redis
SET learn:ttl-reset "v3" KEEPTTL
```

如果希望每次写入都重新设置 TTL，要显式带上 `EX`：

```redis
SET learn:ttl-reset "v4" EX 60
```

当前工程的 `saveMessages` 每次保存会重新设置 TTL：

```js
await this.redis.set(this.messagesKey(sessionId), payload, "EX", this.ttlSeconds);
```

这意味着用户每次继续对话，短期记忆的过期时间都会刷新。

## 11. SET NX EX：创建锁和防覆盖

`SET` 可以带条件：

```redis
SET learn:lock worker-1 NX EX 30
```

含义：

- `NX`：只有 key 不存在时才设置。
- `EX 30`：设置后 30 秒过期。

如果设置成功，返回：

```text
OK
```

如果 key 已存在，返回：

```text
(nil)
```

这个命令常用于简单分布式锁：

```js
const result = await redis.set("agent:lock:session:demo", "worker-1", "NX", "EX", 30);
if (result !== "OK") {
  throw new Error("Session is already running");
}
```

但是释放锁不能直接 `DEL key`，因为锁可能已经过期并被别人重新获取。生产中通常用 Lua 判断 value 是否是自己写入的，再删除。这个进阶点在 [06. Redis 进阶机制与生产实践](./06-redis-production-and-debugging.md) 里讲。

## 12. Agent 中哪些 key 必须有 TTL

Agent 项目里，以下数据通常必须设置 TTL：

| 数据 | 为什么要 TTL | 示例 |
| --- | --- | --- |
| 短期记忆 | 用户不再对话后自动释放内存 | `agent:memory:{sessionId}:messages` |
| 工具缓存 | 外部数据会过期 | `agent:tool_cache:weather:{city}` |
| 限流计数 | 只统计一个时间窗口 | `agent:rate_limit:{userId}:minute` |
| 临时锁 | 防止进程崩溃后永久锁死 | `agent:lock:session:{sessionId}` |
| 临时任务状态 | 任务结束后不需要永久保存 | `agent:task_runtime:{taskId}` |

不一定要 TTL 的数据：

- Redis 作为队列时未消费的任务。
- 系统配置缓存，但仍建议设计刷新机制。
- 明确需要长期存在的热数据副本。

**如果你不确定一个 Redis key 是否要 TTL，优先问：**

```text
如果这个 key 永久留在 Redis，会不会越来越多？
如果它过期了，业务能不能重新生成？
```

**能重新生成的数据，通常适合 TTL。**

## 13. 基础练习

进入 Redis CLI 后，按顺序执行：

```redis
SET learn:user:1:name "Alice"
GET learn:user:1:name

SET learn:agent:session:001 "hello" EX 120
TTL learn:agent:session:001

INCR learn:agent:user:001:message_count
INCR learn:agent:user:001:message_count
GET learn:agent:user:001:message_count

SET learn:agent:lock:session:001 worker-1 NX EX 30
SET learn:agent:lock:session:001 worker-2 NX EX 30

SCAN 0 MATCH learn:* COUNT 20
```

练习目标：

- 能解释每个 key 的业务含义。
- 能解释为什么锁要用 `NX EX`。
- 能解释为什么计数器用 `INCR` 而不是 `GET` 后手动加 1。
- 能解释 `TTL` 返回 `-1` 和 `-2` 的区别。

## 14. 本章完成标准

学完本章，你应该能回答：

1. Redis key 为什么要带业务前缀？
2. 为什么 Agent 的会话记忆 key 必须包含 session id？
3. `SET key value` 为什么可能意外清除 TTL？
4. `INCR` 为什么适合做限流计数器？
5. `SET NX EX` 为什么可以作为简单锁的基础？
6. 什么数据应该设置 TTL，什么数据不应该只放 Redis？
