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



**为什么并行：这两类检索互不依赖，可以同时发出，减少等待时间。**



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

第四步，组装本轮模型输入，在 [invokeWithMemory](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:364) 里，当前顺序是：

```js
const invokeMessages = [
  ...(memoryMsg ? [memoryMsg] : []),
  ...history,
  new HumanMessage(userText),
];
```

顺序很重要。**Mem0 检索结果**作为**系统消息放在前面**，**Redis 历史消息放在中间**，当前用户输入放在最后。这样模型能同时看到“外部记忆”和“最近对话”。



------

## 【重点】检索出来的消息顺序处理：

这个顺序的含义是：

1. `memoryMsg` 放最前面：把 Mem0 检索到的长期/会话记忆作为系统级背景，先告诉模型“这些是本轮可参考的外部记忆”。
2. `history` 放中间：再给模型当前 Redis 保存的短期聊天历史，让它知道最近几轮发生了什么。
3. `new HumanMessage(userText)` 放最后：最后放当前用户输入，让模型明确本轮真正要回答的问题是什么。

顺序会影响模型理解重点。模型通常更重视消息序列中“角色”和“位置”共同表达的上下文关系：系统消息用于约束和背景，历史消息用于连续性，最后一条用户消息通常被当作当前任务。

如果把当前用户输入放到历史前面：

```js
[new HumanMessage(userText), ...history]
```

模型会看到“当前问题”后面又跟了一堆旧对话，容易把最后一条历史消息误当作最新任务，回答可能跑偏。

如果把 `memoryMsg` 放到最后：

```js
[...history, new HumanMessage(userText), memoryMsg]
```

这在语义上也不自然：系统记忆变成了用户问题之后才出现的补充约束，可能干扰“当前用户到底问了什么”。而且有些消息处理逻辑更习惯系统消息靠前。

如果不放 `memoryMsg`，模型只能依赖 Redis 历史和当前输入。Redis 过期、重启或新会话后，长期记忆就无法参与回答。

所以当前顺序是合理的：

```text
Mem0 检索记忆（背景/约束）
→ Redis 短期历史（最近上下文）
→ 当前用户输入（本轮问题）
```

另外，后面 [messagesForRedis](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:94) 会把 `SystemMessage` 过滤掉再写回 Redis。这也说明 `memoryMsg` 只是“本轮临时注入”，不是要永久混入短期聊天历史。



更准确地说：`invokeMessages` 会按你组装的顺序传给 `agent.invoke`，但中间的 `history` 不会被统一“结构为 AIMessage”。

当前代码是：

```js
const invokeMessages = [
  ...(memoryMsg ? [memoryMsg] : []),
  ...history,
  new HumanMessage(userText),
];
```

实际结构是：

```text
可能存在的 SystemMessage
→ Redis 里恢复出来的历史消息数组
→ 当前这一轮的 HumanMessage
```

其中：

1. `memoryMsg`

如果 Mem0 检索到了记忆，`buildSystemMessage()` 返回的是：

```js
new SystemMessage(...)
```

所以第一段确实是 `SystemMessage`。

如果没检索到记忆，`memoryMsg` 是 `null`，这一段就不会出现。

2. `history`

`history` 来自：

```js
const history = await redisStore.loadMessages(sessionId);
```

它不是单个 `AIMessage`，而是一组历史聊天消息。通常长这样：

```text
HumanMessage   // 上一轮用户输入
AIMessage      // 上一轮助手回复
HumanMessage   // 再上一轮用户输入
AIMessage      // 再上一轮助手回复
...
```

具体类型取决于之前写入 Redis 的 `result.messages`。保存前代码只过滤掉了 `SystemMessage/SystemMessageChunk`：

```js
const redisMessages = messagesForRedis(result.messages);
await redisStore.saveMessages(sessionId, redisMessages);
```

所以 Redis 里的历史通常包含 `HumanMessage` 和 `AIMessage`，而不是只包含 `AIMessage`。

3. `new HumanMessage(userText)`

最后这一项一定是当前用户输入，被显式构造成：

```js
new HumanMessage(userText)
```

所以整体更像：

```text
[
  SystemMessage,          // Mem0 记忆，可能没有
  HumanMessage,           // Redis 历史：旧用户消息
  AIMessage,              // Redis 历史：旧助手回复
  HumanMessage,
  AIMessage,
  HumanMessage            // 当前用户输入
]
```

重点：`agent.invoke({ messages: invokeMessages })` 接收到的是一个已经按顺序排好的消息数组。LangChain 不会把“三个子数组”分别变成 `SystemMessage / AIMessage / HumanMessage`；因为这里也没有三个子数组，**展开运算符 `...` 已经把它们展开成一个扁平数组了**。



