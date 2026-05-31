# `StateGraph + createDeepAgent` 混合流水线

## 1. 目标

本文讲解第三套实现：

```text
外层 StateGraph
  -> research Deep Agent
  -> draft Deep Agent
  -> editor_review Deep Agent
  -> finalize Deep Agent
```

源码入口：

- 流水线：[`hybrid-deep-pipeline.mjs`](../../src/debug/hybrid-deep-pipeline.mjs#L1)
- CLI：[`hybrid-deep-cli.mjs`](../../src/debug/hybrid-deep-cli.mjs#L1)
- 离线验证：[`hybrid-deep-pipeline-smoke-test.mjs`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L1)

这套实现用于学习如何同时获得两类能力：

1. 使用 `StateGraph` 硬性规定跨阶段流程，避免 Editor 被省略。
2. 在每个阶段内部使用 `createDeepAgent()`，保留 memory、skill、文件系统和默认 Deep Agent 中间件。

它不会修改以下两套已有实现：

| 实现 | 源码 | 用途 |
| --- | --- | --- |
| 原版 | [`agent.mjs`](../../src/agent.mjs#L207) | 观察单个 Deep Agent 的自主规划能力。 |
| 基础受控版 | [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L447) | 用最少中间件排查流程问题。 |

## 2. 运行方式

执行混合版：

```powershell
node src/debug/hybrid-deep-cli.mjs
```

默认测试问题定义在 [`DEFAULT_HYBRID_TEST_QUERY`](../../src/debug/hybrid-deep-pipeline.mjs#L38)。

也可以传入自定义小型问题：

```powershell
node src/debug/hybrid-deep-cli.mjs "调研 npm workspaces 是否适合管理三个包的小型仓库，输出一页以内建议"
```

如需临时调整单个 Deep Agent 阶段的 LangGraph 步数：

```powershell
$env:HYBRID_PHASE_RECURSION_LIMIT = "120"
node src/debug/hybrid-deep-cli.mjs
```

运行离线验证：

```powershell
node src/debug/hybrid-deep-pipeline-smoke-test.mjs
```

离线验证不会调用模型 API 或搜索 API。

## 3. 与前两套实现的关系

| 维度 | 原版 | 基础受控版 | 混合版 |
| --- | --- | --- | --- |
| 主流程 | 单个 `createDeepAgent()` 自主规划 | `StateGraph + createAgent()` | `StateGraph + createDeepAgent()` |
| Editor 保证 | Prompt 约束 | 图节点和 gate | 图节点和 gate |
| memory | 自动启用 | 未启用 | 每个阶段自动启用 |
| skill | 自动启用 | 手动挂载中间件 | 每个阶段通过 `skills` 参数自动启用 |
| 默认摘要 | 启用 | 未启用 | 启用，但上下文限制在单个阶段 |
| 子 Agent `task` 工具 | 可用 | 不存在 | 框架提供，但学习运行默认禁止调用 |
| trace 长度 | 最长 | 最短 | 介于两者之间 |

混合版不是基础受控版的替代品：

- 排查流程错误时，基础受控版更容易阅读。
- 学习 Deep Agent 默认能力如何嵌入固定流程时，使用混合版。

### 3.1 行业定位：主流模式，不是唯一标准

这套方案属于当前常见的混合架构：

```text
外层确定性工作流
  -> 控制固定业务阶段、检查点和失败条件

阶段内部 Agent
  -> 根据局部任务自主读取文件、使用工具和调用子 Agent
```

它不是某个框架规定的唯一标准实现，也不能仅凭公开资料判断其市场占有率。但“代码编排 + 局部 Agent 自主性”是多个主流框架和 Agent 实践明确支持的模式：

| 来源 | 对应观点 |
| --- | --- |
| [LangChain：Custom workflow](https://docs.langchain.com/oss/python/langchain/multi-agent/custom-workflow) | 使用 LangGraph 定义确定性流程，并将 Agent 嵌入图节点。 |
| [LangGraph：Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents) | orchestrator-worker 是常见工作流，协调员可拆分任务并汇总 worker 输出。 |
| [OpenAI Agents SDK：Agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/) | 可以混合使用模型自主编排和代码编排。 |
| [Anthropic：Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) | 固定任务优先使用可预测工作流；开放任务再增加 Agent 自主性。 |
| [Anthropic：Multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system) | Research 系统使用 orchestrator-worker：主 Agent 并行委派子 Agent 并汇总结果。 |

当前工程中的固定四阶段、Editor gate、搜索次数和工具预算是针对调试目标设计的参数，不是行业统一标准。

## 4. 外层图：硬性规定流程

图结构定义在 [`buildHybridDeepPipeline()`](../../src/debug/hybrid-deep-pipeline.mjs#L601)：

```js
return new StateGraph(HybridPipelineState)
  .addNode("research", researchNode)
  .addNode("draft", draftNode)
  .addNode("editor_review", reviewNode)
  .addNode("finalize", finalizeNode)
  .addEdge(START, "research")
  .addEdge("research", "draft")
  .addEdge("draft", "editor_review")
  .addEdge("editor_review", "finalize")
  .addEdge("finalize", END)
  .compile({ name: "hybrid_deep_agent_pipeline" });
```

这段代码解决了单个自主 Agent 的关键缺陷：

> 即使某个阶段内部发生上下文摘要，外层图仍然知道下一步必须进入 `editor_review`。执行顺序不再依赖模型记住完整 Prompt。

## 5. Editor gate：禁止提前定稿

Editor 节点完成后，才会将状态写为：

```js
editorCompleted: true
```

对应代码位于 [`reviewNode()`](../../src/debug/hybrid-deep-pipeline.mjs#L669)。

定稿前，[`finalizeNode()`](../../src/debug/hybrid-deep-pipeline.mjs#L695) 会执行两次检查：

```js
if (!state.editorCompleted) {
  throw new Error("Editor gate 阻止定稿：尚未完成 Editor 审阅");
}
assertVirtualFile(state.reviewPath, "finalize");
```

因此：

- 模型无法自行跳过 Editor 节点。
- Editor 没有写出 review 文件时，流水线会停止。
- 定稿阶段必须读取真实存在的审阅结果。

## 6. 内层 Deep Agent：自动恢复默认能力

混合版没有在三个阶段中直接调用基础 `createAgent()`。

它通过 [`createPhaseDeepAgent()`](../../src/debug/hybrid-deep-pipeline.mjs#L259) 统一创建阶段 Agent：

```js
return createDeepAgent({
  name,
  model,
  backend,
  tools,
  systemPrompt,
  memory: [HYBRID_MEMORY_PATH],
  skills: [skillsRoot],
  permissions: HYBRID_PERMISSIONS,
  middleware: [...],
});
```

`createDeepAgent()` 会自动添加：

| 能力 | 来源 |
| --- | --- |
| todo 管理 | `todoListMiddleware()` |
| 文件工具 | `createFilesystemMiddleware()` |
| 子 Agent 委派工具 | `createSubAgentMiddleware()` |
| 自动摘要 | `createSummarizationMiddleware()` |
| 工具调用修补 | `createPatchToolCallsMiddleware()` |
| skill | 顶层 `skills` 参数触发 |
| memory | 顶层 `memory` 参数触发 |

自动组装逻辑可以查看 [`deepagents/dist/index.js`](../../node_modules/deepagents/dist/index.js#L8145)。

## 7. memory：不需要手动实现

混合版新增了一份只读 memory：

- [`hybrid-memory/AGENTS.md`](../../hybrid-memory/AGENTS.md#L1)

路径定义在 [`HYBRID_MEMORY_PATH`](../../src/debug/hybrid-deep-pipeline.mjs#L42)：

```js
const HYBRID_MEMORY_PATH = "/hybrid-memory/AGENTS.md";
```

随后通过 `createDeepAgent()` 参数传入：

```js
memory: [HYBRID_MEMORY_PATH]
```

**createDeepAgent() 会自动创建 MemoryMiddleware。它分两步工作。**

**1. 每次 agent.invoke() 开始时读取文件**
beforeAgent() 会读取 AGENTS.md，并将内容保存到当前 Agent state 的 memoryContents 中。

如果 state 中已经存在 memoryContents，则不会重复读取文件。

**2. 每次调用模型时注入 SystemMessage**
wrapModelCall() 会把已加载的 memory 内容追加到 SystemMessage 中，然后再调用模型。

`createDeepAgent()` 会自动挂载 `createMemoryMiddleware()`，读取文件并加入系统提示词。

这与基础受控版不同。基础受控版如果需要 memory，必须手动调用 `createMemoryMiddleware()`。

## 8. skill：按阶段隔离

混合版为三个阶段分别建立了 skill 目录：

| 阶段 | skill | 源码 |
| --- | --- | --- |
| 调研 | `compact-research` | [`SKILL.md`](../../skills-hybrid/research/compact-research/SKILL.md#L1) |
| 写作 | `concise-report-writer` | [`SKILL.md`](../../skills-hybrid/writer/concise-report-writer/SKILL.md#L1) |
| 审阅 | `mandatory-editor-review` | [`SKILL.md`](../../skills-hybrid/editor/mandatory-editor-review/SKILL.md#L1) |

路径定义在 [`hybrid-deep-pipeline.mjs`](../../src/debug/hybrid-deep-pipeline.mjs#L43)：

```js
const RESEARCH_SKILLS_ROOT = "/skills-hybrid/research/";
const WRITER_SKILLS_ROOT = "/skills-hybrid/writer/";
const EDITOR_SKILLS_ROOT = "/skills-hybrid/editor/";
```

创建 Agent 时，每个阶段只传入自己的目录：

```js
skills: [skillsRoot]
```

这样可以避免写作阶段看到调研 skill，也可以避免 Editor 看到无关工具说明。

## 9. 子 Agent：为什么默认禁止继续委派

`createDeepAgent()` 默认会提供 `task` 工具。因此，阶段内部理论上仍然可以继续创建子 Agent。

但默认学习问题很小。如果允许 `research Deep Agent -> task -> 子 Agent` 继续扩展，trace 会重新变长。

所以 `createPhaseDeepAgent()` 中的 [`toolCallLimitMiddleware({ toolName: "task", ... })`](../../src/debug/hybrid-deep-pipeline.mjs#L291) 增加了工具级硬限制：

```js
toolCallLimitMiddleware({
  toolName: "task",
  runLimit: maxTaskCalls,
  exitBehavior: "error",
})
```

`maxTaskCalls` 默认值为 `0`：

```js
maxTaskCalls = 0
```

这表示：

- `createDeepAgent()` 的子 Agent 机制仍然存在。
- 当前学习运行禁止阶段内部再次拆分任务。
- 如果模型误调用 `task`，流水线会立即暴露问题，而不是产生额外 token 消耗。

工程中已经增加了一个独立的嵌套测试入口。它只在 research 阶段开放两个受控子 Agent：

- CLI：[`nested-hybrid-deep-cli.mjs`](../../src/debug/nested-hybrid-deep-cli.mjs#L1)
- 详细说明：[混合流水线中的嵌套子 Agent](./hybrid-nested-subagents.md#L1)

## 10. 文件权限：限制读写范围

混合版只允许：

| 路径 | 权限 | 用途 |
| --- | --- | --- |
| `/hybrid_workspace/**` | 读写 | 保存每次运行的输入、草稿、review 和终稿。 |
| `/skills-hybrid/**` | 只读 | 加载阶段 skill。 |
| `/hybrid-memory/**` | 只读 | 加载 memory。 |
| 其他路径 | 拒绝 | 避免调试 Agent 浏览或修改工程其他内容。 |

权限定义位于 [`HYBRID_PERMISSIONS`](../../src/debug/hybrid-deep-pipeline.mjs#L82)。

## 11. 调用预算：限制单个阶段成本

每个阶段都会增加：

```js
modelCallLimitMiddleware(...)
toolCallLimitMiddleware(...)
toolCallLimitMiddleware({ toolName: "task", ... })
```

对应代码位于 `createPhaseDeepAgent()` 中的 [`modelCallLimitMiddleware()`](../../src/debug/hybrid-deep-pipeline.mjs#L283) 和 [`toolCallLimitMiddleware()`](../../src/debug/hybrid-deep-pipeline.mjs#L287)。

当前预算：

| 阶段 | 模型调用上限 | 工具调用上限 |
| --- | --- | --- |
| `research` | 8 | 8 |
| `draft` | 7 | 7 |
| `editor_review` | 7 | 7 |
| `finalize` | 7 | 7 |

此外，阶段内部 LangGraph 步数默认上限为 `96`：

- [`DEFAULT_HYBRID_PHASE_RECURSION_LIMIT`](../../src/debug/hybrid-deep-pipeline.mjs#L48)
- [`invokePhase()`](../../src/debug/hybrid-deep-pipeline.mjs#L565)

混合版的步数上限比基础受控版更高，因为 `createDeepAgent()` 默认挂载了更多中间件。图步数不等于模型调用次数。

### 11.1 已加入的保护措施

当前实现刻意增加了多层保护。它们分别解决不同问题：

| 类别 | 保护措施 | 目的 |
| --- | --- | --- |
| 流程正确性 | 固定 `research -> draft -> editor_review -> finalize` 图结构 | 防止模型跳过 Editor 或提前总结。 |
| 流程正确性 | `editorCompleted` gate | Editor 未完成时禁止定稿。 |
| 流程正确性 | `assertVirtualFile()` | 阶段没有写出真实文件时立即停止。 |
| 成本控制 | 每阶段模型调用上限 | 防止异常循环持续请求模型。 |
| 成本控制 | 每阶段全部工具调用上限 | 防止重复读取、重复写入和空转。 |
| 成本控制 | 默认 `maxTaskCalls = 0` | 普通混合版不允许阶段内部继续扩张子 Agent。 |
| 成本控制 | 精简搜索工具 | 限制搜索次数、返回结果数量和摘要长度。 |
| 文件安全 | `HYBRID_PERMISSIONS` | 只允许访问运行目录、skill 和 memory；其他路径默认拒绝。 |
| 上下文隔离 | 按阶段配置 skill | 避免写作和 Editor 阶段看到无关 skill。 |
| 运行隔离 | 每次使用独立 `runId` 目录 | 防止历史 findings 干扰本次运行。 |
| 可观测性 | 阶段 `runName` 和 tags | 在 LangSmith 中区分 research、draft、Editor 和 finalize。 |
| 可观测性 | `GRAPH_RECURSION_LIMIT` 增强错误 | 区分图步数上限和模型调用次数。 |

嵌套子 Agent 模式还有额外保护：

- `task` 最多调用两次；
- 只允许 `scenario_researcher` 和 `limits_researcher`；
- 每种子 Agent 最多调用一次；
- 每个子 Agent 最多搜索一次；
- 父子 Agent 的预算计数和摘要状态相互隔离；
- 两个子 Agent 的独立 findings 文件和汇总文件都必须存在。

详细说明见 [混合流水线中的嵌套子 Agent](./hybrid-nested-subagents.md#L1)。

### 11.2 自行测试时可以调整什么

建议一次只调整一个变量，并在 LangSmith 中比较 trace。

| 调整目标 | 调整位置 | 建议 |
| --- | --- | --- |
| 更换测试问题 | CLI 参数 | 优先使用一页以内、可拆成两个独立主题的问题。 |
| 更换模型 | 环境变量 `HYBRID_PIPELINE_MODEL` | 比较不同模型的工具遵循能力和 token 消耗。 |
| 增加阶段图步数 | 环境变量 `HYBRID_PHASE_RECURSION_LIMIT` | 只在确认没有重复调用后提高。 |
| 增加阶段模型预算 | [`createHybridDeepPhaseAgents()`](../../src/debug/hybrid-deep-pipeline.mjs#L448) | 模型提前停止或无法完成写入时，小幅增加。 |
| 增加阶段工具预算 | [`createHybridDeepPhaseAgents()`](../../src/debug/hybrid-deep-pipeline.mjs#L448) | 出现 `ToolCallLimitExceededError` 时先检查 trace，再小幅增加。 |
| 调整搜索次数 | [`createCompactWebSearch()`](../../src/debug/compact-search.mjs#L68) | 与全部工具预算分开调整。 |
| 调整搜索结果长度 | [`compact-search.mjs`](../../src/debug/compact-search.mjs#L6) | trace 太长时优先降低结果数量和摘要长度。 |
| 调整子 Agent 数量 | 嵌套模式的 `subagents`、Prompt、guard 和文件路径 | 必须同步修改，不能只提高 `maxTaskCalls`。 |
| 调整 skill | [`skills-hybrid`](../../skills-hybrid/research/compact-research/SKILL.md#L1) | 适合测试 Prompt 与 skill 的职责边界。 |

不建议为了通过一次测试直接移除：

- Editor gate；
- `assertVirtualFile()`；
- 文件系统默认拒绝规则；
- 嵌套模式的子 Agent 白名单；
- 搜索次数限制；
- 模型和工具调用预算。

如果需要放宽限制，应逐步提高预算并观察 trace，而不是一次性取消保护。

## 12. 每次运行使用独立目录

每次运行都会写入：

```text
hybrid_workspace/
  runs/
    <runId>/
      sources/
        question.md
        findings_node_test.md
      reports/
        draft_node_test.md
        review_node_test.md
        report_node_test.md
```

路径由 [`createHybridRunPaths()`](../../src/debug/hybrid-deep-pipeline.mjs#L135) 创建。

独立目录可以避免历史材料干扰当前运行，也便于将 LangSmith trace 与本地文件对应起来。

## 13. 离线 smoke test 验证了什么

执行：

```powershell
node src/debug/hybrid-deep-pipeline-smoke-test.mjs
```

测试覆盖：

| 测试 | 源码 | 目的 |
| --- | --- | --- |
| 固定阶段顺序 | [`testPipelineOrderAndEditorGate()`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L47) | 验证阶段顺序和最终报告文件。 |
| Editor 文件缺失 | [`testMissingEditorOutputStopsPipeline()`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L112) | 验证 Editor 未写 review 时流水线失败。 |
| Deep Agent 工厂 | [`testDeepAgentFactory()`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L205) | 验证三个 `createDeepAgent()` 实例可以构造。 |
| 嵌套状态隔离 | [`testNestedResearchLocalStateIsolation()`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L236) | 验证并行子 Agent 不会向父 Agent 回传局部计数状态。 |
| 学习资源 | [`testLearningFilesExist()`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L271) | 验证 memory 和 skill 文件存在。 |

## 14. 推荐阅读顺序

1. 阅读外层固定图：[`buildHybridDeepPipeline()`](../../src/debug/hybrid-deep-pipeline.mjs#L601)
2. 阅读 Editor gate：[`finalizeNode()`](../../src/debug/hybrid-deep-pipeline.mjs#L695)
3. 阅读阶段 Deep Agent 工厂：[`createPhaseDeepAgent()`](../../src/debug/hybrid-deep-pipeline.mjs#L259)
4. 阅读三个阶段配置：[`createHybridDeepPhaseAgents()`](../../src/debug/hybrid-deep-pipeline.mjs#L448)
5. 阅读 memory：[`AGENTS.md`](../../hybrid-memory/AGENTS.md#L1)
6. 阅读三个独立 skill：[`skills-hybrid`](../../skills-hybrid/research/compact-research/SKILL.md#L1)
7. 运行离线 smoke test：[`hybrid-deep-pipeline-smoke-test.mjs`](../../src/debug/hybrid-deep-pipeline-smoke-test.mjs#L1)
8. 最后运行真实 CLI：[`hybrid-deep-cli.mjs`](../../src/debug/hybrid-deep-cli.mjs#L1)
9. 运行嵌套子 Agent CLI：[`nested-hybrid-deep-cli.mjs`](../../src/debug/nested-hybrid-deep-cli.mjs#L1)
