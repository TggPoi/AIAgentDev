# 主 Agent 与子 Agent 的任务委派流程

## 1. 本文回答的问题

本文围绕三个问题展开：

1. 主 Agent 如何选择子 Agent 并分配任务？
2. 子 Agent 如何判断当前任务已经完成？
3. 子 Agent 完成后，如何把结果返回给主 Agent？

这个工程使用 `deepagents` 提供的 `task` 工具完成子 Agent 委派。最重要的结论是：

> 主 Agent 不会直接调用某个 JavaScript 函数来启动调研员。它会让模型生成一次 `task` 工具调用，由 `deepagents` 框架选择对应子 Agent、创建独立任务上下文、等待任务完成，再将结果包装为一条 `ToolMessage` 返回给主 Agent。

## 2. 先看完整流程

一次调研员委派可以概括为：

```text
主 Agent 阅读用户问题
  -> 主 Agent 判断需要拆分独立调研主题
  -> 主 Agent 生成 task 工具调用
     {
       subagent_type: "researcher",
       description: "调研某个子主题，并将结果写入指定 findings 文件"
     }
  -> deepagents 根据 subagent_type 选择 researcher
  -> 将 description 转换为子 Agent 的 HumanMessage
  -> researcher 独立执行搜索和文件写入
  -> researcher 返回一句完成说明
  -> 子 Agent 的 invoke() 结束
  -> deepagents 将最后一条消息包装为 task 的 ToolMessage
  -> 主 Agent 收到工具结果
  -> 主 Agent 读取 findings 文件，继续起草报告
```

结果实际通过两个渠道返回：

| 渠道 | 内容 | 用途 |
| --- | --- | --- |
| `ToolMessage` | 子 Agent 最后一条回复，例如“已完成并写入 findings 文件”。 | 告诉主 Agent：本次委派已经结束。 |
| 共享工作区文件 | 完整调研材料，例如 `/workspace/sources/findings_xxx.md`。 | 供主 Agent 后续读取和写报告。 |

## 3. 第一阶段：注册可用的子 Agent 类型

### 3.1 工程中定义了三类子 Agent

