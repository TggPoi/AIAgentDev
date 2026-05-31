# `createDeepAgent` 与 `createAgent` 实现方案对比

## 1. 文档目标

当前工程中存在两套可以独立运行的实现：

| 方案 | 入口 | 定位 |
| --- | --- | --- |
| 原版 Deep Agent | [`agent.mjs`](../../src/agent.mjs#L207) | 功能完整的自主调研 Agent。 |
| 受控调试版 | [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L465) | 用固定流程缩短 trace，便于学习和排查问题。 |

两套方案并不是简单的“新版本替换旧版本”。它们解决的问题不同：

- 原版优先保留 Agent 的自主规划能力。
- 调试版优先保证流程可控、成本有限、错误容易定位。

本文重点回答两个问题：

1. 使用 `createDeepAgent()` 时，是否只能依赖 Prompt 约束执行流程？
2. 换成基础 `createAgent()` 后，memory 和 skill 是否都需要自行实现？

## 2. 先看结论

### 2.1 `createDeepAgent()` 不只支持 Prompt 约束

`createDeepAgent()` 支持增加自定义中间件。中间件可以限制工具调用、校验状态、拒绝不合法操作。

但是，需要区分两类能力：

| 能力 | 含义 | 推荐方式 |
| --- | --- | --- |
| 阻止错误动作 | 例如 Editor 未完成时，禁止写入最终报告。 | 自定义中间件或工具包装器。 |
| 保证阶段必定执行 | 例如无论模型如何规划，Editor 节点都必须执行一次。 | 外层 `StateGraph`。 |

仅使用 Prompt 时，模型通常会遵循流程，但代码没有提供硬性保证。

中间件可以拒绝提前定稿，但如果模型始终不调用 Editor，中间件也无法自动替模型完成调度。此时模型可能反复尝试其他操作，最终触发递归上限。

### 2.2 使用 `createAgent()` 不等于重新手写 skill 系统

受控调试版确实需要手动选择并挂载中间件，但不需要重新编写 skill 加载器。

调试版已经复用了 `deepagents` 提供的 [`createSkillsMiddleware()`](../../src/debug/controlled-pipeline.mjs#L186)：

```js
createSkillsMiddleware({
  backend,
  sources: [DEBUG_SKILLS_ROOT],
})
```

该中间件会扫描 skill 目录，将 skill 名称和描述注入系统提示词，并让 Agent 在需要时读取完整的 `SKILL.md`。这是渐进式加载机制，具体说明见 [`deepagents` 类型定义](../../node_modules/deepagents/dist/index.d.ts#L2307)。

因此，更准确的说法是：

> 使用 `createAgent()` 时，需要手动组装所需能力，但可以直接复用 `deepagents` 已经提供的中间件。

## 3. 两种方案的结构

### 3.1 原版：一个自主规划的 Deep Agent

原版在 [`createIntelligenceDeskAgent()`](../../src/agent.mjs#L161) 中调用：

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

结构可以概括为：

```text
用户问题
  -> 主 Agent 自主规划
     -> 可调用 researcher
     -> 可调用 analyst
     -> 可调用 editor
     -> 主 Agent 起草、修订并输出最终报告
```

标准阶段和资源限制主要写在 [`orchestratorPrompt`](../../src/agent.mjs#L105) 中。例如：

- 最多使用两个调研员：[`agent.mjs`](../../src/agent.mjs#L140)
- 调研完成后进入“起草 -> 审阅 -> 定稿”：[`agent.mjs`](../../src/agent.mjs#L144)

这些规则会影响模型决策，但不是 JavaScript 层面的固定执行路径。

### 3.2 调试版：外层固定图，阶段内部使用基础 Agent

调试版使用 [`StateGraph`](../../src/debug/controlled-pipeline.mjs#L447) 固定执行顺序：

```text
START
  -> research
  -> draft
  -> editor_review
  -> finalize
  -> END
```

每个阶段内部仍然是一个可以调用工具的 Agent：

| 阶段 | Agent | 定义位置 |
| --- | --- | --- |
| 调研 | `debug_researcher` | [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L214) |
| 起草和定稿 | `debug_writer` | [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L232) |
| 审阅 | `debug_editor` | [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L250) |

`finalizeNode()` 还会执行 Editor gate：

```js
if (!state.editorCompleted) {
  throw new Error("Editor gate 阻止定稿：尚未完成 Editor 审阅");
}
```

对应代码位于 [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L424)。

## 4. `createDeepAgent()` 自动提供了什么

`createDeepAgent()` 并不是一种完全不同的底层 Agent。它本质上会组装一组默认中间件，最后仍然调用基础 `createAgent()`。

默认组装逻辑位于 [`deepagents/dist/index.js`](../../node_modules/deepagents/dist/index.js#L8149)：

| 中间件 | 默认挂载 | 作用 |
| --- | --- | --- |
| `todoListMiddleware()` | 是 | 提供 todo 管理能力。 |
| `createFilesystemMiddleware()` | 是 | 提供文件读取、写入和编辑工具。 |
| `createSubAgentMiddleware()` | 是 | 提供 `task` 工具，用于调用子 Agent。 |
| `createSummarizationMiddleware()` | 是 | 上下文过长时自动摘要。 |
| `createPatchToolCallsMiddleware()` | 是 | 修补部分不完整的工具调用。 |
| `createSkillsMiddleware()` | 配置 `skills` 后挂载 | 暴露 skill 列表，并支持按需读取。 |
| `createMemoryMiddleware()` | 配置 `memory` 后挂载 | 读取 memory 文件并注入提示词。 |

原版传入了：

```js
memory: [path.join(projectDir, "AGENTS.md")],
skills: ["/skills/"],
```

所以原版主 Agent 同时启用了 memory 和 skill。

### 自定义子 Agent 的 skill 继承规则

需要注意：自定义子 Agent 默认不会继承主 Agent 的 skill。`deepagents` 源码中明确说明，只有通用子 Agent 会继承主 Agent 的 skill：[源码](../../node_modules/deepagents/dist/index.js#L8100)。

如果某个自定义子 Agent 也需要 skill，应在其配置对象中单独添加：

```js
{
  name: "researcher",
  skills: ["/skills/web-research/"],
}
```

## 5. 调试版手动挂载了什么

调试版在 [`createPhaseMiddleware()`](../../src/debug/controlled-pipeline.mjs#L178) 中显式选择能力：

```js
return [
  createFilesystemMiddleware(...),
  createSkillsMiddleware(...),
  modelCallLimitMiddleware(...),
  toolCallLimitMiddleware(...),
];
```

| 中间件 | 是否启用 | 原因 |
| --- | --- | --- |
| 文件系统 | 是 | 阶段之间通过文件传递材料。 |
| skill | 是 | 保留可学习的 `SKILL.md` 机制。 |
| 模型调用上限 | 是 | 防止异常循环产生超长 trace。 |
| 工具调用上限 | 是 | 限制成本和执行范围。 |
| memory | 否 | 调试任务较小，暂时不需要长期上下文。 |
| todo | 否 | 阶段已经拆分，不需要再次规划复杂 todo。 |
| 子 Agent 委派 | 否 | 外层 `StateGraph` 已经负责阶段调度。 |
| 自动摘要 | 否 | 避免调试时频繁压缩上下文。 |

调试版还增加了文件权限限制：

```js
const DEBUG_PERMISSIONS = [
  { operations: ["read", "write"], paths: ["/debug_workspace/**"] },
  { operations: ["read"], paths: ["/skills-debug/**"] },
  { operations: ["read", "write"], paths: ["/**"], mode: "deny" },
];
```

对应代码位于 [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L49)。

## 6. skill 机制如何比较

### 6.1 原版

原版只需要在 `createDeepAgent()` 中声明：

```js
skills: ["/skills/"]
```

`createDeepAgent()` 会自动创建 `createSkillsMiddleware()`：[源码](../../node_modules/deepagents/dist/index.js#L8145)。

优势：

- 配置简洁。
- 自动与文件系统、子 Agent 和摘要能力组合。
- 适合让主 Agent 自主发现和选择 skill。

缺陷：

- skill 选择仍然由模型决定。
- skill 规则与 Prompt 规则可能发生冲突。
- 自定义子 Agent 不会自动继承主 Agent skill，需要单独配置。

### 6.2 调试版

调试版显式挂载 `createSkillsMiddleware()`，并在每个阶段的 Prompt 中指定必须读取哪个文件。例如调研员会读取：

```text
/skills-debug/compact-research/SKILL.md
```

对应代码位于 [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L218)。

优势：

- 仍然复用标准 skill 加载机制。
- 每个阶段使用哪个 skill 更明确。
- 调试时更容易判断问题来自 Prompt、skill 还是工具。

缺陷：

- 需要手动决定每个阶段挂载哪些 skill。
- Prompt 中指定 skill 路径会降低自主选择能力。
- 新增阶段时，需要同步维护阶段 Prompt 和中间件配置。

## 7. memory 机制如何比较

### 7.1 原版自动启用 memory

原版通过 [`memory`](../../src/agent.mjs#L211) 指定工程级 `AGENTS.md`。

`createDeepAgent()` 检测到该配置后，会自动调用 `createMemoryMiddleware()`：[源码](../../node_modules/deepagents/dist/index.js#L8175)。

memory 会在 Agent 启动时加载，并加入系统提示词。具体行为见 [`deepagents` 类型定义](../../node_modules/deepagents/dist/index.d.ts#L2191)。

优势：

- 可以复用工程级约定。
- 适合长时间演进的正式 Agent。

缺陷：

- memory 会增加提示词长度。
- 调试简单问题时，额外上下文可能让 trace 更长。
- memory 内容过多时，问题定位更困难。

### 7.2 调试版暂时没有启用 memory

调试版没有重新实现 memory，也没有主动挂载它。

如果确实需要，可以在 `createPhaseMiddleware()` 中增加：

```js
import {
  createFilesystemMiddleware,
  createMemoryMiddleware,
  createSkillsMiddleware,
} from "deepagents";

createMemoryMiddleware({
  backend,
  sources: ["/AGENTS.md"],
})
```

这仍然是在复用 `deepagents` 的实现，不需要自己编写 memory 文件读取逻辑。

## 8. 流程约束如何比较

### 8.1 原版：Prompt 主导

原版的优点是灵活。主 Agent 可以根据问题决定：

- 是否需要调研；
- 拆分几个子主题；
- 是否调用分析师；
- 是否需要读取额外文件；
- 最终报告结构。

但跨阶段流程主要依赖 Prompt。例如“最多两个调研员”和“每份报告只调用编辑一次”都写在 [`orchestratorPrompt`](../../src/agent.mjs#L140) 中。

当前代码没有：

- 调研员数量计数器；
- 第三次 `researcher` 调用拦截器；
- Editor 完成状态；
- 定稿前的 Editor gate。

因此，模型可能跳过 Editor，也可能启动额外调研任务。

### 8.2 调试版：图结构主导

调试版把阶段顺序写进 JavaScript：

```js
.addEdge(START, "research")
.addEdge("research", "draft")
.addEdge("draft", "editor_review")
.addEdge("editor_review", "finalize")
.addEdge("finalize", END)
```

对应代码位于 [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L447)。

每个节点完成后还会检查预期文件是否存在：[源码](../../src/debug/controlled-pipeline.mjs#L289)。

优势：

- Editor 无法被跳过。
- 错误能够定位到具体阶段。
- trace 更容易阅读。

缺陷：

- 灵活性降低。
- 如果问题不需要 Editor，图仍然会执行 Editor。
- 新增分支流程时，需要修改图结构。

## 9. token 与 trace 如何比较

### 9.1 原版的风险

原版适合完成复杂调研，但不适合频繁调试大型任务。

主要原因：

1. 主 Agent 可以多轮规划和委派子 Agent。
2. 子 Agent 可以继续读取文件、搜索和更新 todo。
3. `createDeepAgent()` 默认启用摘要中间件：[源码](../../node_modules/deepagents/dist/index.js#L8162)。
4. 原版将模型输入上限覆盖为 `8_000`：[agent.mjs](../../src/agent.mjs#L203)。

较小的输入阈值可能导致摘要过早触发。频繁摘要会增加调用次数，也可能压缩掉阶段约束，最终出现 Editor 被遗漏的风险。

### 9.2 调试版的控制方式

调试版使用较小的问题，并为每个阶段增加：

- 模型调用上限；
- 工具调用上限；
- LangGraph 步数上限；
- 搜索次数上限；
- 独立运行目录。

模型调用和工具调用限制位于 [`createPhaseMiddleware()`](../../src/debug/controlled-pipeline.mjs#L178)。

这使得 trace 更短，也更容易判断问题发生在哪一个阶段。

## 10. 优势与缺陷汇总

| 维度 | 原版 `createDeepAgent()` | 调试版 `StateGraph + createAgent()` |
| --- | --- | --- |
| 核心目标 | 自主完成复杂任务 | 稳定复现和排查问题 |
| 流程控制 | Prompt 为主 | JavaScript 图结构为主 |
| Editor 保证 | 可能被模型跳过 | 必须经过 Editor 节点 |
| memory | 配置后自动挂载 | 当前未启用，可手动挂载标准中间件 |
| skill | 配置后自动挂载 | 手动挂载标准中间件 |
| 子 Agent | 内置 `task` 委派 | 当前没有子 Agent 委派 |
| todo | 默认提供 | 当前未启用 |
| 自动摘要 | 默认提供 | 当前未启用 |
| 调用预算 | 主要依赖 Prompt 和递归上限 | 显式限制模型与工具调用 |
| trace 长度 | 复杂任务下较长 | 通常较短 |
| 灵活性 | 高 | 较低 |
| 调试难度 | 较高 | 较低 |
| 维护成本 | 默认能力较多，业务代码较少 | 需要显式维护图节点和中间件 |

## 11. 如何选择

### 适合使用原版的场景

使用 `createDeepAgent()`：

- 希望观察 Agent 自主规划能力；
- 问题类型变化较大；
- 需要动态拆分不同数量的子任务；
- 需要 memory、skill、todo 和子 Agent 协作；
- 可以接受更长的 trace 和更高的 token 消耗。

### 适合使用调试版的场景

使用 `StateGraph + createAgent()`：

- 正在排查流程错误；
- 需要稳定复现；
- 必须确保 Editor 执行；
- 需要严格控制搜索次数、模型调用次数和工具调用次数；
- 希望逐步理解各个中间件的职责。

## 12. 后续可采用的组合方案

如果正式版本既需要 Deep Agent 能力，又必须保证 Editor 不被跳过，可以组合两种方案：

```text
外层 StateGraph
  -> researchDeepAgent
  -> writerDeepAgent
  -> editorDeepAgent
  -> finalizeDeepAgent
```

每个节点内部使用专门配置的 `createDeepAgent()`：

- 外层 `StateGraph` 负责阶段顺序和 gate。
- 内层 `createDeepAgent()` 负责阶段内部的 memory、skill、文件系统和子 Agent 能力。
- 每个阶段只挂载必要工具和 skill，避免恢复成一个无限扩张的长任务。

这种组合方案比单纯依赖 Prompt 更可靠，也比完全手写所有能力更容易维护。

工程中已经新增了一套可运行的学习实现：

- [`hybrid-deep-pipeline.mjs`](../../src/debug/hybrid-deep-pipeline.mjs#L1)
- [`hybrid-deep-cli.mjs`](../../src/debug/hybrid-deep-cli.mjs#L1)
- [混合流水线学习文档](./hybrid-deep-agent-pipeline.md#L1)

## 13. 推荐学习顺序

建议按以下顺序阅读源码：

1. [`agent.mjs` 中的 `createDeepAgent()` 配置](../../src/agent.mjs#L207)
2. [`deepagents` 默认中间件组装逻辑](../../node_modules/deepagents/dist/index.js#L8149)
3. [`controlled-pipeline.mjs` 中的阶段中间件](../../src/debug/controlled-pipeline.mjs#L178)
4. [`controlled-pipeline.mjs` 中的三个基础 Agent](../../src/debug/controlled-pipeline.mjs#L214)
5. [`controlled-pipeline.mjs` 中的 Editor gate](../../src/debug/controlled-pipeline.mjs#L424)
6. [`controlled-pipeline.mjs` 中的固定图结构](../../src/debug/controlled-pipeline.mjs#L447)
7. [`hybrid-deep-pipeline.mjs` 中的阶段 Deep Agent 工厂](../../src/debug/hybrid-deep-pipeline.mjs#L259)
8. [`hybrid-deep-pipeline.mjs` 中的混合图结构](../../src/debug/hybrid-deep-pipeline.mjs#L718)