因为“扁平数组”只是说数组不再嵌套，不代表消息失去了类型。

在 LangChain 里，**每一项消息对象本身就带有类型**。比如：

```js
const invokeMessages = [
  ...(memoryMsg ? [memoryMsg] : []),
  ...history,
  new HumanMessage(userText),
];
```

展开后大概是：

```js
[
  new SystemMessage("【用户长期记忆】..."),
  new HumanMessage("上一轮用户说的话"),
  new AIMessage("上一轮助手回复"),
  new HumanMessage("当前用户最新问题")
]
```

Agent 判断消息角色主要靠“每个元素自己的消息类型”，不是靠外层数组分组。

具体到当前代码：

`memoryMsg` 来自：

```js
const memoryMsg = mem0Store.buildSystemMessage(mem);
```

而 `buildSystemMessage()` 里面明确返回：

```js
return new SystemMessage(...)
```

所以它自己就是 `SystemMessage`。

`history` 来自 Redis：

```js
const history = await redisStore.loadMessages(sessionId);
```

保存时用的是：

```js
mapChatMessagesToStoredMessages(messages)
```

读取时用的是：

```js
mapStoredMessagesToChatMessages(JSON.parse(raw))
```

这两个函数会保留并恢复消息类型。所以以前保存进去的 `HumanMessage` 读出来还是 `HumanMessage`，以前的 `AIMessage` 读出来还是 `AIMessage`。

当前最新提问是这里显式创建的：

```js
new HumanMessage(userText)
```

所以它一定是 `HumanMessage`。

“之前的对话历史”不是一种特殊 message 类型。它只是消息数组中排在当前最新 `HumanMessage` 之前的那些消息。Agent/模型通过顺序理解它们是历史上下文，通过最后一条 `HumanMessage` 理解“这是当前要回答的问题”。

最终传给模型适配器时，通常会被转换成类似这样的角色结构：

```js
[
  { role: "system", content: "【用户长期记忆】..." },
  { role: "user", content: "上一轮用户说的话" },
  { role: "assistant", content: "上一轮助手回复" },
  { role: "user", content: "当前用户最新问题" }
]
```

所以关键点是：

```text
消息类型由每个 message 对象决定
历史/当前由数组顺序决定
当前问题通常是最后一个 HumanMessage
SystemMessage 不靠位置变成 system，而是它本身就是 SystemMessage
```

这也是为什么当前代码后面要用 `messagesForRedis()` 过滤 `SystemMessage`：Mem0 注入的系统记忆只是本轮上下文，不应该被当成普通历史消息保存回 Redis。



------

## 【重点】Agent调用时的message处理：

第五步，调用 Agent：

```js
const result = await agent.invoke(
  { messages: invokeMessages },
  { recursionLimit: 30 },
);
```

`recursionLimit` 控制 LangGraph/LangChain 图执行的最大步数，防止工具调用或中间状态无限循环。这里没有工具，但仍保留限制，是工程上的保护。

**处理invokeMessages时，**不是“先按 role 拆分成几组再处理”，而是：

```text
Agent 接收一个有顺序的 BaseMessage[]
→ LangChain/Agent 中间件按顺序读取这个消息数组
→ ChatOpenAI 适配器把每个 Message 转成 OpenAI 需要的 role 消息
→ 最终以 messages 数组提交给聊天模型
```

也就是说，它不是把所有内容拼成一个普通字符串 prompt，例如：

```text
系统记忆 + 历史对话 + 当前问题
```

然后作为一个大字符串发给模型。

在你当前代码里，因为用的是 `ChatOpenAI`，最终更接近这种结构：

```js
[
  {
    role: "system",
    content: "【用户长期记忆】..."
  },
  {
    role: "user",
    content: "上一轮用户问题"
  },
  {
    role: "assistant",
    content: "上一轮助手回答"
  },
  {
    role: "user",
    content: "当前最新问题"
  }
]
```

但注意，它不会把所有 `system` 放一组、所有 `user` 放一组、所有 `assistant` 放一组。顺序仍然保留。否则历史对话就乱了。

所以更准确的理解是：

```text
role 决定每条消息的身份
顺序决定对话发生的时间线
最后一个 HumanMessage 通常就是当前最新提问
```

是的，你现在问到的是关键点。但“按 role 拆分处理”这个说法还不够准确，专业一点应该这样理解：

