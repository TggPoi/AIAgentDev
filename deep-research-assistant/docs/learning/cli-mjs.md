# `cli.mjs` 学习笔记

## 1. 文件职责

[`cli.mjs`](../../src/cli.mjs#L1) 是命令行入口。它负责：

1. 加载 `.env` 配置。
2. 读取用户输入的调研问题。
3. 创建并流式执行深度调研 Agent。
4. 将 Agent 的关键执行步骤打印到终端。
5. 在任务结束后列出生成的 Markdown 文件。

这个文件看起来较长，但 Agent 的核心执行逻辑集中在 [`run()`](../../src/cli.mjs#L209)。其余函数大多用于输入处理、日志展示和输出汇总。

阅读时，可以先折叠 [`cli.mjs`](../../src/cli.mjs#L328) 底部的历史运行日志。该注释块不是可执行代码。

## 2. 从入口开始阅读

不要从第一行开始逐行阅读。首先查看文件底部的 [`main()`](../../src/cli.mjs#L287)：

```js
main()
  -> printBanner()
  -> readQuery()
  -> run(query)
  -> printOutputs()
```

各函数的作用如下：

| 函数 | 作用 |
| --- | --- |
| [`printBanner()`](../../src/cli.mjs#L48) | 打印命令行标题。 |
| [`readQuery()`](../../src/cli.mjs#L56) | 优先读取命令行参数；没有参数时，通过终端交互读取问题。 |
| [`run(query)`](../../src/cli.mjs#L209) | 创建 Agent，流式执行任务，并打印关键事件。 |
| [`printOutputs()`](../../src/cli.mjs#L263) | 列出最近生成的调研材料和报告。 |

文件底部的 [`main().catch(...)`](../../src/cli.mjs#L322) 是最后一道异常处理。如果 `main()` 中存在未捕获错误，它会打印错误并结束进程。

## 3. 理解 `run()`：核心执行流程

[`run()`](../../src/cli.mjs#L209) 是最值得优先掌握的函数。

### 3.1 创建 Agent

```js
const agent = createIntelligenceDeskAgent();
```

[`createIntelligenceDeskAgent()`](../../src/agent.mjs#L161) 定义在 `agent.mjs` 中。它负责创建主 Agent、注册子 Agent，并配置虚拟文件系统。

### 3.2 创建工具调用跟踪表

```js
const pending = new Map();
const pendingEval = new Map();
```

这两个 `Map` 用于关联一次工具调用的开始和结束：

| 变量 | 记录内容 |
| --- | --- |
| `pending` | 文件工具调用，例如 `write_file`、`read_file` 和 `grep`。 |
| `pendingEval` | 分析师通过代码解释器执行的 `eval` 调用。 |

键是工具调用 ID。工具开始时使用 `set()` 保存信息，工具结束时使用 `delete()` 清理信息。

可以将其理解为：

```js
pending.set("tool-call-123", {
  name: "write_file",
  path: "/workspace/reports/draft.md",
});

// 工具完成后：
pending.delete("tool-call-123");
```

### 3.3 监听流式事件

[`agent.stream(...)`](../../src/cli.mjs#L222) 会持续返回 Agent 执行过程中的事件：

```js
for await (const [namespace, chunk] of await agent.stream(...)) {
  for (const [node, data] of Object.entries(chunk)) {
    // 根据节点类型处理事件
  }
}
```

关键变量：

| 变量 | 含义 |
| --- | --- |
| `namespace` | 当前事件所属的执行路径，用于区分主 Agent 和子 Agent。 |
| `chunk` | 一次流式更新，其中可能包含一个或多个节点。 |
| `node` | 当前节点名称。 |
| `data` | 当前节点携带的数据，例如消息和工具调用。 |

重点关注三类节点：

| 节点 | 含义 | 处理逻辑 |
| --- | --- | --- |
| `model_request` | 模型完成一次决策，可能准备调用工具。 | 记录文件工具和 `eval` 调用，并打印步骤标签。 |
| `tools` | 工具已经执行完成。 | 打印工具执行结果。 |
| `todoListMiddleware.after_model` | 模型更新了待办列表。 | 打印当前步骤标签。 |

## 4. 日志辅助函数

这些函数主要影响终端显示，不会改变 Agent 的调研逻辑。

| 函数 | 作用 |
| --- | --- |
| [`stepLabel(namespace, node)`](../../src/cli.mjs#L73) | 根据命名空间区分主 Agent 和子 Agent。 |
| [`displayPath(p)`](../../src/cli.mjs#L83) | 将虚拟工作区路径整理为适合终端展示的路径。 |
| [`pathFromArgs(name, args)`](../../src/cli.mjs#L90) | 从文件工具参数中提取目标路径或搜索描述。 |
| [`parseArgs(args)`](../../src/cli.mjs#L109) | 尝试将 JSON 字符串形式的工具参数解析为对象。 |
| [`previewText(text, maxLen)`](../../src/cli.mjs#L123) | 将长文本压缩为单行预览，并限制长度。 |
| [`trackEvalCalls(data, pendingEval)`](../../src/cli.mjs#L133) | 记录分析师准备执行的 JavaScript 代码。 |
| [`trackFileCalls(data, pending)`](../../src/cli.mjs#L155) | 记录模型即将执行的文件操作。 |
| [`logToolResults(data, pending, pendingEval)`](../../src/cli.mjs#L171) | 工具完成后打印简洁结果，并清理跟踪记录。 |

### `trackFileCalls()` 和 `logToolResults()` 的关系

工具开始前，[`trackFileCalls()`](../../src/cli.mjs#L155) 保存工具 ID 和目标路径：

```js
pending.set(tc.id, { name: tc.name, path: p });
```

工具完成后，[`logToolResults()`](../../src/cli.mjs#L171) 根据相同 ID 找到对应路径：

```js
const op = msg.tool_call_id ? pending.get(msg.tool_call_id) : undefined;
```

打印完成后删除记录：

```js
pending.delete(msg.tool_call_id);
```

## 5. 输入与输出

### 输入

[`readQuery()`](../../src/cli.mjs#L56) 支持两种输入方式。

命令行参数：

```powershell
node src/cli.mjs "调研 LangGraph 和 AutoGen 的差异"
```

交互输入：

```powershell
node src/cli.mjs
```

如果命令行参数为空，程序会提示：

```text
请输入调研主题:
```

### 输出

[`listMd(dir)`](../../src/cli.mjs#L246) 读取指定目录下的 Markdown 文件，并按修改时间倒序排列。

[`printOutputs()`](../../src/cli.mjs#L263) 使用 `listMd()` 展示：

- `workspace/sources` 中的调研材料。
- `workspace/reports` 中的报告文件。

## 6. 顶部配置项

| 配置 | 位置 | 作用 |
| --- | --- | --- |
| `projectRoot` | [`cli.mjs`](../../src/cli.mjs#L20) | 定位工程根目录和 `.env` 文件。 |
| `recursionLimit` | [`cli.mjs`](../../src/cli.mjs#L27) | 限制 Agent 图允许执行的最大递归步数，默认值为 `300`。 |
| `FILE_TOOLS` | [`cli.mjs`](../../src/cli.mjs#L30) | 声明需要打印路径的文件工具名称。 |
| `EVAL_TOOL` | [`cli.mjs`](../../src/cli.mjs#L40) | 保存代码解释器工具名称 `eval`。 |
| `PREVIEW_LEN` | [`cli.mjs`](../../src/cli.mjs#L42) | 控制 `eval` 输入代码的预览长度。 |
| `RESULT_PREVIEW_LEN` | [`cli.mjs`](../../src/cli.mjs#L44) | 控制 `eval` 执行结果的预览长度。 |

## 7. 建议的学习顺序

按照以下顺序阅读源码：

1. [`main()`](../../src/cli.mjs#L287)：掌握程序入口和总体流程。
2. [`readQuery()`](../../src/cli.mjs#L56)：理解命令行参数和交互输入。
3. [`run()`](../../src/cli.mjs#L209)：理解 Agent 的流式执行。
4. [`trackFileCalls()`](../../src/cli.mjs#L155) 和 [`logToolResults()`](../../src/cli.mjs#L171)：理解工具调用如何被跟踪。
5. [`trackEvalCalls()`](../../src/cli.mjs#L133)：理解分析师代码执行日志。
6. [`listMd()`](../../src/cli.mjs#L246) 和 [`printOutputs()`](../../src/cli.mjs#L263)：理解任务结束后的文件展示。
7. 最后再阅读顶部导入和配置项。

## 8. 需要掌握的 JavaScript 语法

阅读这个文件时，优先学习以下语法：

1. `async` / `await`
2. `for await...of`
3. `Map`
4. 数组和对象解构，例如 `const [node, data] = ...`
5. 可选链，例如 `data?.messages`
6. 空值合并运算符，例如 `value ?? []`
7. `Object.entries()`
8. `try...catch...finally`
9. 数组方法：`filter()`、`map()` 和 `sort()`

## 9. 在 VS Code 中使用本笔记

1. 在 VS Code 中打开本文件。
2. 按 `Ctrl+Shift+V` 打开 Markdown 预览。
3. 点击本文中的函数链接，即可跳转到对应源码位置。
4. 在 Markdown 源码编辑页面中，也可以按住 `Ctrl` 并点击链接。

源码调整后，行号可能发生变化。如果链接跳转位置不准确，需要同步更新链接中的 `#L行号`。
