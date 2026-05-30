# `agent.mjs` 学习笔记

## 1. 文件职责

[`agent.mjs`](../../src/agent.mjs#L1) 负责定义深度调研 Agent 的能力和工作规则。

它主要完成以下工作：

1. 确定工程根目录。
2. 定义三类专用子 Agent：调研员、编辑和分析师。
3. 编写主 Agent 的系统提示词。
4. 从环境变量读取模型连接配置。
5. 配置虚拟文件系统。
6. 调用 `createDeepAgent()` 创建可执行的主 Agent。

这个文件不负责执行用户问题。真正触发执行的是 [`cli.mjs` 中的 `run()`](../../src/cli.mjs#L209)。

## 2. 推荐阅读顺序

不要从提示词的第一行开始逐字阅读。先理解文件骨架：

```text
projectDir
  -> researcherSubAgent
  -> editorSubAgent
  -> analystSubAgent
  -> orchestratorPrompt
  -> createIntelligenceDeskAgent()
```

推荐按照以下顺序阅读：

1. [`createIntelligenceDeskAgent()`](../../src/agent.mjs#L161)：理解 Agent 如何被组装。
2. [`createDeepAgent({...})`](../../src/agent.mjs#L200)：理解最终传入框架的配置。
3. [`orchestratorPrompt`](../../src/agent.mjs#L106)：理解主 Agent 的工作流程。
4. [`researcherSubAgent`](../../src/agent.mjs#L25)：理解联网调研任务。
5. [`analystSubAgent`](../../src/agent.mjs#L87)：理解数值计算任务。
6. [`editorSubAgent`](../../src/agent.mjs#L58)：理解报告审阅任务。
7. 最后阅读顶部导入和工程路径。

## 3. 总体结构

可以将该文件理解为一个 Agent 配置工厂：

```js
export function createIntelligenceDeskAgent() {
  // 读取模型配置
  // 创建文件系统
  // 创建聊天模型
  // 注册主提示词和子 Agent 类型
  return createDeepAgent(...);
}
```

调用关系：

```text
cli.mjs 中的 run()
  -> createIntelligenceDeskAgent()
    -> createDeepAgent()
      -> 返回可执行的深度调研 Agent
```

## 4. 工程根目录

[`projectDir`](../../src/agent.mjs#L18) 保存当前工程的根目录：

```js
const projectDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
```

其中：

| 表达式 | 作用 |
| --- | --- |
| `import.meta.url` | 当前 `agent.mjs` 文件的 URL。 |
| `fileURLToPath(...)` | 将 URL 转为 Windows 本地路径。 |
| `path.dirname(...)` | 获取 `src` 目录。 |
| `path.resolve(..., "..")` | 从 `src` 返回上一级工程根目录。 |

`projectDir` 在两个地方使用：

1. [`FilesystemBackend`](../../src/agent.mjs#L174) 使用它确定实际文件系统根目录。
2. [`memory`](../../src/agent.mjs#L204) 使用它定位工程级 `AGENTS.md`。

该变量还会被导出给 [`cli.mjs`](../../src/agent.mjs#L210)，用于展示最终生成的文件。

## 5. 三类子 Agent

三个子 Agent 都是配置对象，不是立即运行的任务。

| 子 Agent | 位置 | 用途 |
| --- | --- | --- |
| `researcherSubAgent` | [`agent.mjs`](../../src/agent.mjs#L25) | 联网搜索并写入调研材料。 |
| `editorSubAgent` | [`agent.mjs`](../../src/agent.mjs#L58) | 审阅草稿，返回修改建议。 |
| `analystSubAgent` | [`agent.mjs`](../../src/agent.mjs#L87) | 使用 JavaScript REPL 完成数据分析。 |

每个配置对象通常包含：

| 字段 | 作用 |
| --- | --- |
| `name` | 主 Agent 调用 `task` 工具时使用的 `subagent_type`。 |
| `description` | 帮助主 Agent 判断何时使用该子 Agent。 |
| `systemPrompt` | 规定子 Agent 的角色、工作步骤和限制。 |
| `tools` | 仅向该子 Agent开放的工具。 |
| `middleware` | 向该子 Agent 增加的中间件能力。 |

### 5.1 调研员 `researcher`

[`researcherSubAgent`](../../src/agent.mjs#L25) 负责调研一个聚焦子主题。

它的主要规则：

1. 每次只负责一个子主题。
2. 最多调用三次 `web_search`。
3. 将结果整理为结构化摘要。
4. 只写入一份 `/workspace/sources/findings_*.md` 文件。
5. 写入后立即结束任务。

调研员可用的联网工具在 [`tools: [webSearch]`](../../src/agent.mjs#L54) 中注册。工具的具体实现位于 [`search.mjs`](../../src/tools/search.mjs#L90)。

### 5.2 编辑 `editor`

[`editorSubAgent`](../../src/agent.mjs#L58) 负责检查报告草稿。

它只提供审阅意见，不直接修改报告文件。主 Agent 收到建议后，再自行执行修订。

### 5.3 分析师 `analyst`

[`analystSubAgent`](../../src/agent.mjs#L87) 用于数值计算、排名、增长率和结构化数据分析。

它通过 [`createCodeInterpreterMiddleware()`](../../src/agent.mjs#L102) 获得 JavaScript REPL，可以执行计算代码。提示词要求分析师展示计算过程，不允许直接猜测数字。

## 6. 主 Agent 提示词

[`orchestratorPrompt`](../../src/agent.mjs#L106) 是主 Agent 的系统提示词。

主 Agent 的标准流程定义在 [`agent.mjs`](../../src/agent.mjs#L120)：

| 阶段 | 主要动作 | 执行者 |
| --- | --- | --- |
| 规划 | 拆解任务，保存用户问题和调研计划。 | 主 Agent |
| 调研 | 委派调研员搜索独立子主题。 | `researcher` |
| 分析 | 必要时执行数值计算。 | `analyst` |
| 起草 | 写入报告草稿。 | 主 Agent |
| 审阅 | 检查草稿并给出建议。 | `editor` |
| 定稿 | 修改草稿并生成最终报告。 | 主 Agent |

### 主 Agent 与子 Agent 的边界

提示词明确规定：

- 调研、计算和审阅可以委派给子 Agent。
- 报告起草、修订和定稿由主 Agent 自己完成。
- `web-research` 和 `report-writer` 是技能，不是子 Agent 类型。

对应规则位于 [`agent.mjs`](../../src/agent.mjs#L129)。

## 7. 子 Agent 是如何启动的

[`subagents`](../../src/agent.mjs#L206) 注册的是可调用的子 Agent 类型：

```js
subagents: [researcherSubAgent, editorSubAgent, analystSubAgent]
```

这行代码不会预先启动三个 Agent，也不会预先创建两个调研员实例。

运行期间，主 Agent 会根据任务生成类似下面的 `task` 工具调用：

```js
task({
  subagent_type: "researcher",
  description: "调研某个独立子主题，并写入指定 findings 文件",
});
```

如果需要并行调研两个主题，主 Agent 可以生成两个独立的 `task` 调用。它们复用同一个 `researcherSubAgent` 配置，但拥有不同的任务描述和独立上下文。

### “最多 2 个调研员”是什么限制

[`orchestratorPrompt`](../../src/agent.mjs#L139) 规定每份报告最多使用两个调研员，并在 [`agent.mjs`](../../src/agent.mjs#L141) 要求已有两份 `findings` 文件后不再新增调研员。

这是提示词层面的行为约束，不是 JavaScript 代码层面的硬限制。当前文件中没有调研员计数器，也没有拦截第三次 `task({ subagent_type: "researcher" })` 的校验逻辑。

## 8. Agent 工厂函数

[`createIntelligenceDeskAgent()`](../../src/agent.mjs#L161) 是整个文件最重要的函数。

### 8.1 读取环境变量

```js
const apiKey = process.env.OPENAI_API_KEY?.trim();
const model = process.env.OPENAI_MODEL?.trim() || "gpt-4o";
const baseURL = process.env.OPENAI_BASE_URL?.trim() || undefined;
```

| 环境变量 | 必需 | 作用 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 是 | 模型接口密钥。 |
| `OPENAI_MODEL` | 否 | 模型名称，未设置时使用 `gpt-4o`。 |
| `OPENAI_BASE_URL` | 否 | OpenAI 兼容接口地址。 |

如果未提供 `OPENAI_API_KEY`，函数会在 [`agent.mjs`](../../src/agent.mjs#L164) 主动抛出错误。

### 8.2 配置虚拟文件系统

[`FilesystemBackend`](../../src/agent.mjs#L174) 将工程目录映射为 Agent 可操作的工作区：

```js
const backend = new FilesystemBackend({
  rootDir: projectDir,
  virtualMode: true,
});
```

`virtualMode: true` 表示提示词中的 `/workspace/...` 等路径会由框架映射到工程目录，而不是直接操作系统根目录。

### 8.3 创建聊天模型

[`chatModel`](../../src/agent.mjs#L181) 是主 Agent 和子 Agent 使用的模型：

```js
const chatModel = new ChatOpenAI({
  model,
  temperature: 0,
  apiKey,
  ...
});
```

`temperature: 0` 用于降低输出随机性，使调研流程更稳定。

### 8.4 覆盖输入上限

[`Object.defineProperty(...)`](../../src/agent.mjs#L196) 将模型的 `maxInputTokens` 设置为 `8_000`：

```js
Object.defineProperty(chatModel, "profile", {
  get: () => ({ maxInputTokens: 8_000 }),
});
```

框架读取 `chatModel.profile` 后，会根据输入上限决定何时触发上下文压缩。

### 8.5 创建深度调研 Agent

[`createDeepAgent({...})`](../../src/agent.mjs#L200) 汇总所有配置：

| 参数 | 作用 |
| --- | --- |
| `model` | 主 Agent 使用的聊天模型。 |
| `systemPrompt` | 主 Agent 的工作规则。 |
| `backend` | Agent 可访问的虚拟文件系统。 |
| `memory` | 工程级记忆文件 `AGENTS.md`。 |
| `skills` | 技能目录 `/skills/`。 |
| `subagents` | 可按需调用的子 Agent 类型。 |

## 9. 与其他文件的关系

```text
src/cli.mjs
  -> 调用 createIntelligenceDeskAgent()

src/agent.mjs
  -> 导入 webSearch
  -> 创建主 Agent
  -> 注册 researcher、editor、analyst

src/tools/search.mjs
  -> 实现 webSearch

AGENTS.md
  -> 作为工程级记忆文件传给主 Agent
```

相关源码：

- CLI 入口：[`cli.mjs`](../../src/cli.mjs#L209)
- Agent 工厂：[`agent.mjs`](../../src/agent.mjs#L161)
- 搜索工具：[`search.mjs`](../../src/tools/search.mjs#L90)

## 10. 需要掌握的 JavaScript 语法

阅读这个文件时，优先掌握：

1. ES Module：`import` 和 `export`
2. 对象字面量：`{ name, description, systemPrompt }`
3. 模板字符串：反引号 `` `...` ``
4. 可选链：`process.env.OPENAI_API_KEY?.trim()`
5. 逻辑或默认值：`value || "gpt-4o"`
6. 条件展开对象：`...(baseURL ? {...} : {})`
7. Getter：`get: () => ({ maxInputTokens: 8_000 })`
8. 工厂函数：函数负责创建并返回配置完成的对象

## 11. 在 VS Code 中使用本笔记

1. 在 VS Code 中打开本文件。
2. 按 `Ctrl+Shift+V` 打开 Markdown 预览。
3. 点击本文中的源码链接，即可跳转到对应位置。
4. 源码调整后，行号可能变化，需要同步更新链接中的 `#L行号`。

## 12. 相关专题

- [主 Agent 与子 Agent 的任务委派流程](./subagent-task-flow.md)：详细说明 `task` 工具、任务上下文、停止条件和结果回传。
