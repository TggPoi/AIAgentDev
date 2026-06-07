# 01. 从 Agent 记忆基础理解 Mem0

## 先建立知识地图

学习 Mem0 之前，先把 Agent 记忆拆成几层：

- 消息历史：最近几轮 `user/assistant/system/tool` 消息，通常直接放进模型上下文。它解决“刚刚说了什么”的问题。
- 摘要记忆：当消息太多时，把旧消息压缩成摘要，减少 token。它解决“上下文太长”的问题。
- 长期记忆：跨会话仍然有价值的事实，比如用户身份、长期偏好、过敏、工作背景。它解决“下次还能认得用户”的问题。
- 会话记忆：只对当前任务有效的事实，比如“这次先写 Q1 总结”。它解决“当前任务上下文”的问题。
- Agent 角色记忆：和某个 Agent 绑定的工作方式或角色设定，比如“学习导师要解释为什么”。它解决“同一个 Agent 应保持什么行为”的问题。

当前工程正好覆盖这些层级：Redis 保存短期消息，Mem0 保存长期和会话级事实，LangChain Agent 在调用模型前把检索到的记忆注入为 `SystemMessage`。核心代码入口在 [src/mem0-redis-mem0-agent.mjs](../src/mem0-redis-mem0-agent.mjs#L364)。

## Mem0 是什么

直观理解：Mem0 是 Agent 的“外部记忆层”。模型本身不会自动长期记住用户，普通聊天历史也会因为窗口长度、进程重启或 TTL 过期而丢失。Mem0 的作用是把对话中值得保留的事实抽出来，存成可检索的 memory。下次用户提问时，应用先按用户、会话或 Agent 维度检索相关 memory，再把结果放回模型上下文。

它不是数据库的替代品。数据库适合保存确定结构的业务数据，比如订单、用户表、权限。Mem0 适合保存从自然语言对话中抽取出的事实，并在之后用自然语言问题找回来。

它也不是 Redis 的替代品。Redis 更适合短期、快速、明确 key 的数据，比如当前会话消息、工具缓存、限流计数。Mem0 更适合长期、语义化、跨轮检索的记忆。

## 为什么不能只把全部聊天存进 prompt

把全部聊天塞给模型看似简单，但会有几个问题。

第一，成本会持续上升。每轮都带上越来越长的历史，token 会越来越多。

第二，重要信息会被噪声淹没。寒暄、草稿、已废弃方案都和真正长期有用的事实混在一起。

第三，生命周期不清楚。“我住在杭州”可能长期有效，“这次先写 Q1 总结”只对当前会话有效。如果不分层，旧任务很容易污染新任务。

第四，进程重启后短期历史可能消失。当前工程用 Redis 保存当前会话消息，但 Redis key 设置了 TTL，见 [RedisMessageStore.saveMessages](../src/mem0-redis-mem0-agent.mjs#L170)。这意味着 Redis 负责“短期兜底”，不是永久人格档案。

## 什么时候应该写入记忆

应该写入的是“未来可能还要用”的事实：

- 用户身份：姓名、职业、居住地。
- 长期偏好：回答风格、技术栈偏好、饮食禁忌。
- 当前任务状态：本会话内的大纲、进度、临时决策。
- Agent 行为约定：某个 Agent 的角色和回答方式。

不应该写入的是没有长期价值的信息：

- “你好”“谢谢”“继续”。
- 助手刚生成但用户未确认采纳的普通建议。
- 一次性临时请求，比如“帮我写一句祝福语”。
- 已经被后续对话否定的旧事实，除非系统支持更新和历史追踪。

当前工程用一个分类器判断本轮对话应写入 `user` 还是 `session`，提示词在 [CLASSIFIER_PROMPT](../src/mem0-redis-mem0-agent.mjs#L49)，结构化输出 schema 在 [memorySchema](../src/mem0-redis-mem0-agent.mjs#L35)。

## 先用离线脚本观察机制

建议先运行：

```powershell
pnpm.cmd mem0:offline
```

这个脚本在 [src/mem0-learning-offline-demo.mjs](../src/mem0-learning-offline-demo.mjs#L1)。它不调用真实 Mem0，而是用 `OfflineMemoryClient` 模拟核心流程。这样你能先理解数据变化，再学习真实 API。

脚本里的 `add` 在 [src/mem0-learning-offline-demo.mjs](../src/mem0-learning-offline-demo.mjs#L80)。输入是一组消息：

```js
[
  { role: "user", content: "我叫小明，住在杭州，长期喜欢骑行和摄影。" },
  { role: "assistant", content: "好的，这属于跨会话也有用的用户画像。" },
]
```

执行后，本地数组新增类似对象：

```json
{
  "id": "mem_1",
  "memory": "我叫小明，住在杭州，长期喜欢骑行和摄影。",
  "userId": "learning_user",
  "runId": null,
  "agentId": null
}
```

这里最重要的不是 `id`，而是 scope 字段：`userId/runId/agentId`。scope 决定这条 memory 以后在哪个空间里能被搜到。

脚本里的 `search` 在 [src/mem0-learning-offline-demo.mjs](../src/mem0-learning-offline-demo.mjs#L107)。输入包含查询文本和过滤条件：

```js
await client.search("这次会话要写什么", {
  filters: { user_id: USER_ID, run_id: RUN_ID },
});
```

执行时会先过滤 scope，再做文本匹配。返回值保持 `{ results: [...] }`，是为了贴近真实 `MemoryClient.search()` 的返回结构。

## 记忆注入到底是什么

Mem0 检索结果本身不会自动改变模型。应用必须把检索到的 memory 变成模型输入。当前工程的做法是拼成 `SystemMessage`，见 [buildSystemMessage](../src/mem0-redis-mem0-agent.mjs#L277)。

离线脚本用 `buildMemoryPrompt` 做同样的事，见 [src/mem0-learning-offline-demo.mjs](../src/mem0-learning-offline-demo.mjs#L137)。它会生成类似文本：

```text
【用户长期记忆】
- 我叫小明，住在杭州，长期喜欢骑行和摄影。

【当前会话记忆】
- 这次会话先写 Q1 总结，重点补项目复盘。

请结合以上记忆回答，不能把没有命中的内容当事实。
```

这一步在 Agent 开发里非常关键：记忆系统负责“找回事实”，模型负责“基于事实回答”。如果检索结果没注入，模型就看不到这些记忆；如果注入了错误记忆，模型就可能稳定地答错。

## 常见误区

第一个误区是把“保存消息历史”当成“长期记忆”。消息历史只是原始聊天记录，长期记忆应该是抽取、去重、分层后的事实。

第二个误区是只按 `userId` 检索所有内容。这样会把当前任务状态也带到未来新会话里。当前工程对会话记忆使用 `userId + runId` 组合过滤，见 [searchSessionMemory](../src/mem0-scoped-memory-test.mjs#L58)。

第三个误区是把检索结果当作绝对真相。记忆可能过期、被错误抽取或和最新用户输入冲突。文档和代码里的提示都强调“结合记忆回答，勿编造”，但业务上仍应允许用户纠正记忆。

## 什么时候不用 Mem0

如果只是单轮问答，不需要跨轮记住用户，就不用 Mem0。

如果数据必须强一致、可审计、结构稳定，比如订单状态，不应该只放在 Mem0。

如果只是当前进程内几分钟的缓存，用 Redis 或内存更简单。

如果必须精确匹配 key，比如“session:123 的最近 20 条消息”，Redis 更合适。
