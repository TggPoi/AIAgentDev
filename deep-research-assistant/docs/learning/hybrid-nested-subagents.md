# 混合流水线中的嵌套子 Agent

## 1. 测试目标

默认混合流水线禁止阶段内部调用 `task`，避免调试 trace 重新膨胀。

为了单独学习子 Agent 协同，工程新增了一个独立入口：

- CLI：[`nested-hybrid-deep-cli.mjs`](../../src/debug/nested-hybrid-deep-cli.mjs#L1)
- 流水线：[`hybrid-deep-pipeline.mjs`](../../src/debug/hybrid-deep-pipeline.mjs#L1)
- 离线验证：[`hybrid-deep-pipeline-smoke-test.mjs`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L1)

该入口不会改变默认的 [`hybrid-deep-cli.mjs`](../../src/debug/hybrid-deep-cli.mjs#L1)。

## 2. 真实运行方式

执行：

```powershell
node src/debug/nested-hybrid-deep-cli.mjs
```

也可以传入一个小型问题：

```powershell
node src/debug/nested-hybrid-deep-cli.mjs "调研 node:test 对小型 CLI 项目的价值、限制和采用建议"
```

该命令会调用模型 API 和搜索 API。测试前确认 `.env` 中已经配置：

```text
OPENAI_API_KEY
BOCHA_API_KEY
```

如需覆盖模型：

```powershell
$env:HYBRID_PIPELINE_MODEL = "gpt-4o"
node src/debug/nested-hybrid-deep-cli.mjs
```

## 3. 执行结构

外层流程仍然固定：

```text
StateGraph
  -> research
  -> draft
  -> editor_review
  -> finalize
```

只有 `research` 阶段内部增加了嵌套委派：

```text
research coordinator Deep Agent
  -> task({ subagent_type: "scenario_researcher", ... })
  -> task({ subagent_type: "limits_researcher", ... })
  -> 读取两个子 Agent 文件
  -> 合并为 findings_node_test.md
```

两个 `task` 相互独立。Prompt 要求协调员在同一轮模型回复中发出两个调用，使 LangChain 可以并行执行。

## 4. 两个子 Agent 在哪里定义

嵌套子 Agent 定义在 [`createNestedResearchSubagents()`](../../src/debug/hybrid-deep-pipeline.mjs#L410)：

| 子 Agent | 任务 | 搜索上限 |
| --- | --- | --- |
| `scenario_researcher` | 调研适用场景 | 1 次 |
| `limits_researcher` | 调研限制和采用建议 | 1 次 |

两个子 Agent 各自拥有一个独立的 `compact_web_search` 实例：

```js
tools: [createCompactWebSearch({ maxCalls: 1 })]
```

因此，每个子 Agent 最多搜索一次，合计最多两次。

每个子 Agent 还具有独立的整体预算：

| 预算 | 上限 | 说明 |
| --- | --- | --- |
| 模型调用次数 | `7` | 允许完成读取、搜索、写入和结束确认。 |
| 全部工具调用次数 | `8` | 包括 `read_file`、`compact_web_search`、`write_file` 和可选 todo 更新。 |
| 搜索次数 | `1` | 由独立的 `compact_web_search` 实例硬性限制。 |

整体工具预算不能设置得过紧。Deep Agent 除了搜索，还需要读取 skill、读取问题文件和写入 findings；如果模型使用 todo，还会产生额外工具调用。搜索成本仍然由单独的搜索上限控制。

两个子 Agent 由 [`createIsolatedNestedResearchSubagent()`](../../src/debug/hybrid-deep-pipeline.mjs#L353) 预先创建为独立的 `createAgent()`。**它们仍然拥有 filesystem、skill、todo、摘要和预算中间件，但会隔离父子 Agent 的局部计数状态。第 12 节解释这样设计的原因。**

## 5. 协调员如何获得 `task`

[`createHybridDeepPhaseAgents()`](../../src/debug/hybrid-deep-pipeline.mjs#L448) 在嵌套模式下创建 research 协调员：

```js
createPhaseDeepAgent({
  name: "hybrid_research_coordinator",
  subagents: createNestedResearchSubagents({ model, backend }),
  maxTaskCalls: 2,
  ...
})
```

[`createPhaseDeepAgent()`](../../src/debug/hybrid-deep-pipeline.mjs#L259) 最终调用 `createDeepAgent()`，并传入 `subagents`：

```js
return createDeepAgent({
  ...
  subagents,
})
```

`createDeepAgent()` 会自动添加 `createSubAgentMiddleware()`。该中间件向协调员提供 `task` 工具。

### 5.1 `subagents` 和 `task` 分别负责什么

`subagents` 和 `task` 解决的是两个不同阶段的问题：

| 名称 | 所属阶段 | 作用 |
| --- | --- | --- |
| `subagents` 参数 | 初始化阶段 | 注册主 Agent 可以使用哪些子 Agent 类型，以及每种类型的模型、工具、Prompt、skill 和预算。 |
| `task` 工具 | 运行阶段 | 根据 `subagent_type` 选择一个已经注册的子 Agent，并启动一次临时执行实例。 |

当前代码在初始化阶段注册：

```text
scenario_researcher
limits_researcher
```

协调员真正开始调研后，才会调用：

```js
task({
  subagent_type: "scenario_researcher",
  description: "调研适用场景，并将结果写入指定文件",
})

task({
  subagent_type: "limits_researcher",
  description: "调研限制和采用建议，并将结果写入指定文件",
})
```

`task` 工具会根据 `subagent_type` 查找已经注册的 runnable，再调用它的 `invoke()`。对应逻辑位于 [`createTaskTool()`](../../node_modules/deepagents/dist/index.js#L2263)。

因此，`task` 不是 Agent 工厂。它不会在运行时凭空定义新的 Agent 类型，只会启动已经注册好的 Agent：

```text
subagents
负责注册：有哪些子 Agent 可以使用

task
负责调度：这一次让哪个已注册的子 Agent 执行什么任务
```

### 5.2 为什么主 Agent 仍然需要调用 `task`

`subagents` 是 JavaScript 运行时配置。大语言模型不能直接调用：

```js
scenarioResearcherRunnable.invoke(...)
```

模型只能调用暴露给它的工具。`createDeepAgent()` 将已注册子 Agent 包装为统一的 `task` 工具，让模型通过参数选择目标：

```text
协调员模型
    ↓ 调用 task({ subagent_type, description })
task 工具
    ↓ 查找预先注册的 runnable
子 Agent 临时执行实例
    ↓ 返回结果
协调员模型
```

如果不希望模型调用 `task`，也可以在外层 LangGraph 节点中手动调用子 Agent 的 `invoke()`。但是，那会变成由 JavaScript 固定控制调用顺序的显式编排，不再是由协调员模型动态委派任务。

## 6. 为什么不是只修改 `maxTaskCalls`

只将 `maxTaskCalls` 从 `0` 改为 `2` 不够严格。

原因是 `createDeepAgent()` 默认还可能提供 `general-purpose` 子 Agent。模型也可能重复调用同一种调研员。

所以嵌套模式还增加了 [`createNestedResearchTaskGuard()`](../../src/debug/hybrid-deep-pipeline.mjs#L305)：

```js
if (!allowedTypes.has(subagentType)) {
  throw new Error(`嵌套调研不允许调用子 Agent：${subagentType}`);
}
if (usedTypes.has(subagentType)) {
  throw new Error(`嵌套调研子 Agent 只能调用一次：${subagentType}`);
}
```

代码层限制：

| 限制 | 机制 |
| --- | --- |
| 最多两次 `task` | `toolCallLimitMiddleware({ toolName: "task", runLimit: 2 })` |
| 只允许两个专用子 Agent | `NestedResearchTaskGuardMiddleware` |
| 每种子 Agent 最多调用一次 | `NestedResearchTaskGuardMiddleware` |
| 每个子 Agent 最多搜索一次 | 独立的 `compact_web_search` 实例 |

### 6.1 不配置自定义 `subagents` 会发生什么

`createDeepAgent()` 通常会自动注册默认子 Agent：

```text
general-purpose
```

对应逻辑位于 [`GENERAL_PURPOSE_SUBAGENT`](../../node_modules/deepagents/dist/index.js#L2172) 和默认注册位置 [`inlineSubagents.unshift(generalPurposeSpec)`](../../node_modules/deepagents/dist/index.js#L8143)。

如果 harness profile 显式设置 `generalPurposeSubagent.enabled === false`，默认 `general-purpose` 不会注册。所以下面的行为是默认情况，不是不可关闭的规则。

因此，即使没有显式传入自定义 `subagents`，Prompt 仍然可以要求主 Agent 并行调用两次：

```js
task({
  subagent_type: "general-purpose",
  description: "调研适用场景",
})

task({
  subagent_type: "general-purpose",
  description: "调研限制和采用建议",
})
```

这会启动两个独立的 `general-purpose` 临时执行实例。但是 Prompt 不能动态创建新的子 Agent 类型。没有预先注册时，下面的调用会失败：

```js
task({
  subagent_type: "scenario_researcher",
  description: "...",
})
```

因为 `scenario_researcher` 不在 `task` 工具允许的类型列表中。

两种方案的区别如下：

| 方案 | 优点 | 缺点 |
| --- | --- | --- |
| 两次调用默认 `general-purpose` | 配置简单，适合快速验证并行委派。 | 两个实例的职责差异主要依赖 `description`，约束较弱。 |
| 注册两个专用子 Agent | 可以分别限定 Prompt、skill、工具和预算，调试结果更稳定。 | 配置更多，还需要处理局部状态隔离。 |

本工程使用专用子 Agent，是为了让学习实验更容易观察和复现，而不是因为 `task` 无法重复调用 `general-purpose`。

## 7. 子 Agent 如何传递结果

两个子 Agent 分别写入：

```text
sources/findings_scenarios.md
sources/findings_limits.md
```

协调员读取这两个文件，再写入：

```text
sources/findings_node_test.md
```

对应路径在 [`createHybridRunPaths()`](../../src/debug/hybrid-deep-pipeline.mjs#L135) 中创建。

外层 research 节点还会检查三个文件是否存在：

```js
assertVirtualFile(state.scenarioFindingsPath, "research:scenario_researcher");
assertVirtualFile(state.limitsFindingsPath, "research:limits_researcher");
assertVirtualFile(state.findingsPath, "research");
```

对应代码位于 [`researchNode()`](../../src/debug/hybrid-deep-pipeline.mjs#L615)。

如果任意子 Agent 没有写入结果，流水线不会进入 draft。

## 8. 专用 skill

协调员使用：

- [`nested-research-coordinator`](../../skills-hybrid/research-coordinator/nested-research-coordinator/SKILL.md#L1)

两个子 Agent 使用：

- [`compact-subtopic-research`](../../skills-hybrid/research-subagent/compact-subtopic-research/SKILL.md#L1)

skill 被拆分为两个目录，是为了区分“协调任务”和“执行子主题调研”。

## 9. 如何在 LangSmith 中检查

运行真实 CLI 后，在 trace 中重点检查：

1. 顶层 run 名称为 `nested_hybrid_deep_agent_pipeline`。
2. `research` 阶段中出现两个 `task` 工具调用。
3. 两个调用的 `subagent_type` 分别为：

```text
scenario_researcher
limits_researcher
```

4. 两个子 Agent 各自最多调用一次 `compact_web_search`。
5. `research` 完成后，外层图继续执行：

```text
draft -> editor_review -> finalize
```

如果两个 `task` 出现在同一条 AIMessage 中，说明协调员确实发起了并行委派。

## 10. 离线验证

执行：

```powershell
node src/debug/hybrid-deep-pipeline-smoke-test.mjs
```

[`testNestedResearchPrompt()`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L144) 会检查：

- research Prompt 包含两个子 Agent 名称；
- Prompt 包含两个独立输出路径；
- 嵌套模式仍然能够继续执行 Editor gate；
- Deep Agent 工厂能够构造嵌套 research 协调员。

[`testNestedResearchLocalStateIsolation()`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L236) 还会检查：父子 Agent 的局部计数和摘要状态被过滤，但可合并的文件状态仍然保留。

离线测试不会真实调用 `task`、模型 API 或搜索 API。真实委派行为需要通过嵌套 CLI 和 LangSmith trace 观察。

## 11. `ToolCallLimitExceededError` 排查

如果错误类似：

```text
ToolCallLimitExceededError: Tool call limit reached:
run limit exceeded (6/5 calls)
```

含义是某个嵌套调研子 Agent 尝试执行第 6 次工具调用，但该 Agent 的整体工具预算只有 5 次。

整体工具调用不仅包括联网搜索，还包括：

- 读取 skill；
- 读取问题文件；
- 写入 findings；
- 可选的 todo 创建和状态更新。

因此，整体工具上限不能直接等同于搜索上限。

当前实现将每个嵌套调研子 Agent 的整体工具预算设置为 `8`，模型调用预算设置为 `7`。联网搜索仍然由独立的 `compact_web_search({ maxCalls: 1 })` 限制为一次。

预算常量分别是 [`NESTED_RESEARCH_SUBAGENT_MAX_MODEL_CALLS`](../../src/debug/hybrid-deep-pipeline.mjs#L53) 和 [`NESTED_RESEARCH_SUBAGENT_MAX_TOOL_CALLS`](../../src/debug/hybrid-deep-pipeline.mjs#L54)。

## 12. `InvalidUpdateError: threadModelCallCount` 排查

如果错误类似：

```text
InvalidUpdateError: Invalid update for channel "threadModelCallCount"
with values [5,4]: LastValue can only receive one value per step.
```

这不是搜索失败，也不是模型输出格式错误。它表示两个并行子 Agent 在同一个 LangGraph step 中，尝试向父 Agent 的单值状态通道写入不同值。

触发链路如下：

1. 协调员在同一条 AIMessage 中发出两个 `task`。
2. LangChain 的 [`ToolNode`](../../node_modules/langchain/dist/agents/nodes/ToolNode.js#L305) 使用 `Promise.all()` 并行执行两个工具调用。
3. 每个子 Agent 的 `modelCallLimitMiddleware()` 都维护 [`threadModelCallCount`](../../node_modules/langchain/dist/agents/middleware/modelCallLimit.js#L15)。
4. `deepagents` 在子 Agent 结束后，通过 [`returnCommandWithStateUpdate()`](../../node_modules/deepagents/dist/index.js#L2196) 将子 Agent 状态包装为 `Command` 返回父 Agent。
5. `deepagents` 默认过滤列表没有包含预算计数字段，因此两个 `Command` 同时写回 `5` 和 `4`。
6. `threadModelCallCount` 是 `LastValue` 通道，不允许在同一步接收两个不同更新，于是 LangGraph 抛出异常。

[LangGraph 官方排查页](https://docs.langchain.com/oss/javascript/langgraph/errors/INVALID_CONCURRENT_GRAPH_UPDATE)给出的通用建议是：如果并行分支确实需要共同更新一个业务字段，为该字段定义 reducer。当前问题不同：预算计数和摘要事件属于单个 Agent 的局部状态，不应该在父子 Agent 之间合并。为这些字段增加 reducer 会混淆每个 Agent 的独立预算，因此这里选择隔离。

工具调用预算字段也存在同类风险：

```text
threadToolCallCount
runToolCallCount
```

如果只删除模型调用预算，错误可能换成工具预算通道冲突。

### 12.1 `threadModelCallCount` 从哪里来

`threadModelCallCount` 不是 `deepagents` 创建子 Agent 时自带的默认参数。它来自 LangChain 的 [`modelCallLimitMiddleware()`](../../node_modules/langchain/dist/agents/middleware/modelCallLimit.js#L95)。

只有 Agent 显式添加该中间件后，状态中才会出现：

```js
{
  threadModelCallCount: 0,
  runModelCallCount: 0,
}
```

字段定义位于 [`stateSchema`](../../node_modules/langchain/dist/agents/middleware/modelCallLimit.js#L14)。每次模型成功响应后，[`afterModel`](../../node_modules/langchain/dist/agents/middleware/modelCallLimit.js#L137) 会将两个数字同时加 `1`。

| 字段 | 统计范围 | Agent 执行结束后是否归零 |
| --- | --- | --- |
| `runModelCallCount` | 单次 `agent.invoke()` | 是。`afterAgent` 会将其重置为 `0`。 |
| `threadModelCallCount` | 整个对话 thread | 否。它用于跨多次运行统计同一个 thread 的累计模型调用次数。 |

当前工程在两处显式添加该中间件：

| Agent 类型 | 添加位置 | 配置目的 |
| --- | --- | --- |
| research、writer、editor 阶段 Deep Agent | [`createPhaseDeepAgent()`](../../src/debug/hybrid-deep-pipeline.mjs#L259) | 限制每个阶段单次执行的模型调用次数。 |
| 两个嵌套调研子 Agent | [`createIsolatedNestedResearchSubagent()`](../../src/debug/hybrid-deep-pipeline.mjs#L353) | 限制每个子 Agent 单次执行的模型调用次数。 |

本工程配置的是 `runLimit`，没有配置 `threadLimit`：

```js
modelCallLimitMiddleware({
  runLimit: maxModelCalls,
  exitBehavior: "error",
})
```

因此，真正用于强制停止单次执行的是 `runModelCallCount`。`threadModelCallCount` 仍然会被中间件维护，但当前没有用它执行 thread 级别的上限判断。

保留预算中间件仍然有价值：它可以避免模型循环失控，控制 token 消耗，并让 LangSmith trace 更容易排查。修复方向不是删除预算保护，而是阻止局部预算字段跨 Agent 传播。

### 12.2 修复方案

当前实现增加了两层隔离：

| 位置 | 代码 | 作用 |
| --- | --- | --- |
| 子 Agent 输入和输出 | [`createIsolatedNestedResearchSubagent()`](../../src/debug/hybrid-deep-pipeline.mjs#L353) | 防止子 Agent 继承父 Agent 已消耗的预算，也防止子 Agent 局部状态向外泄漏。 |
| `task` 返回父 Agent 前 | [`sanitizeNestedResearchTaskResult()`](../../src/debug/hybrid-deep-pipeline.mjs#L172) | 再次过滤 `Command.update`，避免并行分支同时写入单值局部通道。 |

过滤字段定义在 [`NESTED_RESEARCH_LOCAL_STATE_KEYS`](../../src/debug/hybrid-deep-pipeline.mjs#L55)：

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

`files` 不会被过滤。它在 `deepagents` 中使用 reducer 合并并行更新，两个子 Agent 仍然可以分别写入独立 findings 文件。

### 12.3 先区分三类状态

理解这两个函数前，需要先区分哪些数据应该共享，哪些数据不应该共享。

| 状态类型 | 示例 | 是否允许从子 Agent 合并回父 Agent | 原因 |
| --- | --- | --- | --- |
| 业务成果 | `files` | 允许 | 子 Agent 写出的 findings 文件正是协调员需要读取的结果。 |
| 单次 Agent 的预算 | `threadModelCallCount`、`runToolCallCount` | 不允许 | 这些数字只用于限制当前 Agent。父 Agent 和两个子 Agent 必须分别计数。 |
| 单次 Agent 的摘要过程 | `_summarizationEvent`、`_summarizationSessionId` | 不允许 | 这些字段描述某个 Agent 自己的上下文压缩过程，对另一个 Agent 没有业务意义。 |

可以将父 Agent 和两个子 Agent 想成三个独立执行器：

```text
research 协调员
├── scenario_researcher
└── limits_researcher
```

三个执行器可以通过 `files` 交换成果，但不应该共用同一个预算计数器。否则，`scenario_researcher` 已经消耗的模型调用次数可能被算到 `limits_researcher` 或父 Agent 身上。

负责识别局部字段的是 [`omitNestedResearchLocalState()`](../../src/debug/hybrid-deep-pipeline.mjs#L157)。它的行为很简单：

```js
const cleanedState = Object.fromEntries(
  Object.entries(state).filter(
    ([key]) => !nestedResearchLocalStateKeys.has(key),
  ),
);
```

它创建一个浅拷贝，删除局部字段，保留其他字段。假设输入为：

```js
{
  files: { "/sources/scenario.md": "..." },
  threadModelCallCount: 5,
  runToolCallCount: 3,
  _summarizationSessionId: "child-session",
}
```

输出将变为：

```js
{
  files: { "/sources/scenario.md": "..." },
}
```

这个辅助函数本身不知道数据来自父 Agent 还是子 Agent。调用它的位置决定了过滤发生在哪一个边界。

### 12.4 `createIsolatedNestedResearchSubagent()` 做什么

[`createIsolatedNestedResearchSubagent()`](../../src/debug/hybrid-deep-pipeline.mjs#L353) 的职责是创建一个能够写文件、读取 skill 和使用搜索工具的子 Agent，并在调用前后隔离局部状态。

#### 第一步：创建真正执行任务的内部 Agent

函数内部先调用 `createAgent()`：

```js
const agent = createAgent({
  name,
  model,
  tools: [createCompactWebSearch({ maxCalls: 1 })],
  systemPrompt,
  middleware: [
    todoListMiddleware(),
    createFilesystemMiddleware({ backend, permissions: HYBRID_PERMISSIONS }),
    createSummarizationMiddleware({ backend }),
    createPatchToolCallsMiddleware(),
    createSkillsMiddleware({
      backend,
      sources: [RESEARCH_SUBAGENT_SKILLS_ROOT],
    }),
    modelCallLimitMiddleware({ ... }),
    toolCallLimitMiddleware({ ... }),
  ],
});
```

这个内部 Agent 拥有完成小型调研任务所需的能力：

| 配置 | 作用 |
| --- | --- |
| `createCompactWebSearch({ maxCalls: 1 })` | 允许单个子 Agent 最多执行一次联网搜索。 |
| `todoListMiddleware()` | 允许子 Agent 管理自己的待办事项。 |
| `createFilesystemMiddleware()` | 允许子 Agent 将调研成果写入指定 findings 文件。 |
| `createSummarizationMiddleware()` | 子 Agent 上下文过长时，可以压缩自己的上下文。 |
| `createSkillsMiddleware()` | 允许子 Agent 读取专用 skill。 |
| 两个 limit middleware | 分别限制单个子 Agent 的模型调用和工具调用次数。 |

这里使用 `createAgent()` 而不是直接把配置对象交给 `createDeepAgent()` 的 `subagents` 参数，是因为还需要在外面包一层状态过滤逻辑。

#### 第二步：返回可以注册给 Deep Agent 的子 Agent 描述

函数返回：

```js
return {
  name,
  description,
  runnable: RunnableLambda.from(async (state, config) => {
    const isolatedInput = omitNestedResearchLocalState(state);
    const result = await agent.invoke(isolatedInput, config);
    return omitNestedResearchLocalState(result);
  }),
};
```

`name` 和 `description` 用于让协调员知道可以委派哪一种任务。`runnable` 才是真正收到状态并运行子 Agent 的入口。

#### 第三步：在调用前过滤父 Agent 状态

[`isolatedInput`](../../src/debug/hybrid-deep-pipeline.mjs#L398) 会删除父 Agent 的局部预算和摘要字段：

```text
父 Agent 状态
    ↓ omitNestedResearchLocalState()
删除父 Agent 自己的预算和摘要字段
    ↓ agent.invoke()
子 Agent 从独立的局部状态开始运行
```

如果缺少这一步，子 Agent 可能继承父 Agent 已经消耗的预算。例如，父 Agent 已调用模型 `5` 次，而子 Agent 的上限是 `7` 次，那么子 Agent 可能只剩 `2` 次可用额度。

#### 第四步：在调用后过滤子 Agent 状态

[`agent.invoke()`](../../src/debug/hybrid-deep-pipeline.mjs#L399) 完成后，再次调用过滤函数：

```text
子 Agent 完成后的状态
    ↓ omitNestedResearchLocalState()
删除子 Agent 自己的预算和摘要字段
    ↓
只把可共享状态交还给 task 工具
```

这一步会保留 `files`，因此 findings 文件仍然可以回到协调员；但子 Agent 自己消耗了多少次模型和工具，不会继续向外传播。

### 12.5 `sanitizeNestedResearchTaskResult()` 做什么

[`sanitizeNestedResearchTaskResult()`](../../src/debug/hybrid-deep-pipeline.mjs#L172) 处理的是另一个边界：`task` 工具已经执行完子 Agent，准备将结果交还给父 Agent。

它在 [`createNestedResearchTaskGuard()`](../../src/debug/hybrid-deep-pipeline.mjs#L305) 中被调用：

```js
return sanitizeNestedResearchTaskResult(await handler(request));
```

可以按下面的顺序阅读：

```text
父 Agent 发出 task
    ↓
handler(request) 执行 deepagents 内置 task 逻辑
    ↓
子 Agent 运行并返回结果
    ↓
deepagents 将状态更新包装为 Command
    ↓
sanitizeNestedResearchTaskResult() 清理 Command.update
    ↓
父 Agent 收到经过清理的 Command
```

#### `Command.update` 是什么

`Command` 是 LangGraph 用来表达“执行完当前动作后，如何更新图状态”的对象。这里最重要的是 `update` 字段。

简化后的返回值可能类似：

```js
new Command({
  update: {
    files: { "/sources/scenario.md": "..." },
    threadModelCallCount: 5,
    runToolCallCount: 3,
  },
});
```

其中 `files` 应该保留，两个计数字段应该删除。

#### 函数逐步做了什么

第一步，如果返回值不是 `Command`，或者没有 `update`，就原样返回：

```js
if (!isCommand(result) || result.update == null) return result;
```

这样可以避免误改普通工具的返回值。

第二步，过滤 `update`。LangGraph 的 `update` 可能有两种形态，所以代码分别处理：

```js
const update = Array.isArray(result.update)
  ? result.update.filter(([key]) => !nestedResearchLocalStateKeys.has(key))
  : omitNestedResearchLocalState(result.update);
```

| `update` 形态 | 示例 | 过滤方式 |
| --- | --- | --- |
| 对象 | `{ files, threadModelCallCount }` | 调用 `omitNestedResearchLocalState()`。 |
| 键值对数组 | `[[key1, value1], [key2, value2]]` | 使用 `filter()` 删除局部字段对应的条目。 |

第三步，创建一个新的 `Command`：

```js
return new Command({
  graph: result.graph,
  update,
  resume: result.resume,
  goto: result.goto,
});
```

这里保留了原始 `Command` 的流程控制字段，只替换经过清理的 `update`。因此，清理不会改变 LangGraph 下一步应该跳转到哪里，只会限制哪些状态能够写回父 Agent。

### 12.6 并行执行时，清理前后有什么差别

修复前，两个并行子 Agent 可能同时向父 Agent 返回：

```js
// scenario_researcher
{ files: { "/sources/scenario.md": "..." }, threadModelCallCount: 5 }

// limits_researcher
{ files: { "/sources/limits.md": "..." }, threadModelCallCount: 4 }
```

`files` 可以通过 reducer 合并。但是 `threadModelCallCount` 是 `LastValue` 通道，同一个 step 中不能同时接收 `5` 和 `4`，因此抛出 `InvalidUpdateError`。

修复后，父 Agent 实际收到：

```js
// scenario_researcher
{ files: { "/sources/scenario.md": "..." } }

// limits_researcher
{ files: { "/sources/limits.md": "..." } }
```

两个文件更新可以合并，局部预算不会进入父 Agent 状态。

### 12.7 为什么需要两层过滤

两层过滤关注的边界不同：

| 只保留哪一层 | 仍然存在的问题 |
| --- | --- |
| 只使用 `createIsolatedNestedResearchSubagent()` | 当前实现通常已经能够阻止局部状态泄漏，但 `task` 工具边界没有最终校验。以后如果替换 runnable、调整 `deepagents` 版本或增加新的返回路径，局部字段可能再次进入 `Command.update`。 |
| 只使用 `sanitizeNestedResearchTaskResult()` | 父 Agent 最终不会收到冲突字段，但子 Agent 仍可能继承父 Agent 已消耗的预算，导致可用额度减少或过早触发 limit middleware。 |
| 两层都使用 | 子 Agent 启动时拥有独立预算；结束后父 Agent 只收到允许共享的状态；`task` 返回前还有一次最终校验。 |

因此，这两层不是重复代码：

```text
createIsolatedNestedResearchSubagent()
负责子 Agent 执行边界的输入和输出隔离

sanitizeNestedResearchTaskResult()
负责 task 工具边界的最终状态校验
```

### 12.8 为什么不改成串行调用

让协调员先调用一个 `task`，等待完成后再调用另一个 `task`，可以绕开“同一步多写入”的异常，但会隐藏父子状态泄漏问题，也无法继续观察真正的并行子 Agent 协作。

本工程保留并行委派，并隔离不应该跨 Agent 传播的局部状态。

## 13. 自行测试时可以调整什么

### 13.1 推荐实验顺序

每次只改变一个变量：

1. 运行离线测试，确认图结构和文件 gate 正常。
2. 使用默认问题运行嵌套 CLI。
3. 在 LangSmith 中确认两个 `task` 是否并行出现。
4. 检查两个子 Agent 各自调用了多少次模型、文件工具和搜索工具。
5. 只有触发预算错误时，才小幅提高对应限制。
6. 最后再尝试不同问题、不同模型或更多子 Agent。

离线测试：

```powershell
node src/debug/hybrid-deep-pipeline-smoke-test.mjs
```

真实测试：

```powershell
node src/debug/nested-hybrid-deep-cli.mjs
```

### 13.2 可调参数

| 想观察的现象 | 调整位置 | 当前值 | 调整建议 |
| --- | --- | --- | --- |
| 更换问题 | CLI 参数 | 默认 `node:test` 问题 | 先选择可以拆成两个独立方面的小问题。 |
| 更换模型 | `HYBRID_PIPELINE_MODEL` | 回退到 `OPENAI_MODEL` | 比较工具调用遵循能力和 token 消耗。 |
| 子 Agent 模型调用不足 | [`NESTED_RESEARCH_SUBAGENT_MAX_MODEL_CALLS`](../../src/debug/hybrid-deep-pipeline.mjs#L53) | `7` | 每次增加 `1`，并检查是否存在空转。 |
| 子 Agent 全部工具调用不足 | [`NESTED_RESEARCH_SUBAGENT_MAX_TOOL_CALLS`](../../src/debug/hybrid-deep-pipeline.mjs#L54) | `8` | 每次增加 `1`，区分读取、todo、搜索和写入。 |
| 子 Agent 搜索资料不足 | [`createCompactWebSearch({ maxCalls: 1 })`](../../src/debug/hybrid-deep-pipeline.mjs#L363) | 每个子 Agent `1` 次 | 与全部工具预算分开调整，通常不要超过 `2`。 |
| 协调员无法完成合并 | [`maxModelCalls`](../../src/debug/hybrid-deep-pipeline.mjs#L469) 和 [`maxToolCalls`](../../src/debug/hybrid-deep-pipeline.mjs#L470) | `8` 和 `10` | 先检查是否重复读取文件，再小幅提高。 |
| 阶段图步数不足 | `HYBRID_PHASE_RECURSION_LIMIT` | `96` | 出现 `GRAPH_RECURSION_LIMIT` 时检查 trace 后调整。 |
| 增加子 Agent 数量 | [`createNestedResearchSubagents()`](../../src/debug/hybrid-deep-pipeline.mjs#L410) | `2` | 同步修改名称列表、Prompt、guard、输出路径和文件 gate。 |

### 13.3 三类预算不要混淆

| 预算 | 控制范围 | 典型报错或现象 |
| --- | --- | --- |
| `maxTaskCalls` | research 协调员可以创建多少次子 Agent | 第三个 `task` 被拒绝。 |
| 子 Agent 全部工具预算 | 单个子 Agent 的读取、搜索、写入和 todo 总次数 | `ToolCallLimitExceededError` 且 `toolName: undefined`。 |
| `compact_web_search` 搜索预算 | 单个子 Agent 的联网搜索次数 | 工具返回“已达到搜索次数上限”。 |

### 13.4 不建议直接移除的保护

测试时可以逐步增加预算，但不建议直接删除：

- `NestedResearchTaskGuardMiddleware`；
- `task` 调用次数上限；
- 每种子 Agent 最多调用一次的限制；
- 子 Agent 输出文件检查；
- 父子 Agent 局部状态隔离；
- Editor gate；
- 文件系统默认拒绝规则；
- 搜索次数限制。

移除这些保护后，测试虽然可能暂时通过，但 trace 可能重新膨胀，也更难判断问题来自模型、Prompt、skill 还是工具。