```text
Agent 不是把 messages 当成一个普通字符串 prompt。
Agent 也不是把 messages 按 role 分成 system/user/assistant 三堆。
Agent 接收的是一个有顺序的结构化消息序列 BaseMessage[]。
每条消息自己带 type/role，顺序仍然保留。
最后由具体模型适配器把 BaseMessage[] 转成模型服务需要的 messages 格式。
```

你当前代码在 [invokeWithMemory](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:364) 里组装的是：

```js
const invokeMessages = [
  ...(memoryMsg ? [memoryMsg] : []),
  ...history,
  new HumanMessage(userText),
];

const result = await agent.invoke(
  { messages: invokeMessages },
  { recursionLimit: 30 },
);
```



这里的 `messages` 本质上不是一个“prompt 字符串”，而是 LangChain 的 `BaseMessage[]`。

**第一层：你传入的是 BaseMessage 对象数组**

LangChain 的消息对象都有自己的类型。`BaseMessage` 类型定义里有 `type`、`content`、`additional_kwargs`、`response_metadata` 等字段，见 [base.d.ts](d:/AI_Agent_Project/mem0-test/node_modules/.pnpm/@langchain+core@1.1.48_open_19b10f90b204c0412756b14b7c0478cd/node_modules/@langchain/core/dist/messages/base.d.ts:77)。

例如：

```js
new SystemMessage("Mem0 检索到的记忆")
new HumanMessage("用户的问题")
new AIMessage("助手之前的回答")
```

它们不是普通对象，也不是普通字符串。每个对象内部都有类型：

```text
SystemMessage.type = "system"
HumanMessage.type = "human"
AIMessage.type = "ai"
```

所以即使数组被展开成扁平数组，类型信息也没有丢。

展开后大概是：

```js
[
  SystemMessage { type: "system", content: "【用户长期记忆】..." },

  HumanMessage  { type: "human", content: "上一轮用户说的话" },
  AIMessage     { type: "ai", content: "上一轮助手的回答" },

  HumanMessage  { type: "human", content: "当前用户最新问题" }
]
```

**第二层：history 为什么还能保留 HumanMessage / AIMessage**

你的 `history` 来自 Redis：

```js
const history = await redisStore.loadMessages(sessionId);
```

读取逻辑在 [loadMessages](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:152)：

```js
return mapStoredMessagesToChatMessages(JSON.parse(raw));
```

LangChain 的 `mapStoredMessagesToChatMessages()` 会根据保存时的 `type` 重建具体消息对象。类型声明里也明确写了：它会把 `StoredMessage[]` 转回 `BaseMessage[]`，见 [utils.d.ts](d:/AI_Agent_Project/mem0-test/node_modules/.pnpm/@langchain+core@1.1.48_open_19b10f90b204c0412756b14b7c0478cd/node_modules/@langchain/core/dist/messages/utils.d.ts:119)。

也就是说，Redis 里保存的不是“纯文本历史”，而是被序列化过的消息结构。保存时：

```js
mapChatMessagesToStoredMessages(messages)
```

读取时：

```js
mapStoredMessagesToChatMessages(...)
```

所以以前的 `HumanMessage` 读出来还是 `HumanMessage`，以前的 `AIMessage` 读出来还是 `AIMessage`。

**第三层：Agent 不会按 role 分堆，而是保留时间线**

这是最容易误解的地方。

模型对话必须保留顺序。比如：

```text
user: 我的名字是小明
assistant: 好的，我记住了
user: 我叫什么？
```

如果按 role 拆成两堆：

```text
所有 user 消息放一起
所有 assistant 消息放一起
```

对话时间线就坏了。模型不知道哪个回答对应哪个问题。

所以 Agent/ChatModel 处理的是“有序消息序列”，不是“role 分组”。

更准确地说：

```text
role/type 负责告诉模型“这句话是谁说的”
数组顺序负责告诉模型“这些话发生的先后顺序”
最后一个 HumanMessage 通常负责告诉模型“本轮最新问题是什么”
```

你的代码当前语义是：

```text
1. SystemMessage：Mem0 检索出来的记忆，本轮背景
2. history：Redis 里恢复出的旧对话，保持原始 user/assistant 顺序
3. HumanMessage：当前用户最新输入
```

**第四层：ChatOpenAI 最终会转成 provider 的 role messages**

你当前用的是：

```js
const model = new ChatOpenAI(...)
```

`ChatOpenAI` 是聊天模型适配器。它最终要调用 OpenAI 兼容的 Chat Completions / Responses 接口，这类接口接受的不是单个字符串，而是类似这样的结构：

