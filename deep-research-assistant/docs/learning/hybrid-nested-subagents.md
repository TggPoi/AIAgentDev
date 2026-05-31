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

嵌套子 Agent 定义在 [`createNestedResearchSubagents()`](../../src/debug/hybrid-deep-pipeline.mjs#L316)：

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

两个子 Agent 由 [`createIsolatedNestedResearchSubagent()`](../../src/debug/hybrid-deep-pipeline.mjs#L270) 预先创建为独立的 `createAgent()`。它们仍然拥有 filesystem、skill、todo、摘要和预算中间件，但会隔离父子 Agent 的局部计数状态。第 12 节解释这样设计的原因。

## 5. 协调员如何获得 `task`

[`createHybridDeepPhaseAgents()`](../../src/debug/hybrid-deep-pipeline.mjs#L349) 在嵌套模式下创建 research 协调员：

```js
createPhaseDeepAgent({
  name: "hybrid_research_coordinator",
  subagents: createNestedResearchSubagents({ model, backend }),
  maxTaskCalls: 2,
  ...
})
```

[`createPhaseDeepAgent()`](../../src/debug/hybrid-deep-pipeline.mjs#L200) 最终调用 `createDeepAgent()`，并传入 `subagents`：

```js
return createDeepAgent({
  ...
  subagents,
})
```

`createDeepAgent()` 会自动添加 `createSubAgentMiddleware()`。该中间件向协调员提供 `task` 工具。

## 6. 为什么不是只修改 `maxTaskCalls`

只将 `maxTaskCalls` 从 `0` 改为 `2` 不够严格。

原因是 `createDeepAgent()` 默认还可能提供 `general-purpose` 子 Agent。模型也可能重复调用同一种调研员。

所以嵌套模式还增加了 [`createNestedResearchTaskGuard()`](../../src/debug/hybrid-deep-pipeline.mjs#L242)：

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

对应路径在 [`createHybridRunPaths()`](../../src/debug/hybrid-deep-pipeline.mjs#L114) 中创建。

外层 research 节点还会检查三个文件是否存在：

```js
assertVirtualFile(state.scenarioFindingsPath, "research:scenario_researcher");
assertVirtualFile(state.limitsFindingsPath, "research:limits_researcher");
assertVirtualFile(state.findingsPath, "research");
```

对应代码位于 [`researchNode()`](../../src/debug/hybrid-deep-pipeline.mjs#L481)。

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

[`testNestedResearchPrompt()`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L119) 会检查：

- research Prompt 包含两个子 Agent 名称；
- Prompt 包含两个独立输出路径；
- 嵌套模式仍然能够继续执行 Editor gate；
- Deep Agent 工厂能够构造嵌套 research 协调员。

[`testNestedResearchLocalStateIsolation()`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L203) 还会检查：父子 Agent 的局部计数和摘要状态被过滤，但可合并的文件状态仍然保留。

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

预算常量位于 [`hybrid-deep-pipeline.mjs`](../../src/debug/hybrid-deep-pipeline.mjs#L53)。

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

### 12.1 修复方案

当前实现增加了两层隔离：

| 位置 | 代码 | 作用 |
| --- | --- | --- |
| 子 Agent 输入和输出 | [`createIsolatedNestedResearchSubagent()`](../../src/debug/hybrid-deep-pipeline.mjs#L270) | 防止子 Agent 继承父 Agent 已消耗的预算，也防止子 Agent 局部状态向外泄漏。 |
| `task` 返回父 Agent 前 | [`sanitizeNestedResearchTaskResult()`](../../src/debug/hybrid-deep-pipeline.mjs#L141) | 再次过滤 `Command.update`，避免并行分支同时写入单值局部通道。 |

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

### 12.2 为什么不改成串行调用

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
| 子 Agent 搜索资料不足 | [`createCompactWebSearch({ maxCalls: 1 })`](../../src/debug/hybrid-deep-pipeline.mjs#L280) | 每个子 Agent `1` 次 | 与全部工具预算分开调整，通常不要超过 `2`。 |
| 协调员无法完成合并 | [`maxModelCalls` 和 `maxToolCalls`](../../src/debug/hybrid-deep-pipeline.mjs#L370) | `8` 和 `10` | 先检查是否重复读取文件，再小幅提高。 |
| 阶段图步数不足 | `HYBRID_PHASE_RECURSION_LIMIT` | `96` | 出现 `GRAPH_RECURSION_LIMIT` 时检查 trace 后调整。 |
| 增加子 Agent 数量 | [`createNestedResearchSubagents()`](../../src/debug/hybrid-deep-pipeline.mjs#L316) | `2` | 同步修改名称列表、Prompt、guard、输出路径和文件 gate。 |

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
