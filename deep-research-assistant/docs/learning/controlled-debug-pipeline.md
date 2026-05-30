# 受控调试版 Agent 流水线

## 1. 目标

原工程适合观察 Deep Agent 的自主规划能力，但不适合频繁调试：

1. GDP 调研任务范围较大，容易产生很长的 LangSmith trace。
2. 主 Agent 依赖提示词自行规划，调研员数量、搜索次数和 Editor 阶段缺少代码级保障。
3. 模型输入上限被覆盖为 `8_000`，可能过早触发上下文摘要。
4. 历史 `findings_*.md` 文件会持续积累，可能干扰后续运行。

本方案保留原有代码，新增一套可单独运行的调试版：

- 入口：[`controlled-cli.mjs`](../../src/debug/controlled-cli.mjs#L1)
- 流水线：[`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L1)
- 精简搜索工具：[`compact-search.mjs`](../../src/debug/compact-search.mjs#L1)
- 离线验证：[`controlled-pipeline-smoke-test.mjs`](../../src/debug/controlled-pipeline-smoke-test.mjs#L1)

## 2. 运行方式

使用默认的小型测试问题：

```powershell
node src/debug/controlled-cli.mjs
```

默认问题定义在 [`DEFAULT_TEST_QUERY`](../../src/debug/controlled-pipeline.mjs#L26)：

```text
调研 Node.js 内置测试运行器 node:test 是否适合小型 JavaScript CLI 项目：
概括 3 个适用场景、2 个限制，并给出采用建议。
输出一页以内的中文简报。
```

也可以覆盖问题：

```powershell
node src/debug/controlled-cli.mjs "调研 npm workspaces 是否适合管理一个包含三个包的小型仓库，输出一页建议"
```

运行离线验证：

```powershell
node src/debug/controlled-pipeline-smoke-test.mjs
```

离线验证不调用模型 API，也不调用搜索 API。

## 3. 与原版的差异

| 维度 | 原版 | 调试版 |
| --- | --- | --- |
| 主流程 | 模型根据提示词自主规划 | LangGraph 固定阶段 |
| Editor | 提示词要求执行 | 图节点强制执行 |
| 搜索工具 | 默认可返回较多摘要 | 最多两次，每次最多三条结果 |
| 摘要策略 | `createDeepAgent()` 自动启用摘要 | 调试版不启用自动摘要 |
| 模型调用 | 主要依赖递归上限 | 每个阶段设置模型调用上限 |
| 工具调用 | 主要依赖提示词约束 | 每个阶段设置工具调用上限 |
| 工作区 | 复用 `/workspace` | 每次使用独立运行目录 |
| 技能 | 复用原技能 | 使用新建的精简技能 |

## 4. 为什么原版 trace 容易膨胀

### 4.1 测试问题过大

GDP 任务需要：

- 查找官方来源；
- 搜索多个省份的数据；
- 对比增速；
- 执行数值计算；
- 生成报告；
- 审阅和修订。

这类任务适合验收完整能力，不适合日常排查。

### 4.2 搜索规则存在冲突

原调研员提示词要求最多调用三次搜索：

- [`agent.mjs`](../../src/agent.mjs#L35)

但原 `web-research` 技能中写的是最多十次：

- [`skills/web-research/SKILL.md`](../../skills/web-research/SKILL.md#L29)

模型可能收到不一致指令。调试版没有修改旧技能，而是新建了 [`compact-research`](../../skills-debug/compact-research/SKILL.md#L1)。

### 4.3 输入上限被覆盖为 `8_000`

原版在 [`agent.mjs`](../../src/agent.mjs#L203) 中覆盖模型 profile：

```js
Object.defineProperty(chatModel, "profile", {
  get: () => ({ maxInputTokens: 8_000 }),
});
```

`createDeepAgent()` 默认带有摘要中间件。较小的输入上限会使摘要较早触发。

调试版改用基础 `createAgent()`，并且没有添加摘要中间件。由于每个阶段都有严格的模型调用和工具调用上限，调试任务应在较短上下文中结束。

## 5. 固定阶段：保证 Editor 不会被跳过

核心函数是 [`buildControlledPipeline()`](../../src/debug/controlled-pipeline.mjs#L244)。

图结构：

```text
START
  -> research
  -> draft
  -> editor_review
  -> finalize
  -> END
```

对应代码：

```js
.addEdge(START, "research")
.addEdge("research", "draft")
.addEdge("draft", "editor_review")
.addEdge("editor_review", "finalize")
.addEdge("finalize", END)
```

关键节点：

| 节点 | 源码 | 作用 |
| --- | --- | --- |
| `researchNode` | [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L252) | 调研并生成 `findings`。 |
| `draftNode` | [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L268) | 根据问题和材料写草稿。 |
| `reviewNode` | [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L285) | 强制 Editor 写入 review 文件。 |
| `finalizeNode` | [`controlled-pipeline.mjs`](../../src/debug/controlled-pipeline.mjs#L305) | 检查 Editor gate，再生成终稿。 |

### Editor gate

`finalizeNode` 首先检查：

```js
if (!state.editorCompleted) {
  throw new Error("Editor gate 阻止定稿：尚未完成 Editor 审阅");
}
```

随后确认 review 文件确实存在：

```js
assertVirtualFile(state.reviewPath, "finalize");
```

因此，Editor 不再只是 Prompt 中的一条建议，而是定稿前必须满足的代码条件。

## 6. 精简搜索工具

[`compact-search.mjs`](../../src/debug/compact-search.mjs#L1) 新增了 `compact_web_search`。

### 代码级限制

| 限制 | 默认值 | 源码 |
| --- | --- | --- |
| 总搜索次数 | `2` | [`DEFAULT_MAX_SEARCH_CALLS`](../../src/debug/compact-search.mjs#L6) |
| 单次结果数量 | `3` | [`DEFAULT_MAX_RESULTS`](../../src/debug/compact-search.mjs#L7) |
| 单条摘要长度 | `280` 字符 | [`DEFAULT_MAX_SUMMARY_CHARS`](../../src/debug/compact-search.mjs#L8) |

工具在 [`createCompactWebSearch()`](../../src/debug/compact-search.mjs#L43) 内部维护调用计数：

```js
if (completedCalls >= maxCalls) {
  return `已达到搜索次数上限：最多 ${maxCalls} 次。请使用已有结果完成调研。`;
}
```

即使模型不遵守 Prompt，也无法无限搜索。

## 7. 每个阶段的调用预算

阶段 Agent 在 [`createPhaseAgents()`](../../src/debug/controlled-pipeline.mjs#L150) 中创建。

每个阶段都使用 [`createPhaseMiddleware()`](../../src/debug/controlled-pipeline.mjs#L127) 添加：

1. 文件系统中间件；
2. 新技能目录；
3. `modelCallLimitMiddleware`；
4. `toolCallLimitMiddleware`。

当前每个阶段最多允许：

```js
maxModelCalls: 8
maxToolCalls: 7
```

目的不是精确预测 token，而是防止异常循环制造超长 trace。

## 8. 独立工作区

每次运行都会创建独立目录：

```text
debug_workspace/
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

路径创建逻辑：

- [`createRunPaths()`](../../src/debug/controlled-pipeline.mjs#L68)
- [`prepareControlledRun()`](../../src/debug/controlled-pipeline.mjs#L83)

这解决了旧 `/workspace/sources` 中历史 `findings_*.md` 持续累积的问题。

`debug_workspace/.gitignore` 会忽略运行产物。

## 9. 文件访问边界

调试版文件权限定义在 [`DEBUG_PERMISSIONS`](../../src/debug/controlled-pipeline.mjs#L33)：

```js
[
  { operations: ["read", "write"], paths: ["/debug_workspace/**"] },
  { operations: ["read"], paths: ["/skills-debug/**"] },
  { operations: ["read", "write"], paths: ["/**"], mode: "deny" },
]
```

含义：

- Agent 可以读写自己的调试工作区。
- Agent 可以读取新的调试技能。
- Agent 无法读取旧的 GDP 材料。
- Agent 无法修改技能文件。

## 10. 新增技能

原有 `skills/` 目录没有修改。调试版使用单独的 `skills-debug/`：

| 技能 | 用途 |
| --- | --- |
| [`compact-research`](../../skills-debug/compact-research/SKILL.md#L1) | 约束短调研：最多两次搜索，材料控制在 600 字内。 |
| [`concise-report-writer`](../../skills-debug/concise-report-writer/SKILL.md#L1) | 约束草稿和终稿：一页以内，只读指定文件。 |
| [`mandatory-editor-review`](../../skills-debug/mandatory-editor-review/SKILL.md#L1) | 约束 Editor：写入 review 文件后停止。 |

## 11. CLI 执行过程

[`controlled-cli.mjs`](../../src/debug/controlled-cli.mjs#L19) 执行以下步骤：

```text
读取命令行问题或默认问题
  -> 创建独立运行目录
  -> 创建受控流水线
  -> invoke()
  -> 输出阶段顺序
  -> 输出 Editor 状态
  -> 输出终稿路径
```

成功时应看到：

```text
阶段顺序: research -> draft -> editor_review -> finalize
Editor 已执行: true
```

## 12. 离线 smoke test

[`controlled-pipeline-smoke-test.mjs`](../../src/debug/controlled-pipeline-smoke-test.mjs#L1) 不调用 API。

它验证：

1. 四个阶段按照固定顺序执行；
2. `editorCompleted` 最终为 `true`；
3. 终稿文件存在；
4. 搜索结果最多保留三条；
5. 搜索摘要会被截断；
6. 测试生成的临时目录会被清理。

核心验证函数：

- [`testPipelineOrderAndEditorGate()`](../../src/debug/controlled-pipeline-smoke-test.mjs#L23)
- [`testCompactSearchFormatting()`](../../src/debug/controlled-pipeline-smoke-test.mjs#L62)

## 13. 适用范围

受控调试版适合：

- 观察一次简短 trace；
- 排查搜索、文件写入和 Editor 阶段；
- 学习 LangGraph 的显式节点和边；
- 验证代码级限制是否生效。

它不替代原版的完整自主调研能力。原版适合最终能力验收；调试版适合日常开发和问题定位。

## 14. 后续可继续演进的方向

1. 为原版增加代码级 `task` 次数限制，而不是只依赖 Prompt。
2. 为生产版恢复摘要中间件，但使用符合真实模型上下文窗口的阈值。
3. 为每个阶段记录 token 使用量，并在 LangSmith 中增加阶段标签。
4. 增加故意跳过 Editor 的负向测试，验证 gate 会拒绝定稿。