```js
[
  {
    role: "system",
    content: "【用户长期记忆】..."
  },
  {
    role: "user",
    content: "上一轮用户说的话"
  },
  {
    role: "assistant",
    content: "上一轮助手回复"
  },
  {
    role: "user",
    content: "当前最新问题"
  }
]
```

本地安装的 `@langchain/openai` 转换器里也明确写了这层职责：把 LangChain message types 映射成 OpenAI roles，并保留消息数组，见 [completions.d.cts](d:/AI_Agent_Project/mem0-test/node_modules/.pnpm/@langchain+openai@1.4.7_@la_b4114d395b5d1e066a4926bc8e77873f/node_modules/@langchain/openai/dist/converters/completions.d.cts:244)。

所以你可以把整个过程理解成：

```text
你的代码：
BaseMessage[]

LangChain Agent：
带状态和中间件的消息序列

ChatOpenAI：
OpenAI-compatible messages[]

模型服务：
带 role 的对话输入
```

**第五层：它和“单个 Prompt”有什么本质区别**

单个 prompt 是这样：

```text
你是助手。
用户长期记忆：...
历史对话：...
当前问题：...
```

这当然也能用，但问题是所有内容都混在一个字符串里了。模型只能靠文本标题猜测角色。

结构化 messages 是这样：

```js
[
  { role: "system", content: "你是助手..." },
  { role: "user", content: "我叫小明" },
  { role: "assistant", content: "好的" },
  { role: "user", content: "我叫什么？" }
]
```

区别是：

```text
单 prompt：角色是你写在文本里的约定。
chat messages：角色是 API 协议里的结构字段。
```

后者更可靠，也更适合多轮对话、工具调用、系统指令、函数调用、消息压缩。

**第六层：当前代码里 SystemMessage 有两类来源**

你这个文件里其实有两个“系统级上下文”：

第一类是 `createAgent` 的 `systemPrompt`：

```js
const agent = createAgent({
  model,
  tools: [],
  systemPrompt:
    "你是会话助手。结合系统消息中的长期/会话记忆回答，中文简短。有对话摘要则据此继续。",
  ...
});
```

位置在 [mem0-redis-mem0-agent.mjs](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:447)。

第二类是每轮动态检索出来的 `memoryMsg`：

```js
const memoryMsg = mem0Store.buildSystemMessage(mem);
```

它来自 Mem0 查询结果，位置在 [mem0-redis-mem0-agent.mjs](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:372)。

这两类都属于“影响模型行为的高优先级上下文”，但职责不同：

```text
systemPrompt：固定角色和回答规则
memoryMsg：本轮根据用户问题动态检索到的记忆
```

这也是为什么 `memoryMsg` 放在历史消息前面：它不是历史聊天，而是本轮回答时要参考的外部事实。

**第七层：为什么还要过滤 SystemMessage 再写 Redis**

这里非常关键。

调用结束后代码做了：

```js
const redisMessages = messagesForRedis(result.messages);
await redisStore.saveMessages(sessionId, redisMessages);
```

`messagesForRedis` 在 [mem0-redis-mem0-agent.mjs](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:94)：

```js
function messagesForRedis(messages) {
  return messages.filter(
    (m) => !SystemMessage.isInstance(m) && !SystemMessageChunk.isInstance(m),
  );
}
```

原因是：`memoryMsg` 是“本轮临时注入的检索结果”，不是用户真实说过的话，也不是助手真实回答过的话。

如果不滤掉，会出现这种污染：

```text
第 1 轮：Mem0 检索出 A，作为 SystemMessage 注入
写回 Redis：A 被保存进历史

第 2 轮：Mem0 又检索出 A
Redis 历史里也有 A
模型看到两份 A

第 3 轮：继续重复污染
```

所以当前设计是：

```text
Mem0 记忆：每轮临时检索、临时注入
Redis 历史：只保存真实对话消息和摘要，不保存 Mem0 注入的系统记忆
```

**最终结论**

你这句话：

> Agent 在处理提问时，会先把 messages 中的元素按照 role 进行拆分处理，而不是作为单个 Prompt 直接提交给大模型

需要改成更专业的版本：

```text
Agent 接收的是一个有序的结构化消息序列 BaseMessage[]。
每个元素通过自身的 message type 表示 system/human/ai/tool 等角色。
Agent 和模型适配器不会把它们按 role 分堆，而是保留顺序，并在调用 ChatOpenAI 时映射成 provider 支持的 role-based messages 数组。
因此它不是单个纯文本 Prompt，而是结构化 Chat Messages。
```

一句话总结：

```text
role/type 决定“谁说的”，数组顺序决定“什么时候说的”，最后一条 HumanMessage 决定“这轮要回答什么”。
```



