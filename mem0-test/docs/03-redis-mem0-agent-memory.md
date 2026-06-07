# 03. Redis 短期记忆与 Mem0 长期记忆组合进 Agent

## 这一篇学什么

前两篇已经解释了 Mem0 记忆是什么、怎么写入、怎么按 scope 检索。这一篇进入当前工程最完整的 Agent 示例：[src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L1)。

这个文件把记忆拆成两条通道：

- Redis：保存当前会话的短期消息历史，有 TTL，适合回答“刚才说了什么”。
- Mem0：保存跨会话长期事实和当前会话事实，适合回答“我是谁”“我长期偏好什么”“这次任务上下文是什么”。

两者不是谁替代谁，而是生命周期不同、查询方式不同。

## 当前工程的运行前提

Redis 配置在 [docker-compose.yml](../docker-compose.yml#L3)。服务使用 `redis:7-alpine`，端口映射为 `6379:6379`，并用 `redis-server --appendonly yes` 开启 AOF 持久化，见 [docker-compose.yml](../docker-compose.yml#L11)。

启动 Redis：

```powershell
docker compose up -d redis
```

运行 Agent：

```powershell
pnpm.cmd agent
```

这个示例还需要：

- `MEM0_API_KEY`：用于 Mem0 云端记忆。
- `OPENAI_API_KEY`：用于 LangChain `ChatOpenAI` 模型和分类器。
- 可选 `OPENAI_BASE_URL`、`MODEL_NAME`、`MEM0_TOP_K`、`MEMORY_TTL_SECONDS`。

## 一轮调用的完整执行链

核心函数是 [invokeWithMemory](../src/mem0-redis-mem0-agent.mjs#L364)。可以把它理解成“每次用户输入后，Agent 怎样准备上下文、调用模型、保存结果”的流水线。

第一步，从 Redis 读取短期历史：

```js
const history = await redisStore.loadMessages(sessionId);
```

`RedisMessageStore` 定义在 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L108)。它按 sessionId 生成 key，见 [messagesKey](../src/mem0-redis-mem0-agent.mjs#L138)。

如果 `KEY_PREFIX = agent:short_memory`，`SESSION_ID = session_002`，Redis key 是：

```text
agent:short_memory:session_002:messages
```

读取前如果 key 不存在，`loadMessages` 返回空数组。读取后如果存在，会把 JSON 反序列化回 LangChain 消息对象，见 [loadMessages](../src/mem0-redis-mem0-agent.mjs#L152)。

第二步，用当前用户输入去 Mem0 检索相关记忆：

```js
const mem = await mem0Store.search(userText);
```

`Mem0MemoryStore.search` 在 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L246)。它并行做两次检索：

- 用户层：`filters: { user_id: this.userId }`
- 会话层：`filters: { AND: [{ user_id: this.userId }, { run_id: this.sessionId }] }`

为什么并行：这两类检索互不依赖，可以同时发出，减少等待时间。

第三步，把 Mem0 命中的 memory 转成 `SystemMessage`：

```js
const memoryMsg = mem0Store.buildSystemMessage(mem);
```

`buildSystemMessage` 在 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L277)。如果没有任何命中，它返回 `null`。如果命中，会生成类似：

```text
【用户长期记忆】
- 用户住在杭州

【当前会话记忆】
- 本次会话在写 Q1 总结

请结合以上记忆回答，勿编造。
```

第四步，组装本轮模型输入：

```js
const invokeMessages = [
  ...(memoryMsg ? [memoryMsg] : []),
  ...history,
  new HumanMessage(userText),
];
```

顺序很重要。Mem0 检索结果作为系统消息放在前面，Redis 历史消息放在中间，当前用户输入放在最后。这样模型能同时看到“外部记忆”和“最近对话”。

第五步，调用 Agent：

```js
const result = await agent.invoke(
  { messages: invokeMessages },
  { recursionLimit: 30 },
);
```

`recursionLimit` 控制 LangGraph/LangChain 图执行的最大步数，防止工具调用或中间状态无限循环。这里没有工具，但仍保留限制，是工程上的保护。

第六步，过滤并写回 Redis：

```js
const redisMessages = messagesForRedis(result.messages);
await redisStore.saveMessages(sessionId, redisMessages);
```

`messagesForRedis` 在 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L94)。它会删除 `SystemMessage` 和 `SystemMessageChunk`。原因是 Mem0 检索结果只是本轮临时注入，不应该变成 Redis 历史的一部分。

写入 Redis 时，代码使用：

```js
await this.redis.set(this.messagesKey(sessionId), payload, "EX", this.ttlSeconds);
```