在 [`agent.mjs`](../../src/agent.mjs#L25) 中，工程定义了调研员配置：

```js
const researcherSubAgent = {
  name: "researcher",
  description: "...",
  systemPrompt: dedent`...`,
  tools: [webSearch],
};
```

另外还有：

| 子 Agent 类型 | 源码 | 作用 |
| --- | --- | --- |
| `researcher` | [`researcherSubAgent`](../../src/agent.mjs#L25) | 搜索一个聚焦子主题，并写入一份调研材料。 |
| `editor` | [`editorSubAgent`](../../src/agent.mjs#L58) | 审阅报告草稿，返回修改建议。 |
| `analyst` | [`analystSubAgent`](../../src/agent.mjs#L87) | 使用 JavaScript REPL 完成数值分析。 |

### 3.2 注册不等于立即执行

[`createDeepAgent()`](../../src/agent.mjs#L200) 接收三类子 Agent：

```js
subagents: [researcherSubAgent, editorSubAgent, analystSubAgent]
```

这行代码的含义是：

> 告诉框架：主 Agent 可以委派给 `researcher`、`editor` 和 `analyst`。

它不是：

> 立即启动一个调研员、一个编辑和一个分析师。

### 3.3 框架会提前创建可复用的子 Agent 图

`deepagents` 在 [`getSubagents()`](../../node_modules/deepagents/dist/index.js#L2220) 中遍历配置，并通过 `createAgent()` 创建子 Agent 图：

```js
for (const agentParams of subagents) {
  agents[agentParams.name] = createAgent({
    model: agentParams.model ?? defaultModel,
    systemPrompt: agentParams.systemPrompt,
    tools: agentParams.tools ?? defaultTools,
    middleware,
    name: agentParams.name,
  });
}
```

因此，更准确的说法是：

- 初始化阶段：框架根据配置创建可复用的子 Agent 图。
- 运行阶段：每次 `task` 调用都使用对应子 Agent 图执行一次新的独立任务。

## 4. 第二阶段：主 Agent 获得 `task` 工具

### 4.1 `createDeepAgent()` 增加子 Agent 中间件

`deepagents` 在 [`createDeepAgent()` 的内部实现](../../node_modules/deepagents/dist/index.js#L8149) 中加入 `createSubAgentMiddleware()`：

```js
createSubAgentMiddleware({
  defaultModel: model,
  defaultTools: effectiveTools,
  defaultInterruptOn: interruptOn,
  subagents: inlineSubagents,
  generalPurposeAgent: false,
})
```

### 4.2 子 Agent 中间件为主 Agent 注册 `task`

[`createSubAgentMiddleware()`](../../node_modules/deepagents/dist/index.js#L2315) 会创建一个中间件，并向主 Agent 增加 `task` 工具：

```js
return createMiddleware({
  name: "subAgentMiddleware",
  tools: [createTaskTool({...})],
  ...
});
```

### 4.3 `task` 工具需要两个参数

[`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2263) 定义了 `task` 工具。其输入结构位于 [`index.js`](../../node_modules/deepagents/dist/index.js#L2303)：

```js
schema: z.object({
  description: z.string().describe("The task to execute with the selected agent"),
  subagent_type: z.string().describe("Name of the agent to use ..."),
})
```

两个参数的作用：

| 参数 | 作用 |
| --- | --- |
| `subagent_type` | 选择子 Agent 类型，例如 `researcher`、`analyst` 或 `editor`。 |
| `description` | 告诉本次子 Agent 需要完成的具体任务。 |

## 5. 第三阶段：主 Agent 决定如何分配任务

### 5.1 主 Agent 根据提示词进行规划

主 Agent 的工作流程写在 [`orchestratorPrompt`](../../src/agent.mjs#L106) 中。

标准流程要求主 Agent 在调研阶段委派调研员，必要时再委派分析师和编辑：

| 阶段 | 规则位置 | 执行方式 |
| --- | --- | --- |
| 调研 | [`agent.mjs`](../../src/agent.mjs#L123) | 委派 `researcher`。 |
| 分析 | [`agent.mjs`](../../src/agent.mjs#L124) | 确实需要数值计算时委派 `analyst`。 |
| 审阅 | [`agent.mjs`](../../src/agent.mjs#L126) | 草稿完成后委派 `editor`。 |

允许的类型写在 [`agent.mjs`](../../src/agent.mjs#L131)：

```text
researcher、analyst、editor、general-purpose
```

### 5.2 任务分配是模型生成的工具调用

主 Agent 并不是在 `agent.mjs` 中执行一段固定的 `if...else` 来分配任务。

实际过程是：

1. 主 Agent 的模型读取用户问题和系统提示词。
2. 模型判断任务需要拆成哪些独立子主题。
3. 模型输出一个或多个 `task` 工具调用。
4. LangChain 的工具执行节点执行这些调用。

例如，主 Agent可能生成：

```js
task({
  subagent_type: "researcher",
  description:
    "调研 LangGraph 的架构特点。最多搜索 3 次，将结论和来源写入 /workspace/sources/findings_langgraph.md。",
});
```

如果还需要调研 AutoGen，可以再生成：

```js
task({
  subagent_type: "researcher",
  description:
    "调研 AutoGen 的架构特点。最多搜索 3 次，将结论和来源写入 /workspace/sources/findings_autogen.md。",
});
```

### 5.3 两个独立任务可以并行执行

`deepagents` 的默认提示词建议并行启动相互独立的任务，见 [`TASK_SYSTEM_PROMPT`](../../node_modules/deepagents/dist/index.js#L2130)。

如果主 Agent 在一条模型回复中生成多个 `task` 工具调用，LangChain 的 [`ToolNode`](../../node_modules/langchain/dist/agents/nodes/ToolNode.js#L305) 会通过 `Promise.all()` 执行它们：

```js
outputs = await Promise.all(
  aiMessage.tool_calls.map((call) => this.runTool(call, config, state)),
);
```

因此，两次 `researcher` 委派可以并行运行。

### 5.4 “最多 2 个调研员”不是代码硬限制

工程提示词规定：

- 每份报告最多两个调研员：[`agent.mjs`](../../src/agent.mjs#L139)
- 最多并行启动两个调研员：[`agent.mjs`](../../src/agent.mjs#L141)

但是当前 JavaScript 代码中没有计数器，也没有拦截第三次 `researcher` 调用的逻辑。

因此，这只是提示词约束：

```text
模型应该遵守，但框架没有强制保证。
```

如果后续需要严格限制，应该增加代码层面的校验或工具调用限制中间件。

## 6. 第四阶段：框架把任务交给指定子 Agent

### 6.1 校验 `subagent_type`

当主 Agent 调用 `task` 后，[`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2274) 首先读取参数：

```js
const { description, subagent_type } = input;
```

随后检查类型是否合法：

```js
if (!(subagent_type in subagentGraphs)) {
  throw new Error(...);
}
```

如果类型合法，就获取对应子 Agent：

```js
const subagent = subagentGraphs[subagent_type];
```

### 6.2 子 Agent 收到什么任务内容

框架在 [`index.js`](../../node_modules/deepagents/dist/index.js#L2281) 中创建子 Agent 状态：

```js
const subagentState = filterStateForSubagent(getCurrentTaskInput());
subagentState.messages = [
  new HumanMessage({ content: description }),
];
```

关键点：

> `description` 会成为子 Agent 的一条新用户消息。

因此，子 Agent 看到的不是主 Agent 的完整对话，而是当前这一次委派的清晰任务描述。

### 6.3 子 Agent 仍然拥有自己的角色规则

以 `researcher` 为例：

- 固定角色来自 [`researcherSubAgent.systemPrompt`](../../src/agent.mjs#L29)。
- 当前具体任务来自 `task.description`。

可以理解为：

```text
systemPrompt:
  你是一名专业调研员，只处理一个子主题，最多搜索三次，写入一个 findings 文件。

HumanMessage:
  调研 LangGraph 的架构特点，并将结果写入 findings_langgraph.md。
```

系统提示词规定“如何工作”，任务描述规定“这一次做什么”。

### 6.4 上下文隔离

框架通过 [`filterStateForSubagent()`](../../node_modules/deepagents/dist/index.js#L2180) 过滤传给子 Agent 的状态。

被排除的字段位于 [`EXCLUDED_STATE_KEYS`](../../node_modules/deepagents/dist/index.js#L1968)：

```js
[
  "messages",
  "todos",
  "structuredResponse",
  "skillsMetadata",
  "memoryContents",
]
```

这意味着：

- 子 Agent 不继承主 Agent 的完整消息历史。
- 子 Agent 不继承主 Agent 的 todo 列表。
- 子 Agent 收到自己的新任务消息。
- 子 Agent 可以通过共享文件系统交换完整资料。

## 7. 第五阶段：子 Agent 如何判断任务完成

子 Agent 的完成分为两层：

1. 业务层：子 Agent 根据角色提示词判断工作目标已经完成。
2. 框架层：子 Agent 输出不包含工具调用的最终消息，执行循环结束。

### 7.1 业务层：提示词定义完成条件

`researcher` 的完成条件非常明确，见 [`agent.mjs`](../../src/agent.mjs#L34)：

```text
1. 可选：列出 todo
2. 最多调用 3 次 web_search
3. 整理结构化摘要
4. 调用 write_file 一次
5. 用一句话确认已完成，然后立即停止
```

其中最关键的规则是：

- 写入一份指定的 `findings_*.md` 文件：[`agent.mjs`](../../src/agent.mjs#L37)
- 确认完成后立即停止：[`agent.mjs`](../../src/agent.mjs#L38)
- `write_file` 后禁止再次搜索：[`agent.mjs`](../../src/agent.mjs#L49)

因此，调研员知道任务完成，是因为其系统提示词明确规定了终点。

### 7.2 框架层：没有工具调用时结束循环

LangChain 的 Agent 路由逻辑位于 [`ReactAgent.js`](../../node_modules/langchain/dist/agents/ReactAgent.js#L353)：

```js
const lastMessage = state.messages.at(-1);

if (
  !AIMessage.isInstance(lastMessage) ||
  !lastMessage.tool_calls ||
  lastMessage.tool_calls.length === 0
) {
  return exitNode;
}
```

含义是：

- 如果子 Agent 仍然返回 `web_search`、`write_file` 或其他工具调用，继续执行。
- 如果子 Agent 返回普通文本，不再请求任何工具，结束本次 Agent 循环。

随后 [`subagent.invoke(...)`](../../node_modules/deepagents/dist/index.js#L2290) 完成并返回结果：

```js
const result = await subagent.invoke(subagentState, subagentConfig);
```

### 7.3 当前没有强制停止钩子

当前工程没有实现：

```text
一旦 researcher 调用 write_file，立即在 JavaScript 层强制终止。
```

现有停止规则主要依靠提示词。如果模型违反提示词并在写文件后继续请求工具，框架仍可能继续执行，直到：

- 模型最终返回不带工具调用的消息；
- 触发递归步数上限；
- 或工具执行抛出异常。

## 8. 第六阶段：结果如何回传给主 Agent

### 8.1 子 Agent 执行完成后返回状态

`task` 工具会等待子 Agent 完整执行：

```js
const result = await subagent.invoke(subagentState, subagentConfig);
```

此时 `result` 包含子 Agent 的最终状态，例如：

- 子 Agent 的消息历史；
- 文件工具执行产生的状态；
- 可选的结构化结果。

### 8.2 提取子 Agent 最后一条消息

框架在 [`returnCommandWithStateUpdate()`](../../node_modules/deepagents/dist/index.js#L2196) 中提取结果。

如果没有结构化结果，则读取最后一条消息：

```js
const messages = result.messages;
content = messages?.[messages.length - 1]?.content || "Task completed";
```

例如，`researcher` 的最后一条消息可能是：

```text
调研完成，已将结果写入 /workspace/sources/findings_langgraph.md。
```

### 8.3 包装为 `ToolMessage`

框架将完成说明包装成一条名为 `task` 的 [`ToolMessage`](../../node_modules/deepagents/dist/index.js#L2208)：

```js
new ToolMessage({
  content,
  tool_call_id: toolCallId,
  name: "task",
})
```

这条消息会回到主 Agent 的消息历史。

可以理解为：

```text
主 Agent:
  请 researcher 调研 LangGraph。

task 工具:
  调研完成，已写入 /workspace/sources/findings_langgraph.md。
```

### 8.4 主 Agent 下一步做什么

收到 `ToolMessage` 后，主 Agent 会再次调用模型。模型可以：

1. 读取调研员写入的 `findings_*.md` 文件。
2. 等待其他并行调研员完成。
3. 必要时调用 `analyst`。
4. 汇总调研材料并起草报告。
5. 调用 `editor` 审阅草稿。
6. 根据反馈修订并定稿。

### 8.5 完整材料通过文件传递

调研员提示词强调：

```text
其他人只能看到你写入的文件，内容必须完整、自洽
```

对应位置：[`agent.mjs`](../../src/agent.mjs#L50)。

因此，`ToolMessage` 通常只携带简短完成说明。完整调研结果应写入：

```text
/workspace/sources/findings_*.md
```

主 Agent 后续通过 `read_file` 读取这些文件。

## 9. CLI 如何展示子 Agent 完成信息

CLI 使用流式模式运行主 Agent：

```js
{
  streamMode: "updates",
  subgraphs: true,
  recursionLimit,
}
```

对应位置：[`cli.mjs`](../../src/cli.mjs#L222)。

当 `task` 工具完成后，[`logToolResults()`](../../src/cli.mjs#L171) 会识别名为 `task` 的工具结果：

```js
if (msg.name === "task") {
  const preview = String(msg.content).slice(0, 120).replace(/\n/g, " ");
  console.log(`  task done: ${preview}...`);
}
```

这就是终端中出现以下日志的原因：

```text
task done: 调研完成，已将结果写入 /workspace/sources/findings_langgraph.md...
```

CLI 只负责展示信息，不负责决定子 Agent 是否完成。

## 10. 一次委派的详细时序图

```text
用户
  |
  | 提交调研问题
  v
主 Agent
  |
  | 根据 orchestratorPrompt 拆分子主题
  | 生成 task({ subagent_type, description })
  v
LangChain ToolNode
  |
  | 执行 task 工具
  v
deepagents createTaskTool()
  |
  | 校验 subagent_type
  | 选择 subagentGraphs[subagent_type]
  | 过滤主 Agent 状态
  | 将 description 设置为新的 HumanMessage
  v
researcher / analyst / editor
  |
  | 独立执行工具调用
  | 根据自身 systemPrompt 判断工作是否完成
  | 返回不带 tool_calls 的最终消息
  v
deepagents createTaskTool()
  |
  | 等待 subagent.invoke() 完成
  | 提取子 Agent 最后一条消息
  | 创建 name = "task" 的 ToolMessage
  v
主 Agent
  |
  | 收到完成摘要
  | 从共享工作区读取完整文件
  | 继续分析、起草、审阅或定稿
  v
CLI
  |
  | 打印 task done: ...
```

## 11. 关键源码导航

### 工程代码

| 内容 | 源码 |
| --- | --- |
| 调研员配置 | [`researcherSubAgent`](../../src/agent.mjs#L25) |
| 编辑配置 | [`editorSubAgent`](../../src/agent.mjs#L58) |
| 分析师配置 | [`analystSubAgent`](../../src/agent.mjs#L87) |
| 主 Agent 流程 | [`orchestratorPrompt`](../../src/agent.mjs#L106) |
| 子 Agent 注册 | [`subagents`](../../src/agent.mjs#L206) |
| CLI 的流式执行 | [`run()`](../../src/cli.mjs#L209) |
| CLI 展示 `task done` | [`logToolResults()`](../../src/cli.mjs#L171) |

### 框架代码

| 内容 | 源码 |
| --- | --- |
| 默认 `task` 使用说明 | [`TASK_SYSTEM_PROMPT`](../../node_modules/deepagents/dist/index.js#L2106) |
| 状态过滤 | [`filterStateForSubagent()`](../../node_modules/deepagents/dist/index.js#L2180) |
| 结果回写 | [`returnCommandWithStateUpdate()`](../../node_modules/deepagents/dist/index.js#L2196) |
| 创建子 Agent 图 | [`getSubagents()`](../../node_modules/deepagents/dist/index.js#L2220) |
| 创建 `task` 工具 | [`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2263) |
| 子 Agent 执行入口 | [`subagent.invoke(...)`](../../node_modules/deepagents/dist/index.js#L2290) |
| 注册子 Agent 中间件 | [`createSubAgentMiddleware()`](../../node_modules/deepagents/dist/index.js#L2315) |
| 并行工具执行 | [`ToolNode`](../../node_modules/langchain/dist/agents/nodes/ToolNode.js#L305) |
| Agent 停止判断 | [`ReactAgent`](../../node_modules/langchain/dist/agents/ReactAgent.js#L353) |

## 12. 阅读时最容易混淆的概念

| 容易混淆的说法 | 更准确的理解 |
| --- | --- |
| 注册 `researcherSubAgent` 就是启动调研员。 | 注册只是提供一种可委派类型；真正执行发生在 `task` 工具调用时。 |
| 主 Agent 直接调用 `researcher()`。 | 主 Agent 生成 `task({ subagent_type: "researcher", description })` 工具调用。 |
| 子 Agent 读取主 Agent 的完整对话。 | 框架过滤消息历史，并将 `description` 设置为新的任务消息。 |
| 子 Agent 写完文件后，JavaScript 会强制停止。 | 当前主要依靠提示词要求立即停止；框架在最终消息不含工具调用时结束循环。 |
| 完整报告直接放进 `ToolMessage` 返回。 | `ToolMessage` 通常只是简短摘要；完整材料通过共享工作区文件传递。 |
| “最多 2 个调研员”一定不会被突破。 | 当前是提示词约束，不是代码硬限制。 |

## 13. 建议的学习顺序

1. 先读 [`researcherSubAgent`](../../src/agent.mjs#L25)，理解调研员的业务终点。
2. 再读 [`orchestratorPrompt`](../../src/agent.mjs#L120)，理解主 Agent 何时委派。
3. 阅读 [`subagents`](../../src/agent.mjs#L206)，理解类型注册。
4. 阅读 [`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2263)，理解任务参数如何传递。
5. 阅读 [`subagent.invoke(...)`](../../node_modules/deepagents/dist/index.js#L2290)，理解子 Agent 如何执行。
6. 阅读 [`returnCommandWithStateUpdate()`](../../node_modules/deepagents/dist/index.js#L2196)，理解结果如何回传。
7. 最后阅读 [`logToolResults()`](../../src/cli.mjs#L171)，理解终端日志如何展示回传结果。

## 14. 在 VS Code 中使用本文

1. 在 VS Code 中打开本文件。
2. 按 `Ctrl+Shift+V` 打开 Markdown 预览。
3. 点击本文中的源码链接，即可跳转到工程代码或本地依赖源码。
4. 升级 `deepagents` 或 `langchain` 依赖后，`node_modules` 中的行号可能变化，需要重新核对框架源码链接。
