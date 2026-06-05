# 04. Node.js 使用 ioredis

这一章学习如何在 Node.js 中操作 Redis。重点不是“怎么写 `redis.get`”，而是理解连接生命周期、异步调用、JSON 序列化、批量命令、事务、错误处理，以及为什么 LangChain message 不能直接裸存进 Redis。

当前工程使用的 Redis 客户端是 `ioredis`，依赖见 [package.json](../package.json#L1)。

## 1. 创建连接

最小连接代码：

```js
import Redis from "ioredis";

const redis = new Redis({
  host: process.env.REDIS_HOST ?? "localhost",
  port: Number(process.env.REDIS_PORT ?? 6379),
  db: Number(process.env.REDIS_DB ?? 0),
});
```

这段代码做了几件事：

- 创建一个 Redis 客户端对象。
- 连接 `localhost:6379`。
- 选择 Redis DB，默认是 `0`。
- 后续命令都会通过这个客户端发送给 Redis server。

当前工程的 Agent 示例也是这样连接的，见 [Redis client](../src/agent-with-redis-memory.mjs#L91)。

## 2. 连接对象不是数据本身

`redis` 变量不是 Redis 数据库，它只是客户端连接对象。

```js
await redis.set("learn:key", "value");
```

这行代码的真实过程是：

```text
Node.js 进程
  -> ioredis 把 SET 命令编码后通过 TCP 发给 Redis
  -> Redis server 执行命令
  -> Redis 返回结果
  -> ioredis 把结果解析成 JS 值
```

所以你必须 `await` Redis 命令，否则拿到的是 Promise。

错误写法：

```js
const value = redis.get("learn:key");
console.log(value); // Promise
```

正确写法：

```js
const value = await redis.get("learn:key");
console.log(value);
```

## 3. 监听连接事件

Redis 是网络服务，连接可能失败、断开、重连。学习阶段至少要监听 `connect` 和 `error`：

```js
redis.on("connect", () => {
  console.log("Redis connected");
});

redis.on("error", (error) => {
  console.error("Redis error:", error.message);
});
```

常见错误：

| 错误 | 可能原因 |
| --- | --- |
| `ECONNREFUSED` | Redis 没启动，端口不对 |
| `ENOTFOUND` | host 写错 |
| `NOAUTH Authentication required` | Redis 设置了密码但客户端没配置 |
| 命令一直卡住 | 网络、重连、Docker 容器异常 |

## 4. 基础读写

```js
await redis.set("learn:string", "hello redis", "EX", 60);
const value = await redis.get("learn:string");
const ttl = await redis.ttl("learn:string");

console.log(value);
console.log(ttl);
```

注意 `EX` 是 Redis 命令参数，不是 JavaScript 配置对象。`ioredis` 会把参数原样拼成 Redis 命令。

下面两种写法含义不同：

```js
await redis.set("k", "v");
await redis.expire("k", 60);
```

和：

```js
await redis.set("k", "v", "EX", 60);
```

第一种是两条命令，中间可能发生进程崩溃，导致 key 被写入但没有 TTL。第二种是一条命令，更适合写入必须带 TTL 的缓存和短期记忆。

## 5. 保存 JSON

Redis 保存的是字符串。如果你要保存对象，需要 `JSON.stringify`。

```js
const task = {
  status: "running",
  step: "search_docs",
  retryCount: 0,
};

await redis.set("agent:task:1001", JSON.stringify(task), "EX", 300);
```

读取：

```js
const raw = await redis.get("agent:task:1001");
const task = raw ? JSON.parse(raw) : null;
```

### 5.1 JSON 的常见错误

错误 1：忘记 `JSON.stringify`

```js
await redis.set("agent:task:1001", task);
```

这通常会得到不符合预期的字符串，比如 `[object Object]`。

错误 2：忘记 `JSON.parse`

```js
const task = await redis.get("agent:task:1001");
console.log(task.status); // undefined
```

`redis.get` 返回的是字符串，不是对象。

错误 3：没有处理 null

```js
const raw = await redis.get("missing:key");
const obj = JSON.parse(raw); // raw 是 null，会报错
```

正确写法：

```js
const raw = await redis.get("missing:key");
const obj = raw ? JSON.parse(raw) : null;
```

## 6. LangChain message 为什么需要转换

当前工程的 `loadMessages` 和 `saveMessages` 用到了两个函数：

- `mapChatMessagesToStoredMessages`
- `mapStoredMessagesToChatMessages`

源码位置：

- [loadMessages](../src/agent-with-redis-memory.mjs#L55)
- [saveMessages](../src/agent-with-redis-memory.mjs#L61)

它们不是 Redis 函数，而是 LangChain 的消息格式转换工具。

### 6.1 BaseMessage 是对象实例

LangChain 的消息通常是类实例：

```js
new HumanMessage("hello")
new AIMessage("hi")
new SystemMessage("You are helpful")
```

这些对象除了 `content`，还有类型、元数据、方法和内部结构。直接把类实例丢给 `JSON.stringify` 并不可靠，因为你真正需要保存的是“可恢复的消息数据”。

### 6.2 mapChatMessagesToStoredMessages

这个函数把 LangChain 消息对象转换成普通对象：

```js
const messages = [
  new HumanMessage("What is Redis TTL?"),
  new AIMessage("TTL is the remaining lifetime of a key."),
];

const stored = mapChatMessagesToStoredMessages(messages);
```

输出结构类似：

```json
[
  {
    "type": "human",
    "data": {
      "content": "What is Redis TTL?",
      "additional_kwargs": {},
      "response_metadata": {}
    }
  },
  {
    "type": "ai",
    "data": {
      "content": "TTL is the remaining lifetime of a key.",
      "tool_calls": [],
      "invalid_tool_calls": [],
      "additional_kwargs": {},
      "response_metadata": {}
    }
  }
]
```

这种普通对象可以安全地 `JSON.stringify` 后写入 Redis。

### 6.3 mapStoredMessagesToChatMessages

这个函数做反向转换：

```js
const stored = JSON.parse(rawFromRedis);
const messages = mapStoredMessagesToChatMessages(stored);
```

输出重新变成：

```js
[
  HumanMessage,
  AIMessage,
]
```

这样 `agent.invoke({ messages })` 才能继续使用这些历史消息。



在当前代码里，这两个函数的作用是：**把 LangChain 的消息对象转换成 Redis 能保存的 JSON 普通对象；再从 JSON 普通对象恢复成 LangChain 的消息对象**。

对应位置在 [src/agent-with-redis-memory.mjs](D:/AI_Agent_Project/redis-test/src/agent-with-redis-memory.mjs:55)。

**整体流程**

```js
// 读取 Redis
raw JSON string
  -> JSON.parse(raw)
  -> StoredMessage[]
  -> mapStoredMessagesToChatMessages(...)
  -> BaseMessage[]

// 写入 Redis
BaseMessage[]
  -> mapChatMessagesToStoredMessages(...)
  -> StoredMessage[]
  -> JSON.stringify(...)
  -> Redis SET
```

`mapChatMessagesToStoredMessages(messages)` 用在 `saveMessages` 里。

它接收的是 LangChain 的消息对象数组，例如：

```js
[
  new SystemMessage("You are a Redis tutor."),
  new HumanMessage("What is Redis TTL?"),
  new AIMessage("TTL is the remaining lifetime of a key.")
]
```

输出的是普通 JS 对象数组，可以安全 `JSON.stringify` 后存入 Redis：

```json
[
  {
    "type": "system",
    "data": {
      "content": "You are a Redis tutor.",
      "additional_kwargs": {},
      "response_metadata": {}
    }
  },
  {
    "type": "human",
    "data": {
      "content": "What is Redis TTL?",
      "additional_kwargs": {},
      "response_metadata": {}
    }
  },
  {
    "type": "ai",
    "data": {
      "content": "TTL is the remaining lifetime of a key.",
      "tool_calls": [],
      "invalid_tool_calls": [],
      "additional_kwargs": {},
      "response_metadata": {}
    }
  }
]
```

关键点：`HumanMessage`、`AIMessage`、`SystemMessage` 是类实例，里面有方法和原型信息，不能直接长期依赖 `JSON.stringify` 保存。**`mapChatMessagesToStoredMessages` 会调用每条消息的 `toDict()`，把它们变成适合存储的 `StoredMessage` 普通对象。**

`mapStoredMessagesToChatMessages(messages)` 用在 `loadMessages` 里。

它接收刚才那种 `StoredMessage[]` 普通对象：

```js
[
  {
    type: "human",
    data: {
      content: "What is Redis TTL?",
      additional_kwargs: {},
      response_metadata: {}
    }
  }
]
```

输出重新恢复成 LangChain 消息对象：

```js
[
  HumanMessage {
    content: "What is Redis TTL?",
    // 还有 LangChain 消息对象自己的方法和内部字段
  }
]
```

所以在你的代码里：

```js
async loadMessages(sessionId) {
  const raw = await this.redis.get(this.messagesKey(sessionId));
  if (!raw) return [];
  return mapStoredMessagesToChatMessages(JSON.parse(raw));
}
```

这一步不是简单读取字符串，而是：

1. 从 Redis 读出 JSON 字符串；
2. `JSON.parse` 变成普通对象；
3. `mapStoredMessagesToChatMessages` 恢复成 `HumanMessage`、`AIMessage`、`SystemMessage` 等 LangChain 可直接使用的消息对象。

而：

```js
async saveMessages(sessionId, messages) {
  const payload = JSON.stringify(mapChatMessagesToStoredMessages(messages));
  await this.redis.set(this.messagesKey(sessionId), payload, "EX", this.ttlSeconds);
}
```

这一步是：

1. 拿到 agent 执行后的 `result.messages`；
2. 把 LangChain 消息对象转成可存储对象；
3. `JSON.stringify` 后存进 Redis；
4. 顺便设置 TTL 过期时间。

一句话理解：

`mapChatMessagesToStoredMessages` 是“对象消息 -> 可存储 JSON 数据”。

`mapStoredMessagesToChatMessages` 是“可存储 JSON 数据 -> 对象消息”。



## 7. Pipeline

如果要连续执行很多 Redis 命令，逐条 `await` 会产生多次网络往返。

低效写法：

```js
for (const key of keys) {
  await redis.get(key);
}
```

Pipeline 写法：

```js
const pipeline = redis.pipeline();

for (const key of keys) {
  pipeline.get(key);
}

const results = await pipeline.exec();
```

`results` 的结构是：

```js
[
  [null, "value1"],
  [null, "value2"],
]
```

每个元素是 `[error, result]`。

Pipeline 的重点：

- 减少网络往返。
- 不保证事务语义。
- 适合批量读写。

## 8. Transaction

Redis 事务使用 `MULTI/EXEC`。在 `ioredis` 中：

```js
const results = await redis
  .multi()
  .set("learn:tx:a", "1")
  .incr("learn:tx:counter")
  .expire("learn:tx:counter", 60)
  .exec();
```

事务里的命令会排队，`exec` 时一起执行。

注意：Redis 事务和 PostgreSQL 事务不一样。

| 对比项 | Redis Transaction | PostgreSQL Transaction |
| --- | --- | --- |
| 多命令顺序执行 | 是 | 是 |
| 复杂回滚 | 否 | 是 |
| SQL 隔离级别 | 无 | 有 |
| 适合场景 | 简单原子批处理 | 复杂业务一致性 |

如果你需要“读取后判断再写入”且必须原子，通常要结合 `WATCH` 或 Lua。

## 9. 关闭连接

脚本结束时应该关闭 Redis 连接：

```js
await redis.quit();
```

区别：

| 方法 | 含义 |
| --- | --- |
| `quit()` | 发送 `QUIT`，等待 Redis 正常关闭连接 |
| `disconnect()` | 直接断开客户端连接 |

普通脚本优先用 `quit()`。如果是进程异常退出或需要立即断开，可以用 `disconnect()`。

## 10. 可运行代码案例

配套示例在 [src/redis-learning-examples.mjs](../src/redis-learning-examples.mjs#L1)。

运行：

```powershell
pnpm run redis:examples
```

它会演示：

- String + TTL。
- Hash 保存任务状态。
- List 保存最近消息。
- Set 去重。
- Sorted Set 优先级队列。
- Pipeline 批量读取。
- Transaction 批量更新。
- Stream 追加事件。
- 简单锁。

## 11. 本章完成标准

学完本章，你应该能做到：

1. 能解释 `redis` 客户端对象和 Redis server 的关系。
2. 能正确使用 `await redis.get(...)`。
3. 能用 `JSON.stringify` 和 `JSON.parse` 保存对象。
4. 能解释 LangChain message 为什么要转换成 StoredMessage。
5. 能写出 Pipeline 批量读写。
6. 能说明 Redis Transaction 和 PostgreSQL Transaction 的区别。
7. 能在脚本结束时正确关闭 Redis 连接。





# 函数讲解：

## setTtlForDemoKeys函数：

`setTtlForDemoKeys` 在 [src/redis-learning-examples.mjs](D:/AI_Agent_Project/redis-test/src/redis-learning-examples.mjs:58)：

```js
async function setTtlForDemoKeys(...selectedKeys) {
  const pipeline = redis.pipeline();

  for (const key of selectedKeys) {
    pipeline.expire(key, ttlSeconds);
  }

  await pipeline.exec();
}
```

它的作用是：**给传进来的多个 Redis key 批量设置 TTL 过期时间**。

比如调用位置在 [src/redis-learning-examples.mjs](D:/AI_Agent_Project/redis-test/src/redis-learning-examples.mjs:256)：

```js
await setTtlForDemoKeys(keys.pipelineA, keys.pipelineB);
```

等价于给这两个 key 执行：

```redis
EXPIRE learn:redis:pipeline:a 600
EXPIRE learn:redis:pipeline:b 600
```

也就是让这两个 key 在 `600` 秒后自动过期。

这里的 `...selectedKeys` 是 JavaScript 的剩余参数语法。它会把传进来的多个参数收集成数组：

```js
setTtlForDemoKeys(keys.pipelineA, keys.pipelineB)
```

在函数内部等价于：

```js
selectedKeys = [
  keys.pipelineA,
  keys.pipelineB,
]
```

然后这段循环：

```js
for (const key of selectedKeys) {
  pipeline.expire(key, ttlSeconds);
}
```

会对每个 key 添加一条 `EXPIRE` 命令。

注意：`pipeline.expire(...)` **不会立刻执行 Redis 命令**。它只是把命令先放进 pipeline 队列里。

真正发送给 Redis 的是：

```js
await pipeline.exec();
```

所以流程是：

```text
创建 pipeline
  -> 把 EXPIRE key1 600 放入队列
  -> 把 EXPIRE key2 600 放入队列
  -> exec 一次性发送给 Redis
```

为什么用 Pipeline？

如果不用 Pipeline，代码可能是：

```js
await redis.expire(keys.pipelineA, ttlSeconds);
await redis.expire(keys.pipelineB, ttlSeconds);
```

这会产生两次网络往返：

```text
Node.js -> Redis: EXPIRE keyA
Redis -> Node.js: result

Node.js -> Redis: EXPIRE keyB
Redis -> Node.js: result
```

使用 Pipeline 后，是批量发送：

```text
Node.js -> Redis:
  EXPIRE keyA 600
  EXPIRE keyB 600

Redis -> Node.js:
  resultA
  resultB
```

所以 Pipeline 的主要作用是：**减少网络往返，提高批量操作效率**。

还要注意两个点：

1. `EXPIRE` 只对已经存在的 key 有效。
   如果 key 不存在，Redis 返回 `0`。

2. Pipeline 不是事务。
   它只是批量发送命令，不等于 PostgreSQL 那种事务回滚机制。

如果你想看到返回值，可以这样改：

```js
const results = await pipeline.exec();
console.log(results);
```

返回结构类似：

```js
[
  [null, 1],
  [null, 1],
]
```

含义是：

```text
第一个 null：没有错误
1：EXPIRE 设置成功
```

一句话总结：

`setTtlForDemoKeys(...selectedKeys)` 是一个批量工具函数，用 Pipeline 给多个 Redis key 设置相同的过期时间，避免学习示例产生的 key 永久留在 Redis 里。
