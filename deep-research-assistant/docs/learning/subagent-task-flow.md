# 主 Agent 与子 Agent 的任务委派流程

## 1. 本文回答的问题

本文先围绕三个核心问题展开：

1. 主 Agent 如何选择子 Agent 并分配任务？
2. 子 Agent 如何判断当前任务已经完成？
3. 子 Agent 完成后，如何把结果返回给主 Agent？

然后继续回答几个更底层的问题：

4. `subagents` 配置、`task` 工具和真正运行的子 Agent 实例分别是什么？
5. 哪些上下文会隔离，哪些状态会在父子 Agent 之间共享？
6. 多个 `task` 为什么可以并行，什么情况下并行状态会冲突？
7. Prompt 约束、LangGraph 循环终点和 JavaScript 硬限制有什么区别？
8. 如何通过当前工程中的混合流水线和嵌套实验继续学习？

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

`deepagents` 在 [`getSubagents()`](../../node_modules/deepagents/dist/index.js#L2220) 中遍历配置，并通过 `createAgent()` 创建子 Agent 图。下面只保留最关键的字段：

```js
for (const agentParams of subagents) {
  if ("runnable" in agentParams) {
    agents[agentParams.name] = agentParams.runnable;
  } else {
    agents[agentParams.name] = createAgent({
      model: agentParams.model ?? defaultModel,
      systemPrompt: agentParams.systemPrompt,
      tools: agentParams.tools ?? defaultTools,
      middleware,
      name: agentParams.name,
    });
  }
}
```

因此，更准确的说法是：

- 初始化阶段：框架根据配置创建可复用的子 Agent 图。
- 运行阶段：每次 `task` 调用都使用对应子 Agent 图执行一次新的独立任务。

子 Agent 配置有两种形式：

| 形式 | 框架行为 | 适用场景 |
| --- | --- | --- |
| 普通配置对象 | `deepagents` 根据 `model`、`systemPrompt`、`tools` 和 `middleware` 自动调用 `createAgent()`。 | 原版的 `researcher`、`editor` 和 `analyst`。 |
| 带 `runnable` 的已编译配置 | 框架直接保存并调用传入的 `runnable`。 | 需要自己包裹状态隔离逻辑的嵌套子 Agent。 |

### 3.4 默认还会注册 `general-purpose`

原版显式注册了三类专用子 Agent，但运行时通常还会出现：

```text
general-purpose
```

原因是 [`createDeepAgent()`](../../node_modules/deepagents/dist/index.js#L8132) 默认会检查 harness profile。只要 profile 没有显式关闭通用子 Agent，并且用户没有自己注册同名类型，框架就会将 [`GENERAL_PURPOSE_SUBAGENT`](../../node_modules/deepagents/dist/index.js#L2172) 插入子 Agent 列表：

```js
if (
  !(gpConfig?.enabled === false) &&
  !inlineSubagents.some((item) => item.name === "general-purpose")
) {
  inlineSubagents.unshift(generalPurposeSpec);
}
```

它与专用子 Agent 的差异：

| 类型 | 角色来源 | 工具范围 | skill |
| --- | --- | --- | --- |
| `general-purpose` | 框架默认 Prompt | 默认继承主 Agent 的额外工具 | 默认继承主 Agent 的 skill |
| `researcher` | 工程自定义 Prompt | 只额外开放 `webSearch` | 当前没有单独配置 skill |
| `editor` | 工程自定义 Prompt | 没有额外业务工具 | 当前没有单独配置 skill |
| `analyst` | 工程自定义 Prompt | 通过中间件获得 JavaScript REPL | 当前没有单独配置 skill |

这里的“额外工具”不包括文件工具。自定义子 Agent 也会由 `createDeepAgent()` 自动挂载文件系统中间件，获得 `read_file`、`write_file`、`edit_file`、`ls`、`glob` 和 `grep` 等基础能力。第 15 节会展开说明。

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

这里的 `generalPurposeAgent: false` 容易误解。它不表示原版最终没有 `general-purpose`。原因是 `createDeepAgent()` 已经在更早的预处理阶段将默认通用子 Agent 插入 `inlineSubagents`，随后再关闭 `createSubAgentMiddleware()` 自己重复创建通用子 Agent 的逻辑。详见第 3.4 节。

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

关键前提是：

> 主 Agent 必须在同一条模型回复中一次生成多个 `task` 工具调用。

当前安装的 LangChain 默认使用 `v2` 工具行为，见 [`ReactAgent`](../../node_modules/langchain/dist/agents/ReactAgent.js#L46)。在 `v2` 中，路由器会为每个工具调用创建一个独立的 [`Send`](../../node_modules/langchain/dist/agents/ReactAgent.js#L370)，交给 LangGraph 并行调度：

```js
return regularToolCalls.map(
  (toolCall) => new Send(TOOLS_NODE_NAME, {
    ...state,
    lg_tool_call: toolCall,
  }),
);
```

LangChain 仍保留 `v1` 行为。在 `v1` 中，同一条消息中的多个工具调用会进入同一个 [`ToolNode`](../../node_modules/langchain/dist/agents/nodes/ToolNode.js#L305)，再通过 `Promise.all()` 并行执行：

```js
outputs = await Promise.all(
  aiMessage.tool_calls.map((call) => this.runTool(call, config, state)),
);
```

两种实现细节不同，但对本工程的结论相同：两次独立的 `researcher` 委派可以并行运行。

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

还要注意：

> 这个默认过滤列表只覆盖 `deepagents` 已知的通用字段，不会自动识别业务代码新增的全部局部状态。

如果后续为父 Agent 或子 Agent 增加模型调用计数、工具调用计数、摘要事件等局部字段，并行子 Agent 仍可能把这些字段回写到父 Agent。当前工程的嵌套实验专门演示了这一问题以及修复方法，见第 18 节。

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

### 8.3 包装为 `Command` 和 `ToolMessage`

框架不会只返回一条裸 `ToolMessage`。它会先创建 LangGraph 的 [`Command`](../../node_modules/deepagents/dist/index.js#L2208)，把允许回写的子 Agent 状态与一条名为 `task` 的 `ToolMessage` 放入 `update`：

```js
return new Command({
  update: {
    ...stateUpdate,
    messages: [
      new ToolMessage({
        content,
        tool_call_id: toolCallId,
        name: "task",
      }),
    ],
  },
});
```

`Command.update` 的含义是：

```text
子 Agent 已经完成。
请将这些允许共享的状态更新合并回父 Agent 图。
同时，将这条 task ToolMessage 加入父 Agent 的消息历史。
```

因此，回传过程包含两个层次：

| 回传内容 | 用途 |
| --- | --- |
| `ToolMessage` | 告诉主 Agent 本次 `task` 已经结束，并提供简短结果。 |
| 其他 `stateUpdate` 字段 | 将允许共享的状态合并回父 Agent，例如可合并的文件状态。 |

这条 `ToolMessage` 会回到主 Agent 的消息历史。

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

### 8.6 结构化响应与直接调用分支

[`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2291) 还包含两个容易忽略的分支：

1. 如果子 Agent 配置了 `responseFormat` 并返回 `structuredResponse`，`task` 会优先序列化结构化结果。
2. 如果调用上下文中没有 `config.toolCall.id`，框架无法构造与工具调用对应的 `ToolMessage`，会直接返回文本或 JSON 字符串。

正常由主 Agent 工具节点触发 `task` 时，会存在工具调用 ID，因此通常走 `Command + ToolMessage` 分支。

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
| `v2` 并行工具调度 | [`ReactAgent` 创建 `Send`](../../node_modules/langchain/dist/agents/ReactAgent.js#L370) |
| `v1` 并行工具执行 | [`ToolNode` 使用 `Promise.all()`](../../node_modules/langchain/dist/agents/nodes/ToolNode.js#L305) |
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

## 15. 深入理解：`createDeepAgent()` 到底自动组装了什么

前面的章节沿着一次 `task` 调用解释了运行过程。本节换一个角度，从初始化过程解释主 Agent 和子 Agent 分别具备哪些能力。

### 15.1 主 Agent 的默认中间件

原版只写了：

```js
return createDeepAgent({
  model: chatModel,
  systemPrompt: orchestratorPrompt,
  backend,
  memory: [path.join(projectDir, "AGENTS.md")],
  skills: ["/skills/"],
  subagents: [researcherSubAgent, editorSubAgent, analystSubAgent],
});
```

但是 [`createDeepAgent()`](../../node_modules/deepagents/dist/index.js#L8149) 会自动组装一组中间件：

| 中间件 | 是否默认挂载 | 提供的能力 |
| --- | --- | --- |
| `todoListMiddleware()` | 是 | `write_todos` 工具和 todo 状态。 |
| `createSkillsMiddleware()` | 配置 `skills` 后挂载 | 扫描 skill 元数据，并允许 Agent 按需读取 `SKILL.md`。 |
| `createFilesystemMiddleware()` | 是 | 文件读取、写入、编辑、列目录和搜索能力。 |
| `createSubAgentMiddleware()` | 是 | `task` 工具和子 Agent 使用说明。 |
| `createSummarizationMiddleware()` | 是 | 上下文过长时自动摘要。 |
| `createPatchToolCallsMiddleware()` | 是 | 修复部分不完整的工具调用与工具结果配对。 |
| `createMemoryMiddleware()` | 配置 `memory` 后挂载 | 加载工程级上下文并注入系统提示词。 |
| `humanInTheLoopMiddleware()` | 配置 `interruptOn` 后挂载 | 在指定工具执行前请求人工确认。 |

这说明：

> `createDeepAgent()` 不是另一套独立的 Agent 引擎。它是在基础 `createAgent()` 之上，为常见的长任务工作流预先组装一组中间件。

### 15.2 自定义子 Agent 也会获得一组基础中间件

框架在 [`normalizeSubagentSpec()`](../../node_modules/deepagents/dist/index.js#L8106) 中为自定义子 Agent 组装基础能力：

```js
const subagentMiddleware = [
  todoListMiddleware(),
  createFilesystemMiddleware({ backend, permissions: effectivePermissions }),
  createSummarizationMiddleware({ backend }),
  createPatchToolCallsMiddleware(),
  ...(input.skills ? [createSkillsMiddleware(...)] : []),
  ...(input.middleware ?? []),
];
```

因此，即使 `editorSubAgent` 没有显式配置 `tools`，它仍然可以读取草稿文件。原因不是 `editor` 自动继承了主 Agent 的全部工具，而是它单独挂载了文件系统中间件。

原版三个专用子 Agent 的能力可以整理为：

| 子 Agent | 自动获得 | 额外获得 | 没有自动获得 |
| --- | --- | --- | --- |
| `researcher` | todo、文件系统、摘要、工具调用修补 | `webSearch` | 主 Agent 的 skill、memory、其他业务工具 |
| `editor` | todo、文件系统、摘要、工具调用修补 | 无 | 主 Agent 的 skill、memory、`webSearch`、REPL |
| `analyst` | todo、文件系统、摘要、工具调用修补 | JavaScript REPL 中间件 | 主 Agent 的 skill、memory、`webSearch` |

### 15.3 配置继承矩阵

阅读子 Agent 配置时，最容易误以为“主 Agent 拥有的能力会全部自动传给子 Agent”。实际规则更细：

| 配置项 | `general-purpose` | 自定义子 Agent |
| --- | --- | --- |
| 模型 | 默认使用主 Agent 模型 | 未单独配置时使用主 Agent 模型 |
| `backend` | 使用主 Agent backend | 使用主 Agent backend |
| 文件权限 | 默认使用主 Agent 权限 | 未单独配置 `permissions` 时使用主 Agent 权限 |
| 文件系统中间件 | 自动挂载 | 自动挂载 |
| todo、摘要、工具调用修补 | 自动挂载 | 自动挂载 |
| 主 Agent 的额外 `tools` | 继承 | 不自动继承；应显式配置 `tools` |
| 主 Agent 的 `skills` | 继承 | 不自动继承；应显式配置 `skills` |
| 主 Agent 的 `memoryContents` | 不继承 | 不继承 |
| 主 Agent 自定义 `middleware` | 不直接继承 | 不直接继承；应显式配置子 Agent 的 `middleware` |

skill 继承差异在 [`createDeepAgent()`](../../node_modules/deepagents/dist/index.js#L8100) 的注释中明确说明：

```text
Custom subagents do NOT inherit skills from the main agent by default.
Only the general-purpose subagent inherits the main agent's skills.
```

memory 也需要单独理解：

- 主 Agent 的 `memoryContents` 会被默认过滤，不会从父状态泄漏给子 Agent。
- 当前自定义子 Agent 配置对象没有直接声明 `memory`。
- 如果某个自定义子 Agent 确实需要 memory，应明确挂载相应中间件，而不是假设它继承父 Agent 已加载的内容。

### 15.4 `task` 工具说明也会注入主 Agent 提示词

[`createSubAgentMiddleware()`](../../node_modules/deepagents/dist/index.js#L2329) 不只注册工具，还会在模型调用前追加一段系统提示词：

```js
wrapModelCall: async (request, handler) => {
  return handler({
    ...request,
    systemMessage: request.systemMessage.concat(
      new SystemMessage({ content: systemPrompt }),
    ),
  });
},
```

默认内容来自 [`TASK_SYSTEM_PROMPT`](../../node_modules/deepagents/dist/index.js#L2106)。它告诉主 Agent：

- 何时适合委派；
- 何时不应该委派；
- 子 Agent 是短生命周期执行器；
- 独立任务应尽量并行；
- 子 Agent 最终只返回一个结果。

因此，主 Agent 的委派决策同时受两类 Prompt 影响：

| Prompt | 来源 | 作用 |
| --- | --- | --- |
| 工程业务 Prompt | [`orchestratorPrompt`](../../src/agent.mjs#L106) | 规定本工程的调研、分析、起草、审阅和定稿流程。 |
| 框架通用 Prompt | [`TASK_SYSTEM_PROMPT`](../../node_modules/deepagents/dist/index.js#L2106) | 解释 `task` 的适用场景和生命周期。 |

## 16. `task` 不是 Agent 工厂，而是一次短生命周期执行

### 16.1 三个概念必须分开

| 概念 | 创建时间 | 存续时间 | 作用 |
| --- | --- | --- | --- |
| 子 Agent 配置对象 | 工程初始化前 | 长期存在于代码中 | 描述角色、Prompt、工具和中间件。 |
| 子 Agent 图或 `runnable` | `createDeepAgent()` 初始化时 | 可复用 | 表示一类可以执行任务的 Agent。 |
| 一次 `task` 调用 | 主 Agent 运行时 | 执行完成即结束 | 用一个新的任务描述调用某类子 Agent。 |

可以将 `researcher` 理解为“调研员岗位说明”，将一次 `task` 理解为“一张具体工单”：

```text
researcher 配置
  -> 定义调研员会什么、能用什么工具、如何停止

task({ subagent_type: "researcher", description: "..." })
  -> 创建一张只处理当前子主题的工单
```

### 16.2 可复用图不等于可继续对话

框架创建的子 Agent 图可以复用，但每次调用仍然是新的独立执行。默认 `task` 说明明确强调：

```text
Each agent invocation is stateless.
```

这意味着主 Agent 不能在子 Agent 完成后继续追问：

```text
你刚才漏了一点，再补充一下。
```

主 Agent 只能：

1. 自己整合已有结果；
2. 或重新发起一张内容完整的新 `task` 工单。

因此，`description` 必须足够完整，不能依赖子 Agent 猜测父 Agent 的隐含意图。

### 16.3 为什么子 Agent 看不到父 Agent 的完整对话

[`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2281) 使用 `getCurrentTaskInput()` 取得当前工具执行状态，过滤后覆盖 `messages`：

```js
const subagentState = filterStateForSubagent(getCurrentTaskInput());
subagentState.messages = [
  new HumanMessage({ content: description }),
];
```

覆盖而不是追加消息历史，解决了两个问题：

1. 父 Agent 的长对话不会占满子 Agent 上下文。
2. 子 Agent 只关注当前工单，不会被无关讨论干扰。

代价也很明确：

> 父 Agent 必须在 `description` 中写清楚输入、输出、路径、约束和完成条件。

## 17. 文件系统：隔离上下文，但共享成果

### 17.1 `/workspace/...` 是虚拟路径

原版在 [`agent.mjs`](../../src/agent.mjs#L174) 中创建：

```js
const backend = new FilesystemBackend({
  rootDir: projectDir,
  virtualMode: true,
});
```

当 [`FilesystemBackend.resolvePath()`](../../node_modules/deepagents/dist/index.js#L5162) 处理：

```text
/workspace/sources/findings_langgraph.md
```

它会映射到工程目录中的真实路径：

```text
<projectDir>/workspace/sources/findings_langgraph.md
```

`virtualMode: true` 还会拒绝路径穿越：

```js
if (vpath.includes("..") || vpath.startsWith("~")) {
  throw new Error("Path traversal not allowed");
}
```

因此，提示词中的 `/workspace/...` 不是操作系统根目录。

### 17.2 为什么父子 Agent 可以通过文件交换资料

父 Agent 与子 Agent 使用同一个 `backend`。即使消息历史隔离，它们仍然能访问同一个虚拟文件根目录：

```text
researcher
  -> write_file("/workspace/sources/findings_langgraph.md")

主 Agent
  -> read_file("/workspace/sources/findings_langgraph.md")
```

这是一种常见设计：

| 内容 | 推荐传递方式 |
| --- | --- |
| 简短完成状态 | `ToolMessage` |
| 完整调研材料 | 文件 |
| 需要并行合并的状态 | `Command.update` 中具有 reducer 的字段 |

### 17.3 `files` 状态为什么使用 reducer

文件系统中间件定义了共享状态 schema，见 [`FilesystemStateSchema`](../../node_modules/deepagents/dist/index.js#L1345)：

```js
const FilesystemStateSchema = new StateSchema({
  files: new ReducedValue(..., {
    reducer: fileDataReducer,
  }),
});
```

源码注释明确说明，该 reducer 用于合并并行子 Agent 的文件更新：

```text
Uses ReducedValue for files to allow concurrent updates from parallel subagents.
```

假设两个子 Agent 同时返回：

```js
// 子 Agent A
{ files: { "/sources/a.md": "..." } }

// 子 Agent B
{ files: { "/sources/b.md": "..." } }
```

`files` reducer 可以把它们合并为：

```js
{
  files: {
    "/sources/a.md": "...",
    "/sources/b.md": "...",
  },
}
```

需要区分两种 backend 行为：

| backend 类型 | 文件成果如何可见 |
| --- | --- |
| 当前工程的 `FilesystemBackend` | 文件直接写入本地工程目录，其他 Agent 可再次读取。 |
| 依赖状态保存文件的 backend | 文件更新还需要通过 `files` 状态和 reducer 合并。 |

无论 backend 如何实现，完整成果写入独立文件都比把大段内容塞进 `ToolMessage` 更适合并行调研。

## 18. 状态回写：为什么并行子 Agent 可能发生冲突

### 18.1 `filterStateForSubagent()` 同时用于输入和输出

默认过滤函数在两个方向都会使用：

```text
父 Agent 状态
  -> filterStateForSubagent()
  -> 子 Agent 输入

子 Agent 最终状态
  -> filterStateForSubagent()
  -> Command.update
  -> 父 Agent 状态
```

输入过滤发生在 [`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2281)。

输出过滤发生在 [`returnCommandWithStateUpdate()`](../../node_modules/deepagents/dist/index.js#L2196)。

### 18.2 reducer 字段与单值字段的差异

并行分支回写状态时，字段大体分为两类：

| 字段类型 | 示例 | 同一步收到两个更新时的行为 |
| --- | --- | --- |
| 带 reducer 的可合并字段 | `files` | reducer 合并更新。 |
| 单值字段 | 模型调用计数、工具调用计数、某个局部 session ID | 无法判断应保留哪个值，可能抛出 `InvalidUpdateError`。 |

例如，两个并行子 Agent 如果同时回写：

```js
// 子 Agent A
{ threadModelCallCount: 5 }

// 子 Agent B
{ threadModelCallCount: 4 }
```

父 Agent 的同一个状态通道在同一步收到了两个不同值。如果该通道是 `LastValue`，LangGraph 会拒绝合并。

### 18.3 当前工程的嵌套实验如何修复

混合流水线中的嵌套实验明确过滤以下局部字段：

```js
[
  "threadModelCallCount",
  "runModelCallCount",
  "threadToolCallCount",
  "runToolCallCount",
  "_summarizationEvent",
  "_summarizationSessionId",
]
```

定义位置：[`NESTED_RESEARCH_LOCAL_STATE_KEYS`](../../src/debug/hybrid-deep-pipeline.mjs#L55)。

它增加两层保护：

| 保护层 | 源码 | 作用 |
| --- | --- | --- |
| 子 Agent 执行前后 | [`createIsolatedNestedResearchSubagent()`](../../src/debug/hybrid-deep-pipeline.mjs#L353) | 防止子 Agent 继承父 Agent 已消耗的预算，也防止局部状态泄漏回父 Agent。 |
| `task` 返回父 Agent 前 | [`sanitizeNestedResearchTaskResult()`](../../src/debug/hybrid-deep-pipeline.mjs#L172) | 再次过滤 `Command.update`，作为最终校验。 |

核心原则：

> 父 Agent 和每个子 Agent 可以共享业务成果，但不应该共享各自的预算计数和摘要过程。

完整故障链路、错误示例和修复代码见：

- [混合流水线中的嵌套子 Agent：`InvalidUpdateError` 排查](./hybrid-nested-subagents.md#L362)

## 19. 四类约束：不要把 Prompt 当成硬限制

Agent 系统中经常同时存在多种约束。它们解决的问题不同。

### 19.1 Prompt 约束

例子：

```text
每份报告最多 2 个调研员。
每个调研员最多搜索 3 次。
编辑只调用一次。
```

优点：

- 编写简单；
- 适合表达业务策略；
- 模型可以根据上下文灵活判断。

缺点：

- 模型可能遗漏或违反；
- 无法作为严格安全边界；
- 长上下文摘要后，部分约束可能被弱化。

原版 [`orchestratorPrompt`](../../src/agent.mjs#L106) 主要采用这种方式。

### 19.2 Agent 循环终点

LangChain 的默认循环规则：

```text
模型仍然请求工具
  -> 继续执行

模型返回不带工具调用的文本
  -> 结束 invoke()
```

对应源码：[`ReactAgent`](../../node_modules/langchain/dist/agents/ReactAgent.js#L353)。

它保证 Agent 最终消息出现后循环能够退出，但不保证业务流程一定完整。例如，模型可能在尚未写文件时提前输出普通文本。

### 19.3 运行时预算

典型限制：

| 限制 | 作用 |
| --- | --- |
| `recursionLimit` | 限制 LangGraph 最多执行多少步。 |
| `modelCallLimitMiddleware()` | 限制模型调用次数。 |
| `toolCallLimitMiddleware()` | 限制全部工具或某类工具调用次数。 |
| 搜索工具自己的 `maxCalls` | 单独限制联网搜索次数。 |

这些限制主要控制成本和失控循环。它们通常不能保证业务动作一定发生。

例如，将 `task` 上限设置为 `2` 只能阻止第三次委派，不能保证前两次分别调用了正确的子 Agent。

### 19.4 业务 gate 和 guard

如果需要严格保证流程，应增加代码层校验。

当前工程中的例子：

| 需求 | 代码机制 |
| --- | --- |
| 只允许两个指定嵌套调研员 | [`NestedResearchTaskGuardMiddleware`](../../src/debug/hybrid-deep-pipeline.mjs#L305) |
| 每种嵌套调研员最多调用一次 | `usedTypes` 集合 |
| 最多调用两次 `task` | `toolCallLimitMiddleware({ toolName: "task", runLimit: 2 })` |
| 子 Agent 必须写出文件 | [`assertVirtualFile()` 调用](../../src/debug/hybrid-deep-pipeline.mjs#L634) |
| Editor 不能被跳过 | 外层 `StateGraph` 和 Editor gate |
| 限制 Agent 可访问路径 | 文件系统 `permissions` |

### 19.5 如何选择约束方式

| 目标 | 推荐机制 |
| --- | --- |
| 告诉模型理想工作方式 | Prompt |
| 防止无限循环或成本失控 | 递归上限和预算中间件 |
| 禁止危险路径或非法工具 | permissions、工具包装器、中间件 |
| 保证固定阶段必定发生 | 外层 `StateGraph` |
| 保证文件真实产生 | 节点结束后的文件 gate |
| 保证并行状态可合并 | reducer 或局部状态隔离 |

## 20. 如何写好一条 `task.description`

因为子 Agent 不继承父 Agent 完整对话，所以任务描述质量直接决定执行质量。

### 20.1 推荐结构

一条完整描述至少包含：

1. 子主题边界；
2. 输入材料或读取路径；
3. 允许使用的工具和次数；
4. 输出文件路径或返回格式；
5. 必须覆盖的要点；
6. 明确停止条件；
7. 不应该做的事情。

例如：

```js
task({
  subagent_type: "researcher",
  description: [
    "只调研 LangGraph 的工作流编排能力，不比较其他框架。",
    "最多调用 3 次 web_search，优先使用官方文档。",
    "整理核心概念、适用场景、限制和来源 URL。",
    "将完整结果写入 /workspace/sources/findings_langgraph.md。",
    "写入后用一句话确认完成并立即停止。",
  ].join("\n"),
});
```

### 20.2 常见错误

| 写法 | 问题 |
| --- | --- |
| “帮我继续调研一下。” | 子 Agent 不知道父 Agent 前面讨论了什么。 |
| “研究这个框架。” | 子主题边界不清，容易扩张。 |
| “完成后返回结果。” | 没有说明应写文件还是把完整内容塞进最终消息。 |
| “搜索一些资料。” | 没有搜索次数、来源偏好和停止条件。 |
| 两个并行任务写入同一路径 | 可能覆盖文件或产生难以判断的合并结果。 |

### 20.3 并行任务必须使用不同输出路径

正确：

```text
researcher A -> /workspace/sources/findings_langgraph.md
researcher B -> /workspace/sources/findings_autogen.md
```

不推荐：

```text
researcher A -> /workspace/sources/findings.md
researcher B -> /workspace/sources/findings.md
```

即使底层状态支持 reducer，并行编辑同一个业务文件仍然更容易发生覆盖和语义冲突。

## 21. 如何观察一次真实委派

### 21.1 CLI 已经打开子图流式输出

原版 CLI 使用：

```js
{
  streamMode: "updates",
  subgraphs: true,
  recursionLimit,
}
```

对应源码：[`cli.mjs`](../../src/cli.mjs#L222)。

`subgraphs: true` 表示流式更新包含子图命名空间。CLI 使用 [`stepLabel()`](../../src/cli.mjs#L73) 将类似：

```text
tools:<uuid>
```

转换为：

```text
subagent:<uuid>
```

因此，终端中可以区分：

```text
[主 Agent] model_request
[subagent:...] model_request
task done: ...
```

### 21.2 推荐观察顺序

运行：

```powershell
node src/cli.mjs "比较 LangGraph 与 AutoGen 的工作流编排能力"
```

观察：

1. 主 Agent 是否创建 `question.txt` 和 `research_plan.md`。
2. 主 Agent 是否在同一轮发出两个 `task`。
3. 是否出现两个不同的 `subagent:<uuid>` 命名空间。
4. 两个调研员是否各自写入独立 findings 文件。
5. `task done` 是否只显示简短完成摘要。
6. 主 Agent 是否读取 findings 文件后起草报告。
7. 是否调用一次 `editor` 并根据反馈修订。

### 21.3 LangSmith 中应该检查什么

如果启用了 LangSmith trace，重点查看：

| 观察点 | 说明 |
| --- | --- |
| 主 Agent 的 AIMessage | 是否一次生成多个 `task` 工具调用。 |
| `subagent_type` | 是否选择预期角色。 |
| `description` | 是否包含完整路径、边界和停止条件。 |
| 子 Agent 工具轨迹 | 是否存在重复搜索、重复写入或写入后继续操作。 |
| `Command.update` | 是否只回写允许共享的状态。 |
| 文件路径 | 并行分支是否使用独立输出。 |
| 总步数 | 是否接近递归上限。 |

## 22. 常见问题排查

### 22.1 非法 `subagent_type`

错误类似：

```text
Error: invoked agent of type web-research,
the only allowed types are ...
```

原因：

- 把 skill 名称误当成子 Agent 类型；
- 拼写错误；
- 尝试调用没有提前注册的动态角色。

检查：

1. [`orchestratorPrompt`](../../src/agent.mjs#L131) 中允许的类型；
2. `createDeepAgent({ subagents: [...] })` 中的注册；
3. 默认 `general-purpose` 是否被 profile 关闭。

### 22.2 子 Agent 完成了，但主 Agent 找不到完整材料

原因通常是：

- 子 Agent 只在最终文本中返回摘要，没有写文件；
- 输出路径与主 Agent 读取路径不一致；
- 子 Agent 写到了并行分支共用路径；
- 文件权限拒绝写入。

检查：

1. `task.description` 是否写明路径；
2. 子 Agent Prompt 是否要求 `write_file`；
3. CLI 中是否出现对应 `write_file` 日志；
4. 本地 `workspace/sources/` 是否真实存在文件。

### 22.3 子 Agent 写完文件后仍然继续搜索

原因：

- 当前原版主要依赖 Prompt 规定终点；
- JavaScript 没有在第一次 `write_file` 后强制终止；
- 模型没有严格遵循停止规则。

改进方向：

1. 收紧子 Agent Prompt；
2. 为搜索工具增加硬次数上限；
3. 使用工具调用预算；
4. 必要时增加自定义中间件，在写入目标文件后拒绝额外动作。

### 22.4 `ToolCallLimitExceededError`

含义：

> 某个 Agent 超过了工具调用预算。

不要把“全部工具预算”误解为“搜索预算”。读取 skill、读取文件、写入文件、更新 todo 都会消耗工具调用。

详细示例见：

- [混合流水线中的嵌套子 Agent：`ToolCallLimitExceededError` 排查](./hybrid-nested-subagents.md#L338)

### 22.5 `InvalidUpdateError`

含义：

> 多个并行分支尝试在同一个 LangGraph step 中更新不可合并的单值字段。

排查顺序：

1. 找出发生冲突的字段名；
2. 判断它是业务成果还是局部运行状态；
3. 业务成果需要 reducer；
4. 局部运行状态应该在父子边界过滤；
5. 不要仅仅为了绕过错误而把并行改成串行。

详细示例见第 18 节和：

- [混合流水线中的嵌套子 Agent：`InvalidUpdateError` 排查](./hybrid-nested-subagents.md#L362)

### 22.6 `GRAPH_RECURSION_LIMIT`

含义：

> Agent 图执行步数超过 `recursionLimit`。

它不等于模型调用次数。一次模型响应、一个工具节点、todo 中间件钩子、摘要中间件钩子都可能增加图步数。

排查：

1. 检查是否重复搜索、重复读取或重复写入；
2. 检查是否因为缺少完成条件而空转；
3. 检查摘要是否频繁触发；
4. 确认流程合理后，再小幅提高 `recursionLimit`。

## 23. 四套实现与离线案例如何对应不同学习目标

当前仓库不只有原版。建议将四套运行实现放在一起理解，再使用离线案例单独观察 `task` 基础设施。

| 实现 | 入口 | 编排方式 | 学习重点 |
| --- | --- | --- | --- |
| 原版自主 Agent | [`agent.mjs`](../../src/agent.mjs#L161) | 单个 `createDeepAgent()` 自主规划 | 理解 `task`、Prompt 驱动委派和共享文件。 |
| 基础受控流水线 | [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L447) | 外层 `StateGraph + createAgent()` | 理解固定阶段、Editor gate 和最小中间件。 |
| 混合流水线 | [`hybrid-deep-pipeline.mjs`](../../src/debug/hybrid-deep-pipeline.mjs#L718) | 外层 `StateGraph + createDeepAgent()` | 理解“固定流程 + 阶段内部自主性”。 |
| 嵌套子 Agent 实验 | [`nested-hybrid-deep-cli.mjs`](../../src/debug/nested-hybrid-deep-cli.mjs#L1) | research 阶段内部并行 `task` | 理解 guard、预算、并行状态冲突和隔离。 |
| 离线 `task` 机制案例 | [`subagent-task-flow-local-demo.mjs`](../../src/debug/subagent-task-flow-local-demo.mjs#L1) | 假模型生成两个真实 `task`，本地 runnable 执行任务 | 不调用外部 API，逐步观察本文介绍的底层机制。 |

推荐阅读：

1. 本文：先理解原版 `task` 链路。
2. [`create-deep-agent-vs-create-agent.md`](./create-deep-agent-vs-create-agent.md#L1)：理解默认中间件与手动组装。
3. [`hybrid-deep-agent-pipeline.md`](./hybrid-deep-agent-pipeline.md#L1)：理解固定外层图。
4. [`hybrid-nested-subagents.md`](./hybrid-nested-subagents.md#L1)：理解并行状态隔离。

## 24. 可离线运行的实际案例

前面的章节解释了底层源码，但如果直接运行原版 CLI，还会受到模型输出、联网搜索、API 配置和网络延迟影响。为了将注意力集中在 `task` 机制本身，工程增加了一个完全离线的最小案例：

- [`subagent-task-flow-local-demo.mjs`](../../src/debug/subagent-task-flow-local-demo.mjs#L1)

这个案例不调用 OpenAI API，不调用 Bocha 搜索 API，也不需要 `.env`。它使用仓库现有依赖，可以直接运行。

### 24.1 运行方式

在工程根目录执行：

```powershell
node src/debug/subagent-task-flow-local-demo.mjs
```

运行成功后，终端会输出四部分信息：

```text
=== 1. 父 Agent 生成的两个 task 已由框架执行 ===
- task_scenarios: scenario_researcher 已完成，结果写入 ...
- task_limits: limits_researcher 已完成，结果写入 ...

=== 2. 子 Agent 收到隔离后的任务上下文 ===
- limits_researcher
  状态字段: ...
  唯一 HumanMessage: ...
  可读取共享文件: ...

=== 3. 两个 task 是否并行 ===
- 是

=== 4. files reducer 合并后的结果 ===
...

离线案例执行成功。
```

脚本内部还有断言。如果委派数量、并行关系、上下文隔离或文件合并不符合预期，Node.js 会直接抛出错误并返回非零退出码。

### 24.2 案例要解决的问题

案例模拟一个很小的调研任务：

```text
用户问题：
  node:test 是否适合小型 Node.js CLI 项目？

父 Agent：
  -> 委派 scenario_researcher 整理适用场景
  -> 委派 limits_researcher 整理限制

两个子 Agent：
  -> 读取同一份 question.md
  -> 分别写入独立 findings

父 Agent：
  -> 收到两个 task ToolMessage
  -> 得到合并后的三个文件
```

三个虚拟路径定义在 [`subagent-task-flow-local-demo.mjs`](../../src/debug/subagent-task-flow-local-demo.mjs#L12)：

```js
const QUESTION_PATH = "/workspace/sources/question.md";
const SCENARIO_PATH = "/workspace/sources/findings_scenarios.md";
const LIMITS_PATH = "/workspace/sources/findings_limits.md";
```

两个 findings 使用不同路径。这对应第 20.3 节的规则：

> 并行任务应该写入不同文件，避免覆盖和语义冲突。

### 24.3 哪些部分是真实框架逻辑

这个案例不是手写一个假的 `task()` 函数。以下链路都使用仓库实际安装的 `deepagents`、LangChain 和 LangGraph：

| 机制 | 是否真实执行 | 对应代码 |
| --- | --- | --- |
| `createDeepAgent()` 组装主 Agent | 是 | [`createDeepAgent({...})`](../../src/debug/subagent-task-flow-local-demo.mjs#L144) |
| 注册两个 `runnable` 子 Agent | 是 | [`subagents`](../../src/debug/subagent-task-flow-local-demo.mjs#L147) |
| 主 Agent 输出两个 `task` 工具调用 | 是 | [`toolCalls`](../../src/debug/subagent-task-flow-local-demo.mjs#L112) |
| 根据 `subagent_type` 选择子 Agent | 是 | `deepagents` 的 [`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2274) |
| 过滤父 Agent 状态并替换 `messages` | 是 | `deepagents` 的 [`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2281) |
| 两个工具调用并行执行 | 是 | LangChain `v2` 的 [`Send`](../../node_modules/langchain/dist/agents/ReactAgent.js#L370) |
| 子 Agent 读取和写入虚拟文件状态 | 是 | [`StateBackend`](../../src/debug/subagent-task-flow-local-demo.mjs#L44) |
| 子 Agent 结果包装为 `Command.update` | 是 | `deepagents` 的 [`returnCommandWithStateUpdate()`](../../node_modules/deepagents/dist/index.js#L2196) |
| 两个文件更新通过 reducer 合并 | 是 | `deepagents` 的 [`FilesystemStateSchema`](../../node_modules/deepagents/dist/index.js#L1352) |
| 父 Agent 收到两个 `task ToolMessage` | 是 | [`taskMessages`](../../src/debug/subagent-task-flow-local-demo.mjs#L167) |

### 24.4 哪些部分为了离线测试进行了替换

真实 CLI 中，父 Agent 和子 Agent 都会调用聊天模型。父 Agent 根据 Prompt 自行判断如何拆分任务，子 Agent 根据任务描述自行搜索、整理并写入文件。

离线案例刻意替换了两个不稳定部分：

| 真实运行 | 离线案例 | 原因 |
| --- | --- | --- |
| 父 Agent 调用 OpenAI 兼容模型，自主决定是否生成 `task`。 | 使用 LangChain 自带的 [`FakeToolCallingModel`](../../src/debug/subagent-task-flow-local-demo.mjs#L112)，固定生成两个 `task`。 | 不需要 API Key，输出可重复。 |
| 子 Agent 内部再次运行“模型 -> 工具 -> 模型”循环。 | 使用两个本地 [`RunnableLambda`](../../src/debug/subagent-task-flow-local-demo.mjs#L42)，直接读取问题并返回 findings 更新。 | 不联网，不产生额外 token，便于逐步观察父子边界。 |

因此，案例的定位是：

> 使用真实的委派基础设施，替换外部模型和搜索过程。

它适合学习 `task` 如何注册、选择、隔离、并行和回写。它不用于评估模型的规划质量，也不用于评估搜索结果质量。

### 24.5 第一步：使用 `StateBackend` 创建共享问题文件

[`createInitialFiles()`](../../src/debug/subagent-task-flow-local-demo.mjs#L22) 创建一个临时的状态后端：

```js
const backend = new StateBackend({ state: { files: {} } });
const result = backend.write(
  QUESTION_PATH,
  "# 问题\n\nnode:test 是否适合小型 Node.js CLI 项目？\n",
);
```

`StateBackend` 与原版使用的 `FilesystemBackend` 都实现文件后端协议，但存储位置不同：

| backend | 文件存储位置 | 适用场景 |
| --- | --- | --- |
| 原版 `FilesystemBackend` | 本地工程目录 | 真实调研报告，需要运行结束后继续查看文件。 |
| 案例 `StateBackend` | LangGraph 当前执行状态中的 `files` 字段 | 离线演示，不产生磁盘文件，不需要清理。 |

本案例通过 `new StateBackend({ state })` 将当前状态传给 backend。在这种模式下，`StateBackend.write()` 不会直接修改 LangGraph 状态，而是返回：

```js
{
  filesUpdate: {
    "/workspace/sources/question.md": {
      content: "...",
      ...
    },
  },
}
```

这对应框架注释中强调的原则：

```text
LangGraph state must be updated via Command objects, not direct mutation.
```

### 24.6 第二步：注册两个本地子 Agent

[`createLocalResearcher()`](../../src/debug/subagent-task-flow-local-demo.mjs#L32) 返回一种带 `runnable` 的子 Agent 配置：

```js
return {
  name,
  description,
  runnable: RunnableLambda.from(async (state) => {
    ...
  }),
};
```

这对应第 3.3 节介绍的已编译子 Agent 形式。`deepagents` 不会再为它调用 `createAgent()`，而是直接保存并调用这个 `runnable`。

两个角色分别注册为：

```js
scenario_researcher
limits_researcher
```

定义位置：

- [`scenarioResearcher`](../../src/debug/subagent-task-flow-local-demo.mjs#L77)
- [`limitsResearcher`](../../src/debug/subagent-task-flow-local-demo.mjs#L91)

每个子 Agent 都会：

1. 使用 `StateBackend` 读取共享 `question.md`；
2. 检查自己只收到一条任务消息；
3. 检查父 Agent 的 todo 没有泄漏；
4. 等待一小段时间，便于验证两个执行区间是否重叠；
5. 将结果写入自己的 findings 路径；
6. 返回文件更新和一句完成说明。

核心返回值位于 [`subagent-task-flow-local-demo.mjs`](../../src/debug/subagent-task-flow-local-demo.mjs#L67)：

```js
return {
  files: writeResult.filesUpdate,
  messages: [
    new AIMessage(`${name} 已完成，结果写入 ${outputPath}`),
  ],
};
```

### 24.7 第三步：让假模型生成两个真实 `task`

[`FakeToolCallingModel`](../../src/debug/subagent-task-flow-local-demo.mjs#L112) 的第一轮回复被固定为两个工具调用：

```js
[
  {
    name: "task",
    id: "task_scenarios",
    args: {
      subagent_type: "scenario_researcher",
      description: "...",
    },
  },
  {
    name: "task",
    id: "task_limits",
    args: {
      subagent_type: "limits_researcher",
      description: "...",
    },
  },
]
```

第二轮回复为空工具调用列表：

```js
[]
```

这模拟了真实主 Agent 的两轮行为：

```text
第一轮模型回复：
  我需要并行委派两个独立子任务。
  -> 输出两个 task tool_calls

第二轮模型回复：
  两个 task 已经完成。
  -> 不再请求工具
  -> 主 Agent 循环结束
```

注意：

> 假模型只负责确定工具调用序列。真正执行 `task` 的仍然是 `createDeepAgent()` 自动注册的内置工具。

### 24.8 第四步：父 Agent 状态进入 `task`

案例调用 [`agent.invoke()`](../../src/debug/subagent-task-flow-local-demo.mjs#L151) 时，传入：

```js
{
  messages: [new HumanMessage(...)],
  files: createInitialFiles(),
  todos: [
    {
      content: "父 Agent 的规划不会传给子 Agent",
      status: "in_progress",
    },
  ],
  parentMarker: "未列入默认排除列表的自定义状态会传给子 Agent",
}
```

这里故意增加两类父状态：

| 字段 | 预期行为 | 原因 |
| --- | --- | --- |
| `todos` | 不传给子 Agent | 位于 [`EXCLUDED_STATE_KEYS`](../../node_modules/deepagents/dist/index.js#L1968)。 |
| `parentMarker` | 会传给子 Agent | 它是案例自定义字段，没有位于默认排除列表。 |

`parentMarker` 通过一个最小中间件注册到父 Agent state schema：

```js
const parentStateMiddleware = createMiddleware({
  name: "ParentStateDemoMiddleware",
  stateSchema: z.object({
    parentMarker: z.string().default(""),
  }),
});
```

对应位置：[`subagent-task-flow-local-demo.mjs`](../../src/debug/subagent-task-flow-local-demo.mjs#L105)。

这一步用于验证第 6.4 节的重要提醒：

> 默认过滤列表只覆盖 `deepagents` 已知的通用字段，不会自动识别业务代码后来新增的所有局部状态。

### 24.9 第五步：观察子 Agent 收到的隔离上下文

运行案例后，两个子 Agent 都会打印类似字段：

```text
状态字段:
  _summarizationEvent,
  _summarizationSessionId,
  files,
  jumpTo,
  lg_tool_call,
  messages,
  parentMarker
```

其中最重要的是：

| 字段 | 是否存在 | 说明 |
| --- | --- | --- |
| `messages` | 是 | 但只包含当前 `task.description` 转换而来的唯一 `HumanMessage`。 |
| `files` | 是 | 子 Agent 可以读取共享问题文件。 |
| `todos` | 否 | 已被默认过滤。 |
| `parentMarker` | 是 | 自定义字段不会被自动过滤。 |
| `_summarizationEvent` | 是 | 默认过滤列表没有覆盖它。 |
| `_summarizationSessionId` | 是 | 默认过滤列表没有覆盖它。 |
| `lg_tool_call` | 是 | LangChain `v2` 使用 `Send` 分发单个工具调用时加入的内部字段。 |

这说明“父子上下文隔离”不是：

```text
删除所有状态，只保留 description。
```

而是：

```text
过滤已知的不应继承字段；
覆盖 messages 为当前 description；
保留仍然需要共享或尚未被识别为局部状态的字段。
```

这也是嵌套流水线为什么还要增加自定义局部状态过滤的原因，见第 18 节。

### 24.10 第六步：验证两个 `task` 确实并行

两个子 Agent 分别等待：

```js
scenario_researcher -> 120 ms
limits_researcher   -> 80 ms
```

对应位置：

- [`scenarioResearcher.delayMs`](../../src/debug/subagent-task-flow-local-demo.mjs#L88)
- [`limitsResearcher.delayMs`](../../src/debug/subagent-task-flow-local-demo.mjs#L102)

执行结束后，案例比较两个执行区间：

```js
const ranInParallel = Math.max(...starts) < Math.min(...finishes);
```

对应位置：[`subagent-task-flow-local-demo.mjs`](../../src/debug/subagent-task-flow-local-demo.mjs#L172)。

判断逻辑：

```text
最晚开始的任务
  早于
最早结束的任务

=> 两个任务的执行区间发生重叠
=> 两个 task 确实并行运行
```

如果框架改成串行执行，断言会失败：

```js
assert.equal(ranInParallel, true);
```

### 24.11 第七步：观察 `ToolMessage` 和文件合并

子 Agent 返回后，`deepagents` 会调用 [`returnCommandWithStateUpdate()`](../../node_modules/deepagents/dist/index.js#L2196)，将结果包装为：

```text
Command.update
  -> files: 当前子 Agent 的 findings 更新
  -> messages: 一条 name = "task" 的 ToolMessage
```

两个并行 `task` 分别返回：

```text
/workspace/sources/findings_scenarios.md
/workspace/sources/findings_limits.md
```

文件系统中间件的 reducer 将两个更新与原始问题文件合并。最终 `result.files` 中同时存在：

```text
/workspace/sources/question.md
/workspace/sources/findings_scenarios.md
/workspace/sources/findings_limits.md
```

案例使用断言检查两个 findings：

```js
assert.equal(typeof result.files[SCENARIO_PATH]?.content, "string");
assert.equal(typeof result.files[LIMITS_PATH]?.content, "string");
```

对应位置：[`subagent-task-flow-local-demo.mjs`](../../src/debug/subagent-task-flow-local-demo.mjs#L177)。

### 24.12 案例与原版 CLI 的对应关系

| 离线案例 | 原版 CLI |
| --- | --- |
| `FakeToolCallingModel` 固定发出两个 `task` | OpenAI 兼容模型根据 Prompt 决定是否委派 |
| `scenario_researcher` 本地 runnable | 原版 `researcherSubAgent` 创建的子 Agent 图 |
| `limits_researcher` 本地 runnable | 第二次独立 `researcher` 调用 |
| `StateBackend` 中的 `question.md` | 磁盘中的 `/workspace/sources/question.txt` |
| `StateBackend` 中的两个 findings | 磁盘中的 `/workspace/sources/findings_*.md` |
| 控制台打印 `task ToolMessage` | CLI 中的 `task done: ...` |
| 断言执行区间重叠 | LangSmith 中观察两个并行子任务 |

### 24.13 推荐阅读案例源码的顺序

按下面顺序打开源码：

1. [`FakeToolCallingModel`](../../src/debug/subagent-task-flow-local-demo.mjs#L112)：先看父 Agent 会生成哪两个 `task`。
2. [`createDeepAgent({...})`](../../src/debug/subagent-task-flow-local-demo.mjs#L144)：确认两个子 Agent 如何注册。
3. [`agent.invoke({...})`](../../src/debug/subagent-task-flow-local-demo.mjs#L151)：查看父 Agent 初始状态。
4. [`createLocalResearcher()`](../../src/debug/subagent-task-flow-local-demo.mjs#L32)：查看子 Agent 如何读取共享文件和写入独立 findings。
5. [`ranInParallel`](../../src/debug/subagent-task-flow-local-demo.mjs#L172)：查看并行验证。
6. [`taskMessages`](../../src/debug/subagent-task-flow-local-demo.mjs#L167)：查看回传给父 Agent 的简短完成说明。
7. 最后重新对照 [`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2263) 和 [`returnCommandWithStateUpdate()`](../../node_modules/deepagents/dist/index.js#L2196)。

## 25. 推荐动手实验

本节中的离线 smoke test 不需要模型或搜索 API。其他真实运行示例需要提前配置：

```text
OPENAI_API_KEY
BOCHA_API_KEY
```

如需切换模型，还可以配置：

```text
OPENAI_MODEL
OPENAI_BASE_URL
```

### 25.1 实验一：运行离线 `task` 机制案例

运行：

```powershell
node src/debug/subagent-task-flow-local-demo.mjs
```

目标：

- 不配置任何 API Key，先观察真实 `task` 基础设施；
- 确认父 Agent 的 todo 被过滤；
- 确认自定义父状态仍然会传入子 Agent；
- 确认两个子 Agent 并行执行；
- 确认两个 findings 通过 reducer 合并。

### 25.2 实验二：观察一次专用调研员委派

运行：

```powershell
node src/cli.mjs "调研 LangGraph 的核心能力，输出简短报告"
```

目标：

- 找到一次 `researcher` 调用；
- 对照 `task.description` 和 findings 文件；
- 确认 `ToolMessage` 只是简短摘要。

### 25.3 实验三：观察两个并行调研员

运行：

```powershell
node src/cli.mjs "比较 LangGraph 和 AutoGen 的架构特点"
```

目标：

- 检查主 Agent 是否在同一条 AIMessage 中生成两个 `task`；
- 检查两个子 Agent 是否写入不同文件；
- 比较并行和串行 trace。

### 25.4 实验四：观察固定流水线

运行离线测试：

```powershell
node src/debug/hybrid-deep-pipeline-smoke-test.mjs
```

目标：

- 验证外层四阶段；
- 验证 Editor gate；
- 验证嵌套状态过滤；
- 不调用模型 API 和搜索 API。

### 25.5 实验五：观察嵌套并行子 Agent

运行：

```powershell
node src/debug/nested-hybrid-deep-cli.mjs
```

目标：

- 在 research 阶段看到两个专用子 Agent；
- 确认每个子 Agent 最多搜索一次；
- 确认协调员读取两个 findings 后再合并；
- 在 LangSmith 中检查父子状态没有泄漏。

## 26. 进阶源码导航

### `deepagents`

| 主题 | 源码 |
| --- | --- |
| 默认排除的父子状态 | [`EXCLUDED_STATE_KEYS`](../../node_modules/deepagents/dist/index.js#L1968) |
| 动态生成 `task` 工具描述 | [`getTaskToolDescription()`](../../node_modules/deepagents/dist/index.js#L1980) |
| 默认 `task` 系统提示词 | [`TASK_SYSTEM_PROMPT`](../../node_modules/deepagents/dist/index.js#L2106) |
| 默认通用子 Agent | [`GENERAL_PURPOSE_SUBAGENT`](../../node_modules/deepagents/dist/index.js#L2172) |
| 父子状态过滤 | [`filterStateForSubagent()`](../../node_modules/deepagents/dist/index.js#L2180) |
| 子 Agent 结果包装为 `Command` | [`returnCommandWithStateUpdate()`](../../node_modules/deepagents/dist/index.js#L2196) |
| 子 Agent 图初始化 | [`getSubagents()`](../../node_modules/deepagents/dist/index.js#L2220) |
| `task` 工具实现 | [`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2263) |
| 子 Agent 中间件 | [`createSubAgentMiddleware()`](../../node_modules/deepagents/dist/index.js#L2315) |
| 并行文件更新 reducer | [`FilesystemStateSchema`](../../node_modules/deepagents/dist/index.js#L1345) |
| 虚拟路径解析 | [`FilesystemBackend.resolvePath()`](../../node_modules/deepagents/dist/index.js#L5162) |
| 自定义子 Agent 标准化 | [`normalizeSubagentSpec()`](../../node_modules/deepagents/dist/index.js#L8106) |
| 默认 `general-purpose` 注入 | [`inlineSubagents.unshift(...)`](../../node_modules/deepagents/dist/index.js#L8132) |
| 主 Agent 默认中间件组装 | [`createDeepAgent()`](../../node_modules/deepagents/dist/index.js#L8149) |

### LangChain 与 LangGraph

| 主题 | 源码 |
| --- | --- |
| 默认工具行为为 `v2` | [`ReactAgent`](../../node_modules/langchain/dist/agents/ReactAgent.js#L46) |
| 没有工具调用时退出 Agent 循环 | [`createModelRouter()`](../../node_modules/langchain/dist/agents/ReactAgent.js#L353) |
| `v2` 为每个工具调用创建 `Send` | [`createModelRouter()`](../../node_modules/langchain/dist/agents/ReactAgent.js#L370) |
| `v1` 在单个 `ToolNode` 中用 `Promise.all()` | [`ToolNode.run()`](../../node_modules/langchain/dist/agents/nodes/ToolNode.js#L305) |

### 当前工程

| 主题 | 源码 |
| --- | --- |
| 原版主 Agent 与专用子 Agent | [`agent.mjs`](../../src/agent.mjs#L25) |
| CLI 子图流式展示 | [`cli.mjs`](../../src/cli.mjs#L73) |
| 离线 `task` 机制案例 | [`subagent-task-flow-local-demo.mjs`](../../src/debug/subagent-task-flow-local-demo.mjs#L1) |
| 混合流水线阶段 Deep Agent | [`createPhaseDeepAgent()`](../../src/debug/hybrid-deep-pipeline.mjs#L259) |
| 嵌套 `task` guard | [`createNestedResearchTaskGuard()`](../../src/debug/hybrid-deep-pipeline.mjs#L305) |
| 嵌套子 Agent 状态隔离 | [`createIsolatedNestedResearchSubagent()`](../../src/debug/hybrid-deep-pipeline.mjs#L353) |
| 嵌套子 Agent 注册 | [`createNestedResearchSubagents()`](../../src/debug/hybrid-deep-pipeline.mjs#L410) |
| 嵌套模式离线测试 | [`testNestedResearchLocalStateIsolation()`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L236) |

## 27. 最终心智模型

可以用下面这张图记住整个机制：

```text
初始化阶段
  createDeepAgent()
    -> 为主 Agent 组装 todo、filesystem、task、summary、skill、memory
    -> 注入默认 general-purpose 子 Agent
    -> 将自定义子 Agent 标准化为可复用 runnable
    -> 为主 Agent 注册统一 task 工具

运行阶段
  用户问题
    -> 主 Agent 模型规划
    -> 生成一个或多个 task({ subagent_type, description })
    -> LangGraph 调度独立工具调用
    -> task 根据 subagent_type 选择已注册 runnable
    -> 过滤父 Agent 状态
    -> 用 description 创建新的 HumanMessage
    -> 子 Agent 独立循环：模型 -> 工具 -> 模型
    -> 子 Agent 返回不带工具调用的最终消息
    -> 过滤子 Agent 状态
    -> 包装为 Command.update + task ToolMessage
    -> 父 Agent 合并允许共享的状态
    -> 父 Agent 读取成果文件并继续工作
```

最重要的边界：

| 边界 | 应该记住什么 |
| --- | --- |
| 配置与执行 | 注册一种子 Agent 类型，不等于已经启动一次任务。 |
| Prompt 与硬限制 | Prompt 表达策略；中间件、gate 和图结构提供强制保证。 |
| 隔离与共享 | 消息历史应隔离；业务成果应通过文件或可合并状态共享。 |
| 并行与状态 | 并行任务要写不同文件；局部计数状态不能回写到父 Agent。 |
| 简短回执与完整材料 | `ToolMessage` 适合返回摘要；完整材料适合写入文件。 |