### 对消息处理的个人理解：

~~~
所以invokeMessages数组中memoryMsg是作为Systemmessage，
history和新的HumanMessage(userText)按照时间线合并为AImessage和usermessage，作为之前的对话历史上下文和目前最新的提问，我的理解对吗？
~~~

基本对，但有两点要改得更精确。

当前代码：

```js
const invokeMessages = [
  ...(memoryMsg ? [memoryMsg] : []),
  ...history,
  new HumanMessage(userText),
];
```

可以理解为：

```text
memoryMsg
→ 作为 SystemMessage，提供本轮 Mem0 检索出来的记忆背景

history
→ 作为之前的对话历史上下文，里面按原时间线保留 HumanMessage / AIMessage

new HumanMessage(userText)
→ 作为当前最新用户提问，放在消息序列最后
```

你说的这句里需要修正的是：

> history 和新的 HumanMessage(userText) 按照时间线合并为 AIMessage 和 usermessage

更准确是：

```text
history 本身已经是一组历史消息，里面可能有 HumanMessage、AIMessage，也可能有摘要相关消息。
new HumanMessage(userText) 是当前新增的用户消息。
二者不会“合并为 AIMessage 和 usermessage”，而是按顺序拼接成一个更长的消息时间线。
```

也就是：

```js
[
  SystemMessage(memoryMsg),

  // history 里已有的历史时间线
  HumanMessage("上一轮用户输入"),
  AIMessage("上一轮助手回复"),
  HumanMessage("再上一轮用户输入"),
  AIMessage("再上一轮助手回复"),

  // 当前最新提问
  HumanMessage(userText)
]
```

最终传给 `ChatOpenAI` 时，会被映射成类似：

```js
[
  { role: "system", content: "Mem0 检索记忆..." },
  { role: "user", content: "上一轮用户输入" },
  { role: "assistant", content: "上一轮助手回复" },
  { role: "user", content: "当前最新提问" }
]
```

所以你的核心理解是对的：

```text
memoryMsg = 本轮系统级记忆背景
history = 之前的对话历史上下文
HumanMessage(userText) = 当前最新提问
```

只要记住：`history` 不是统一变成 `AIMessage`，它保留原来的消息类型和顺序。



## 【重点】对话完成，处理新的消息记忆写入：

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



**这里是覆盖写入，不是追加写入。**

`saveMessages()` 里面是：

```js
const payload = JSON.stringify(mapChatMessagesToStoredMessages(messages));
await this.redis.set(this.messagesKey(sessionId), payload, "EX", this.ttlSeconds);
```

`redis.set(key, payload, "EX", ttl)` 的语义是：

```text
把这个 key 的值设置为 payload
如果 key 原来存在，直接覆盖旧值
同时重新设置 TTL
```

所以 Redis 中这个 key：

```text
agent:short_memory:session_002:messages
```

每一轮都会被写成“当前最新的完整消息历史”。

不是这样：

```text
旧历史 + 新消息 append 到 Redis List
```

而是这样：

```text
读取旧历史
→ 拼上本轮 HumanMessage
→ agent.invoke 得到包含新回复的 result.messages
→ 过滤 SystemMessage
→ 整个消息数组重新 JSON 序列化
→ SET 覆盖同一个 Redis key
```

为什么这样做是合理的：

1. `result.messages` 已经包含完整时间线

因为调用前传入了：

```js
[
  memoryMsg,
  ...history,
  new HumanMessage(userText)
]
```

Agent 返回的 `result.messages` 通常是在这个基础上追加助手回复、摘要等处理后的完整消息状态。所以写回时不需要再手动 append。

2. 可以配合摘要中间件

如果 `summarizationMiddleware` 触发了压缩，`result.messages` 可能已经不是“旧历史 + 新消息”的简单追加，而是被中间件整理过的最新状态。直接覆盖 Redis，才能保存压缩后的状态。

3. TTL 会续期

每次 `SET ... EX` 都会重新设置过期时间。也就是说当前会话只要持续聊天，短期记忆就会续期；如果长时间不聊，它会自动过期。

所以你的理解可以写成：

```text
是的，saveMessages 会用本轮 agent.invoke 后的最新消息数组，覆盖当前 sessionId 对应 Redis key 中旧的对话历史。
```

但注意：它覆盖的不是“丢掉旧历史只保存本轮”，而是“用最新完整历史替换旧版本历史”。





------

第七步，分类并写入 Mem0：

```js
const { written, reason } = await mem0Store.classifyAndPersist(userText, assistantText);
```

