# 02. Mem0 API、scope 与可运行示例

## 这一篇学什么

上一篇讲的是 Agent 记忆的基础模型。这一篇进入当前工程的 Mem0 SDK 用法：如何添加、检索、列出、更新、查看历史、删除记忆，以及如何用 scope 隔离不同层级的记忆。

当前安装的 `mem0ai` 版本是 `3.0.6`，见 [package.json](../package.json#L20)。我已检查本地安装的类型声明，当前工程用到的核心方法包括：

- `add(messages, options)`：写入一组对话，让 Mem0 抽取 memory。
- `search(query, options)`：用自然语言检索 memory。
- `getAll(options)`：按过滤条件列出 memory。
- `get(memoryId)`：读取单条 memory。
- `update(memoryId, { text })`：更新 memory 文本。
- `history(memoryId)`：查看 memory 变更历史。
- `deleteAll(options)`：按 scope 删除 memory。

这些 API 在当前工程里的基础调用集中在 [src/mem0-test.mjs](../src/mem0-test.mjs#L13)。

## add：写入的不是普通字符串，而是一段对话

当前工程基础示例里，`MemoryClient` 的创建在 [src/mem0-test.mjs](../src/mem0-test.mjs#L13)：

```js
const client = new MemoryClient({
  apiKey: process.env.MEM0_API_KEY,
});
```

`apiKey` 来自 `.env`。没有它，云端 Mem0 请求会失败。

`add` 的输入通常是消息数组，而不是单个字符串：

```js
const conversation = [
  { role: "user", content: "我是素食主义者，而且对坚果过敏。" },
  { role: "assistant", content: "好的，我会记住你的饮食偏好。" },
];

await client.add(conversation, { userId: "demo-user" });
```

为什么这样设计：Mem0 要从对话里判断哪些内容值得记。用户说“我对坚果过敏”是事实，助手说“好的”不是事实，但这两条放在一起能帮助记忆系统理解上下文。

执行后发生什么：真实 Mem0 会异步抽取、去重、分类，然后生成一条或多条 memory。当前工程注释中的历史输出显示，记忆结果会包含 `id`、`memory`、`userId`、`categories`、`createdAt`、`updatedAt` 等字段，见 [src/mem0-test.mjs](../src/mem0-test.mjs#L81)。

## search：语义检索，不是 Redis GET

基础示例的搜索在 [src/mem0-test.mjs](../src/mem0-test.mjs#L34)：

```js
const searchResult = await client.search("用户的饮食限制是什么？中文回答", {
  filters: { user_id: USER_ID },
  topK: 5,
});
```

参数含义：

- `query`：自然语言问题。它不需要和原文完全一样。
- `filters.user_id`：只在某个用户的 memory 中检索，避免不同用户串记忆。
- `topK`：最多返回几条结果。它不是“只保存 5 条”，而是“本次检索最多取 5 条”。

返回值形状是：

```json
{
  "results": [
    {
      "id": "...",
      "memory": "User is a vegetarian and is allergic to nuts",
      "score": 0.2346
    }
  ]
}
```

`score` 表示相关性，不是事实可信度。高分只说明“这条记忆和查询更相关”，不说明它一定正确或最新。

## getAll、get、update、history 各解决什么问题

`getAll` 在 [src/mem0-test.mjs](../src/mem0-test.mjs#L43)。它适合调试和管理，不适合每轮 Agent 调用都全量读取。因为 Agent 每轮通常只需要和当前问题相关的 memory，全量塞进去会增加噪声和 token。

`get` 在 [src/mem0-test.mjs](../src/mem0-test.mjs#L54)。它按 memory id 精确读取一条，适合管理界面或用户想查看某条记忆详情。

`update` 在 [src/mem0-test.mjs](../src/mem0-test.mjs#L57)。它适合用户纠正记忆，例如“我现在不住北京了，搬到杭州了”。更新记忆比简单新增更重要，因为旧事实如果一直存在，检索时可能和新事实冲突。

`history` 在 [src/mem0-test.mjs](../src/mem0-test.mjs#L62)。它帮助你理解 memory 的演化：原来是什么，后来改成什么。做 Agent 产品时，这对排查“为什么它记错了”很有用。

`deleteAll` 在 [src/mem0-test.mjs](../src/mem0-test.mjs#L67)。它会按 scope 删除数据，学习时常用于清理测试用户。

## scope：userId、runId、agentId 的区别

scope 是 Mem0 学习里最容易混淆的部分。当前工程的 scope 示例在 [src/mem0-scoped-memory-test.mjs](../src/mem0-scoped-memory-test.mjs#L23)。

`userId` 表示“这个用户长期相关”。例如：

```js
await client.add(messages, { userId: USER_ID });
```

适合保存用户画像、长期偏好、稳定背景。搜索时使用：

```js
filters: { user_id: USER_ID }
```

`runId` 表示“某次运行或某个会话相关”。当前工程把它当作会话 ID 使用，见 [addSessionMemory](../src/mem0-scoped-memory-test.mjs#L47)：

```js
await client.add(messages, { userId: USER_ID, runId: RUN_ID });
```

搜索时使用 `AND`，见 [searchSessionMemory](../src/mem0-scoped-memory-test.mjs#L58)：

```js
filters: { AND: [{ user_id: USER_ID }, { run_id: RUN_ID }] }
```

为什么要同时带 `user_id` 和 `run_id`：`runId` 是会话维度，`userId` 是用户维度。两者合起来才表示“这个用户的这个会话”。只按 `run_id` 查，多个用户如果用了同名 session，就可能互相污染。

`agentId` 表示“某个 Agent 相关”。当前工程在 [addAgentMemory](../src/mem0-scoped-memory-test.mjs#L76) 写入：

```js
await client.add(messages, { agentId: AGENT_ID });
```

适合保存角色和工作方式，例如“旅行规划助手要多给备选方案”。搜索时用：

```js
filters: { agent_id: AGENT_ID }
```

## 为什么 add 后要稍后 search

[src/mem0-scoped-memory-test.mjs](../src/mem0-scoped-memory-test.mjs#L122) 提示 “add 已提交（异步处理），稍后再运行 search”。这是因为 Mem0 不是简单把字符串插入数组。真实服务可能要做抽取、向量化、索引更新、去重和分类。刚 add 完立刻 search，可能还没检索到。

这和 Redis 的 `SET` 不一样。Redis `SET key value` 返回成功后，马上 `GET key` 就应该拿到值。Mem0 更像“提交一段对话给记忆管道处理”，最终 memory 可能稍后可检索。

## 本地运行：先写入，再检索，再清理

运行 scope 示例：

```powershell
pnpm.cmd mem0:scoped
```

默认动作是 `add`，会写入用户层、会话层、Agent 层三类记忆。

稍等几秒后运行：

```powershell
pnpm.cmd mem0:scoped search
```

你应该观察三个输出：

- 用户记忆能回答“用户住在哪里，有什么爱好”。
- 会话记忆能回答“这次对话要先做什么”。
- Agent 记忆能回答“这个 Agent 的角色和回答方式”。

清理测试数据：

```powershell
pnpm.cmd mem0:scoped --cleanup
```

这会执行三次删除，分别清理 user、user + run、agent，代码在 [src/mem0-scoped-memory-test.mjs](../src/mem0-scoped-memory-test.mjs#L111)。

## 常见错误和边界

缺少 `MEM0_API_KEY` 时，脚本会直接退出，见 [src/mem0-scoped-memory-test.mjs](../src/mem0-scoped-memory-test.mjs#L103)。这类错误不是代码逻辑错，而是环境变量没配置。

scope 写入和搜索不一致时，会查不到。例如写入时用了 `{ userId, runId }`，搜索时只按 `{ user_id }`，可能会混入用户层和会话层结果；搜索时 run_id 写错，则当前会话记忆为空。

不要把所有临时任务都写入 user 层。用户下次打开新会话时，不应该继续被旧任务污染。当前 Agent 示例通过分类器区分 `write_user` 和 `write_session`，见 [classifyAndPersist](../src/mem0-redis-mem0-agent.mjs#L300)。