这行在 [saveMessages](../src/mem0-redis-mem0-agent.mjs#L170)。执行后 Redis 中的 key 会保存序列化后的消息数组，并设置过期时间。

`EX` 参数表示 TTL 单位是秒。例如 `MEMORY_TTL_SECONDS=1800`，表示 1800 秒后短期消息自动过期。`ttl(sessionId)` 会返回剩余秒数，见 [ttl](../src/mem0-redis-mem0-agent.mjs#L199)。

第七步，分类并写入 Mem0：

```js
const { written, reason } = await mem0Store.classifyAndPersist(userText, assistantText);
```

`classifyAndPersist` 在 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L300)。它用结构化输出分类器判断：

- `write_user = true`：写入用户长期记忆。
- `write_session = true`：写入当前会话记忆。
- 两者都 false：不写入 Mem0。

这一步解决的是“不是每轮都应该记”的问题。寒暄不记，当前任务写 session，长期偏好写 user。

## Redis 中的数据如何变化

假设 Redis 一开始没有 key。

第一轮用户输入后：

1. `loadMessages` 读取 key，Redis 返回 null。
2. Agent 生成回复。
3. `messagesForRedis` 过滤掉 Mem0 注入的系统消息。
4. `saveMessages` 写入 user + assistant 消息数组。
5. Redis key 有 TTL。

第二轮用户输入后：

1. `loadMessages` 读出上一轮 user + assistant。
2. 当前用户消息追加到模型输入。
3. Agent 回复后，新的完整消息数组写回 Redis。
4. TTL 重新设置，相当于这个会话的短期记忆续期。

如果 Redis key 过期，下一轮 `loadMessages` 会返回空数组，但 Mem0 用户层长期记忆仍然可以检索回来。这就是“短期记忆”和“长期记忆”的分工。

## 摘要中间件解决什么问题

Agent 创建在 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L447)。里面使用了 `summarizationMiddleware`，配置在 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L453)：

```js
summarizationMiddleware({
  model,
  summaryPrompt,
  trigger: { messages: 8 },
  keep: { messages: 4 },
})
```

含义：

- `model`：用于生成摘要的模型。
- `summaryPrompt`：告诉模型如何总结旧消息。
- `trigger.messages = 8`：消息数量达到阈值后触发摘要。
- `keep.messages = 4`：摘要后仍保留最近 4 条消息。

摘要不是长期记忆。摘要仍属于当前对话上下文压缩；Mem0 才负责跨会话事实。

## 什么时候用 Redis，什么时候用 Mem0

用 Redis：

- 最近几轮原始消息。
- 当前会话临时缓存。
- 工具结果缓存。
- 限流、锁、队列、事件流。
- 需要明确 key、快速读写、可设置 TTL 的数据。

用 Mem0：

- 用户长期偏好。
- 用户画像。
- 当前会话中需要语义检索的任务事实。
- Agent 角色或行为记忆。
- 需要用自然语言问题找回的事实。

不要把二者混成一层。Redis 的强项是确定 key 的状态管理，Mem0 的强项是语义记忆检索。

## 本工程里可以怎样学习

先跑离线版本：

```powershell
pnpm.cmd mem0:offline
```

观察用户层、会话层、Agent 层怎么被写入和检索。

再跑真实 Mem0 scope：

```powershell
pnpm.cmd mem0:scoped
pnpm.cmd mem0:scoped search
```

最后跑完整 Agent：

```powershell
docker compose up -d redis
pnpm.cmd agent
```

建议测试对话按 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L510) 末尾注释顺序执行：先清空，再寒暄，再自我介绍，再输入当前任务，再重启验证用户层长期记忆。

## 常见坑

第一，Redis 连不上。代码在启动时执行 `redis.ping()`，失败会提示先执行 `docker compose up -d redis`，见 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L413)。

第二，Mem0 写入后马上搜索不到。Mem0 写入可能经历异步处理，尤其是抽取和索引更新。学习时 add 后等几秒再 search。

第三，分类器把任务写入 user 层。当前提示词已经强调“这次、本轮、当前会话”优先 session，但模型分类仍可能出错。生产中应记录 `reason`，必要时提供用户可编辑的记忆管理界面。

第四，SystemMessage 被重复保存。当前工程用 `messagesForRedis` 避免这个问题。如果不做过滤，每轮检索到的 Mem0 记忆都会写回 Redis，后面又再次注入，导致上下文越来越脏。

第五，`pnpm` 在 PowerShell 中无法运行。当前环境可能拦截 `pnpm.ps1`，用 `pnpm.cmd` 即可。