`classifyAndPersist` 在 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L300)。它用结构化输出分类器判断：

- `write_user = true`：写入用户长期记忆。
- `write_session = true`：写入当前会话记忆。
- 两者都 false：不写入 Mem0。

这一步解决的是“不是每轮都应该记”的问题。寒暄不记，当前任务写 session，长期偏好写 user。

### mem 0的classifier消息处理机制：

`classifier` 是一个**专门用来做“记忆分层判断”的 LLM 调用器**，不是主 Agent 本身，也不是 Mem0 客户端。

它在 [src/mem0-redis-mem0-agent.mjs](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:434) 创建：

```js
const classifier = new ChatOpenAI({
  model: process.env.MODEL_NAME,
  ...llmOpts,
}).withStructuredOutput(memorySchema);
```

拆开看：

```js
new ChatOpenAI(...)
```

创建了一个聊天模型实例，和主回答模型一样，也使用 `MODEL_NAME`、`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`temperature: 0` 这些配置。

关键是后面这一段：

```js
.withStructuredOutput(memorySchema)
```

这表示：不要让模型随便输出一段自然语言，而是要求它按 `memorySchema` 返回结构化对象。

`memorySchema` 是：

```js
const memorySchema = z.object({
  write_user: z.boolean(),
  write_session: z.boolean(),
  reason: z.string(),
});
```

所以 `classifier.invoke(...)` 的返回值会尽量是：

```js
{
  write_user: true 或 false,
  write_session: true 或 false,
  reason: "分类理由"
}
```

它在 `classifyAndPersist()` 里被调用：

```js
const { write_user, write_session, reason } = await this.classifier.invoke([
  new SystemMessage(CLASSIFIER_PROMPT),
  new HumanMessage(`用户：${userText}\n助手：${assistantText}`),
]);
```

这里它的任务是判断：

```text
本轮 userText + assistantText 里，有没有值得写入 Mem0 的新事实？
如果有，应该写到 user 层，还是 session 层？
```

例如：

用户说：

```text
我叫小明，住在杭州，长期喜欢骑行。
```

classifier 可能返回：

```js
{
  write_user: true,
  write_session: false,
  reason: "用户提供了跨会话仍有用的长期身份和偏好信息"
}
```

然后代码执行：

```js
await this.client.add(turn, { userId: this.userId });
```

写入 Mem0 用户层。

如果用户说：

```text
这次会话先帮我写 Q1 总结，重点放项目复盘。
```

classifier 可能返回：

```js
{
  write_user: false,
  write_session: true,
  reason: "这是当前会话任务上下文，只对本次会话有效"
}
```

然后代码执行：

```js
await this.client.add(turn, {
  userId: this.userId,
  runId: this.sessionId,
});
```

写入 Mem0 会话层。

所以一句话总结：

```text
classifier = 一个带结构化输出约束的 ChatOpenAI，用来判断本轮对话是否应该写入 Mem0，以及写入 user 层还是 session 层。
```

它和主 Agent 的区别是：

```text
主 Agent：负责回答用户问题
classifier：负责给本轮对话打标签，决定是否持久化记忆
Mem0 client：负责真正 add/search/delete 记忆
```





### messagesForRedis函数的作用：

要过滤SystemMessage，SystemMessageChunk 的核心原因是：`SystemMessage` 在这里不是“真实对话历史”，而是本轮临时注入给模型看的上下文。如果写回 Redis，会污染短期记忆。

当前流程是：

```js
const memoryMsg = mem0Store.buildSystemMessage(mem);

const invokeMessages = [
  ...(memoryMsg ? [memoryMsg] : []),
  ...history,
  new HumanMessage(userText),
];

const result = await agent.invoke({ messages: invokeMessages });

const redisMessages = messagesForRedis(result.messages);
await redisStore.saveMessages(sessionId, redisMessages);
```

`memoryMsg` 是从 Mem0 检索结果构造出来的：

```js
new SystemMessage("【用户长期记忆】...")
```

它的用途是：本轮回答时提醒模型“这些是外部记忆”。它不是用户说的话，也不是助手回答的话。

如果不滤掉，会发生这种问题：

```text
第 1 轮：
Mem0 检索到“用户住在杭州”
作为 SystemMessage 注入
如果写回 Redis，Redis 历史里也保存了这条 SystemMessage

第 2 轮：
又从 Mem0 检索到“用户住在杭州”
Redis 历史里也有上一轮保存的“用户住在杭州”
模型看到两份重复记忆

