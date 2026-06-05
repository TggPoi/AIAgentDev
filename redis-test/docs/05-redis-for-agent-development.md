# 05. Agent 开发中的 Redis 记忆系统

这一章把 Redis 放回 Agent 开发场景里学习。你要掌握的不是“Agent 可以用 Redis 存消息”这一句话，而是要能设计一个可维护的记忆系统：会话怎么隔离、短期记忆怎么过期、长期记忆放哪里、缓存怎么失效、并发怎么避免覆盖、Redis 故障时怎么降级。

当前工程示例入口是 [src/agent-with-redis-memory.mjs](../src/agent-with-redis-memory.mjs#L1)。

## 1. Agent 为什么需要 Redis

一个普通函数调用是无状态的：

```text
输入 -> 函数 -> 输出
```

但对话 Agent 通常需要状态：

```text
第 1 轮：用户说自己的名字
第 2 轮：用户问“你还记得我叫什么吗？”
```

如果没有记忆系统，第 2 轮只把当前问题发给模型，模型不知道第 1 轮内容。

Redis 可以保存短期对话上下文：

```text
session_id -> messages
```

每次调用 Agent 前读取历史消息，调用后写回最新消息。

## 2. 短期记忆、长期记忆、工作记忆

Agent 记忆不要混成一种。至少要区分三类。

### 2.1 短期记忆

短期记忆保存最近对话上下文，通常有 TTL。

示例：

```text
agent:short_memory:session_001:messages
ttl: 1800 seconds
```

适合放 Redis。

### 2.2 长期记忆

长期记忆保存用户长期偏好、事实、历史记录、向量化知识。

示例：

```text
用户喜欢中文回答
用户公司名称
历史任务报告
文档向量
```

更适合 PostgreSQL、向量数据库或文件存储。Redis 可以缓存长期记忆的读取结果，但不应该作为唯一来源。

### 2.3 工作记忆

工作记忆是一次 Agent run 中的临时状态，例如当前步骤、已访问 URL、工具调用结果。

适合放 Redis Hash、Set、Stream：

```text
agent:run:run_1001 -> Hash
agent:run:run_1001:seen_urls -> Set
agent:run:run_1001:events -> Stream
```

## 3. 当前工程的短期记忆流程

核心流程在 [invokeWithMemory](../src/agent-with-redis-memory.mjs#L75)：

```text
1. 根据 sessionId 从 Redis 读取历史 messages
2. 把历史 messages 和本轮 HumanMessage 拼起来
3. 调用 agent.invoke
4. 拿到 result.messages
5. 写回 Redis，并设置 TTL
```

伪代码：

```js
const history = await store.loadMessages(sessionId);

const result = await agent.invoke({
  messages: [...history, new HumanMessage(userText)],
});

await store.saveMessages(sessionId, result.messages);
```

这就是“短期记忆”的最小闭环。

## 4. RedisMessageStore 设计

当前工程用一个类封装 Redis 读写，见 [RedisMessageStore](../src/agent-with-redis-memory.mjs#L44)。

### 4.1 messagesKey

```js
messagesKey(sessionId) {
  return `${this.keyPrefix}:${sessionId}:messages`;
}
```

这个函数把业务 key 生成规则集中起来。好处是：

- key 命名统一。
- 后续修改前缀只改一个地方。
- 不容易在不同函数里拼错 key。

如果 `keyPrefix = "agent:short_memory"`，`sessionId = "demo_user_001"`，最终 key 是：

```text
agent:short_memory:demo_user_001:messages
```

### 4.2 loadMessages

```js
async loadMessages(sessionId) {
  const raw = await this.redis.get(this.messagesKey(sessionId));
  if (!raw) return [];
  return mapStoredMessagesToChatMessages(JSON.parse(raw));
}
```

这段代码分成四步：

1. 根据 sessionId 生成 Redis key。
2. 从 Redis 读取 JSON 字符串。
3. 如果 key 不存在，返回空数组。
4. 如果存在，先 `JSON.parse`，再恢复成 LangChain message 对象。

为什么 key 不存在时返回 `[]`？

因为新会话没有历史消息，这不是错误。Agent 可以用空历史开始第一轮对话。

### 4.3 saveMessages

```js
async saveMessages(sessionId, messages) {
  const payload = JSON.stringify(mapChatMessagesToStoredMessages(messages));
  await this.redis.set(this.messagesKey(sessionId), payload, "EX", this.ttlSeconds);
}
```

这段代码分成三步：

1. 把 LangChain message 对象转换成可存储普通对象。
2. `JSON.stringify` 成字符串。
3. 用 `SET ... EX` 写入 Redis，同时设置 TTL。

这里使用 `SET ... EX` 而不是 `SET` 后再 `EXPIRE`，原因是写入和设置过期时间应该尽量放在同一条命令里，避免中间失败导致 key 永不过期。

## 5. 会话隔离

Agent 记忆系统最严重的错误之一是不同用户共用 key。

错误设计：

```text
agent:short_memory:messages
```

正确设计：

```text
agent:short_memory:{sessionId}:messages
```

如果你的系统有租户、用户、会话三层边界，可以进一步设计：

```text
agent:tenant:{tenantId}:user:{userId}:session:{sessionId}:messages
```

选择多少层取决于业务需要。原则是：**不能让一个用户读到另一个用户的记忆**。

## 6. TTL 策略

当前工程默认：

```js
const MEMORY_TTL = Number(process.env.MEMORY_TTL_SECONDS ?? 1800);
```

也就是 1800 秒，30 分钟。

TTL 不是随便写的，它表达产品策略：

| 场景 | 建议 TTL |
| --- | --- |
| 普通聊天短期记忆 | 30 分钟到数小时 |
| 工具结果缓存 | 几分钟到几小时 |
| 验证码、一次性 token | 几分钟 |
| 锁 | 几秒到几十秒 |
| 长任务状态 | 任务预期执行时间的数倍 |

Agent 短期记忆 TTL 太短，用户稍微停顿就丢上下文；TTL 太长，Redis 内存压力变大，也可能保留不该保留的隐私上下文。

## 7. 摘要压缩

Redis 只保存消息，不负责判断消息太多怎么办。当前工程使用 LangChain 的 `summarizationMiddleware`，见 [summarizationMiddleware](../src/agent-with-redis-memory.mjs#L115)。

消息增长问题：

```text
第 1 轮：2 条消息
第 2 轮：4 条消息
第 3 轮：6 条消息
...
```

如果一直把完整历史塞给模型，会遇到：

- token 成本增加。
- 模型上下文超限。
- 响应变慢。
- Redis 保存的 value 越来越大。

摘要压缩的目标是：

```text
旧消息 -> 摘要
最近几轮 -> 原文保留
```

这样模型仍然知道历史重点，但不需要读取所有原始消息。

需要注意：摘要是模型生成的，可能遗漏信息。重要事实如果必须长期保存，应该写入结构化数据库。

## 8. 工具结果缓存

Agent 调用工具时，经常会遇到重复请求：

```text
用户：北京天气怎么样？
Agent 调用 weather("beijing")
用户：那北京今天适合出门吗？
Agent 可能再次需要 weather("beijing")
```

可以缓存工具结果：

```js
async function cachedToolCall(redis, key, ttlSeconds, fn) {
  const cached = await redis.get(key);
  if (cached) {
    return JSON.parse(cached);
  }

  const result = await fn();
  await redis.set(key, JSON.stringify(result), "EX", ttlSeconds);
  return result;
}
```

缓存 key 要包含工具名和参数：

```text
agent:tool_cache:weather:beijing
agent:tool_cache:search:sha256(query)
```

不要只写：

```text
agent:tool_cache
```

否则不同工具、不同参数会互相覆盖。

## 9. 限流

Agent 调用模型和工具都有成本。Redis 可以做时间窗口限流。

示例：每个用户每分钟最多 20 次请求。

```js
async function checkRateLimit(redis, userId) {
  const key = `agent:rate_limit:${userId}:minute`;
  const count = await redis.incr(key);

  if (count === 1) {
    await redis.expire(key, 60);
  }

  if (count > 20) {
    throw new Error("Rate limit exceeded");
  }
}
```

这个写法在学习阶段可以理解，但生产中要注意：`INCR` 和 `EXPIRE` 是两条命令，如果中间崩溃，可能出现没有 TTL 的计数器。更严谨的做法是 Lua 脚本。

## 10. 并发和锁

如果同一个 session 同时来了两个请求：

```text
请求 A 读取历史 messages
请求 B 读取历史 messages
请求 A 写回 messages + A
请求 B 写回 messages + B
```

最后可能只保留 B，A 的结果被覆盖。

可以用 Redis 锁：

```js
const lockKey = `agent:lock:session:${sessionId}`;
const lockValue = crypto.randomUUID();

const acquired = await redis.set(lockKey, lockValue, "NX", "EX", 30);
if (acquired !== "OK") {
  throw new Error("Session is already running");
}
```

释放锁时不能直接 `DEL lockKey`，因为锁可能已经过期并被别的请求拿到。生产中要用 Lua：

```lua
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
else
  return 0
end
```

这个逻辑的意思是：只有锁的 value 还是我自己的随机值，才能删除。

## 11. 任务队列

Agent 经常有异步任务：

- 抓取网页。
- 解析 PDF。
- 生成 embedding。
- 写入向量库。
- 批量调用外部工具。

简单队列可以用 List：

```redis
LPUSH agent:queue:jobs "{\"taskId\":\"1001\",\"type\":\"crawl\"}"
RPOP agent:queue:jobs
```

更可靠的事件流可以用 Stream：

```redis
XADD agent:events * type crawl_requested task_id 1001
```

List 更简单，Stream 更适合需要确认、重试、多 worker 消费的场景。

## 12. Redis 故障时怎么降级

Redis 是外部服务，可能不可用。Agent 系统要提前决定故障策略。

| Redis 用途 | Redis 挂了怎么办 |
| --- | --- |
| 短期记忆 | 可以无历史继续对话，但体验下降 |
| 工具缓存 | 直接调用真实工具 |
| 限流 | 可以拒绝请求，或使用本地临时限流 |
| 锁 | 高风险场景应拒绝并发执行 |
| 队列 | 任务入口应暂停或转入备用队列 |

不要让 Redis 故障导致整个服务无意义崩溃。不同用途的降级策略不一样。

## 13. 当前工程练习

1. 启动 Redis：

```powershell
docker compose up -d redis
```

2. 运行 Agent 示例：

```powershell
node src/agent-with-redis-memory.mjs
```

3. 在另一个终端查看 key：

```powershell
docker exec -it agent_redis redis-cli
```

```redis
SCAN 0 MATCH agent:* COUNT 20
TTL agent:short_memory:demo_user_001:messages
GET agent:short_memory:demo_user_001:messages
```

4. 在 Agent 中输入 `:clear`，再查看 Redis：

```redis
GET agent:short_memory:demo_user_001:messages
```

你应该看到 key 被清理。

## 14. 本章完成标准

学完本章，你应该能回答：

1. Agent 短期记忆为什么适合 Redis？
2. LangChain messages 为什么不能直接裸存？
3. 为什么 session id 必须进入 Redis key？
4. TTL 代表什么产品策略？
5. 摘要压缩解决什么问题，不能解决什么问题？
6. 工具缓存 key 应该包含哪些信息？
7. 为什么简单锁要用 `SET NX EX`？
8. Redis 故障时，短期记忆和锁的降级策略为什么不同？