第 3 轮：
继续累积，短期历史越来越脏
```

所以 `messagesForRedis()` 的设计目标是：**【做好消息边界的处理】**

```text
Redis 只保存真实对话历史
Mem0 记忆每轮动态检索、动态注入
SystemMessage 不进入 Redis
```

这行代码：

```js
return messages.filter(
  (m) => !SystemMessage.isInstance(m) && !SystemMessageChunk.isInstance(m),
);
```

意思是：凡是系统消息，不管是完整消息还是流式消息片段，都不要保存到 Redis。



------

### `SystemMessage` 和 `SystemMessageChunk` 的区别：

`SystemMessage` 是完整的系统消息。

比如：

```js
new SystemMessage("你是会话助手。请结合记忆回答。")
```

它代表一条已经完整构造好的 system role 消息，最终会变成类似：

```js
{
  role: "system",
  content: "你是会话助手。请结合记忆回答。"
}
```

`SystemMessageChunk` 是系统消息的“片段”。

它主要出现在流式输出、消息合并、chunk 处理这类场景。LangChain 的类型定义里写得很清楚：`SystemMessageChunk` represents a chunk of a system message，可以和其他 chunk 拼接。它和 `SystemMessage` 一样，`type` 也是 `"system"`，但它继承的是 `BaseMessageChunk`，不是普通 `BaseMessage`。

可以这样理解：

```text
SystemMessage      = 完整的一条系统消息
SystemMessageChunk = 系统消息的一小段，可被拼接成完整消息
```

当前你的 `buildSystemMessage()` 返回的是 `SystemMessage`，不是 `SystemMessageChunk`。但是过滤函数把 `SystemMessageChunk` 也过滤掉，是一种防御性写法：如果后续换成 streaming、middleware 返回 chunk、或者 LangChain 内部产生了系统消息片段，也不会误写进 Redis。

总结：

```text
为什么过滤：
因为系统消息是运行时上下文/指令/记忆注入，不是对话历史。写进 Redis 会重复、污染、扩大上下文。

SystemMessage：
完整 system 消息。

SystemMessageChunk：
流式或中间处理中的 system 消息片段，可拼接，仍然属于 system 类型。

为什么两个都过滤：
只要是 system 角色，无论完整还是片段，都不应该作为短期聊天历史保存。
```



------

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



## summarizationMiddleware 在当前案例中起到的作用：

在当前案例里，`summarizationMiddleware` 的作用是：**当 Redis 里的短期对话历史越来越长时，把较早的对话压缩成摘要，只保留最近几条原始消息，避免每轮都把完整历史塞给模型。**

它配置在 [src/mem0-redis-mem0-agent.mjs](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:453)：

```js
summarizationMiddleware({
  model,
  summaryPrompt,
  trigger: { messages: 8 },
  keep: { messages: 4 },
})
```

这里每个参数的含义是：

```text
model
= 用哪个模型生成摘要。这里复用了主模型 model。

summaryPrompt
= 摘要提示词。告诉模型如何总结旧对话。

trigger: { messages: 8 }
= 当消息数量达到 8 条左右时，触发摘要。

keep: { messages: 4 }
= 摘要后保留最近 4 条原始消息，其余更早消息压缩成摘要。
```

你的摘要提示词是 [summaryPrompt](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:71)：

```js
const summaryPrompt = `你是对话摘要助手。用中文简洁总结：话题、会话内进度/报错/待办。
用户级长期偏好由外部记忆维护，摘要勿重复堆砌。不要编造。

待摘要的对话：
{messages}

摘要：`;
```

这段提示很重要，它明确要求：

```text
摘要只总结当前对话话题、进度、报错、待办。
用户长期偏好不要重复堆砌，因为长期偏好由 Mem0 管。
```

也就是说，这个 middleware 在你的案例里不是替代 Mem0，而是配合 Mem0：

```text
Mem0：负责长期/会话级语义记忆
Redis：负责短期原始对话历史
summarizationMiddleware：负责当 Redis 历史太长时压缩旧历史
```

**它在执行链里的位置**

每轮调用时，你先组装：

```js
const invokeMessages = [
  ...(memoryMsg ? [memoryMsg] : []),
  ...history,
  new HumanMessage(userText),
];
```

然后调用：

```js
const result = await agent.invoke(
  { messages: invokeMessages },
  { recursionLimit: 30 },
);
```

`summarizationMiddleware` 是 Agent 的 middleware，它会在模型真正回答前检查当前 `messages` 是否太长。

简化流程是：

```text
1. 你从 Redis 加载 history
2. 你从 Mem0 检索 memoryMsg
3. 组装 invokeMessages
4. 进入 agent.invoke
5. summarizationMiddleware 检查 messages 数量
6. 如果没到 8 条，不处理，直接让模型回答
7. 如果达到 8 条，先总结旧消息，保留最近 4 条
8. 模型基于“摘要 + 最近 4 条 + 当前问题”回答
9. result.messages 被写回 Redis
```

**触发前是什么样**

假设还没触发摘要，Redis 历史可能是：

```text
HumanMessage: 用户第 1 轮
AIMessage: 助手第 1 轮

HumanMessage: 用户第 2 轮
AIMessage: 助手第 2 轮

HumanMessage: 用户第 3 轮
AIMessage: 助手第 3 轮
```

下一轮组装后：

```text
SystemMessage: Mem0 检索记忆

HumanMessage: 用户第 1 轮
AIMessage: 助手第 1 轮
HumanMessage: 用户第 2 轮
AIMessage: 助手第 2 轮
HumanMessage: 用户第 3 轮
AIMessage: 助手第 3 轮

HumanMessage: 当前最新问题
```

如果消息数量还没达到触发条件，它不会压缩。

**触发后是什么样**

当消息数量达到 `trigger: { messages: 8 }` 后，它会把较早的对话拿去生成摘要，只保留最近 `keep: { messages: 4 }` 条原始消息。

压缩后，状态大致变成：

```text
HumanMessage: 之前对话摘要：
- 话题是 Q1 总结
- 已决定重点写项目复盘
- order-service 500 错误需要补排查过程

HumanMessage: 最近用户消息
AIMessage: 最近助手回复
HumanMessage: 最近用户消息
AIMessage: 最近助手回复

HumanMessage: 当前最新问题
```

**注意：LangChain 这个 middleware 生成的摘要消息在实现里是一个 `HumanMessage`，并带有 `additional_kwargs: { lc_source: "summarization" }`。所以它不是 `SystemMessage`，后面 `messagesForRedis()` 不会过滤掉它，它会被保存回 Redis。**

这正是你代码里这段判断的意义：

```js
if (redisMessages.length < prevCount + 2) {
  console.log("  ⚡ 已触发压缩");
}
```

位置在 [src/mem0-redis-mem0-agent.mjs](d:/AI_Agent_Project/mem0-test/src/mem0-redis-mem0-agent.mjs:498)。

正常情况下，每轮会增加：

```text
1 条 HumanMessage 当前用户输入
1 条 AIMessage 助手回复
```

所以消息数应该约等于 `prevCount + 2`。

如果触发了摘要，旧消息被压缩删除，消息总数反而可能小于 `prevCount + 2`，于是终端打印：

```text
⚡ 已触发压缩
```

**它和 Redis 写回的关系**

`agent.invoke()` 完成后，你做了：

```js
const redisMessages = messagesForRedis(result.messages);
await redisStore.saveMessages(sessionId, redisMessages);
```

这意味着 Redis 保存的不是“压缩前的旧历史”，而是 Agent middleware 处理后的最新消息状态。

所以一旦摘要触发，Redis 里保存的会是：

```text
摘要消息 + 最近几条原始消息 + 最新助手回复
```

而不是完整原始历史。

这也是为什么 `saveMessages()` 用 `SET` 覆盖写入是合理的：它保存的是“当前最新对话状态”，包括摘要后的状态。

**它不负责什么**

它不负责长期记忆。

比如用户说：

```text
我长期做后端开发，以后回答都希望带代码示例。
```

这类信息应该由 `classifyAndPersist()` 判断后写入 Mem0 用户层。

`summarizationMiddleware` 只是在当前会话历史太长时，把旧聊天压缩成摘要。它不能保证跨会话可检索，也不适合作为用户画像长期存储。

它也不负责 Redis TTL。TTL 是这里控制的：

```js
await this.redis.set(this.messagesKey(sessionId), payload, "EX", this.ttlSeconds);
```

`summary` 只是 Redis value 里的消息内容之一；Redis key 什么时候过期仍由 `MEMORY_TTL_SECONDS` 控制。

**当前案例中的核心作用**

一句话总结：

```text
summarizationMiddleware 在当前代码中负责压缩 Redis 短期对话历史：当消息数达到 8 条时，用模型把较早对话总结成一条摘要消息，只保留最近 4 条原始消息，从而降低上下文长度，并把压缩后的最新状态写回 Redis。
```

更完整地说：

```text
Mem0 解决“跨会话/当前会话事实怎么找回”
Redis 解决“最近对话怎么保存”
summarizationMiddleware 解决“Redis 里的最近对话越来越长，怎么压缩后继续使用”
```





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
