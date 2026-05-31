import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ChatOpenAI } from "@langchain/openai";
import { HumanMessage } from "@langchain/core/messages";
import { END, START, StateGraph } from "@langchain/langgraph";
import {
  createAgent,
  modelCallLimitMiddleware,
  toolCallLimitMiddleware,
} from "langchain";
import {
  createFilesystemMiddleware,
  createSkillsMiddleware,
  FilesystemBackend,
} from "deepagents";
import { z } from "zod";

import { createCompactWebSearch } from "./compact-search.mjs";

export const projectDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);

export const DEFAULT_TEST_QUERY =
  "调研 Node.js 内置测试运行器 node:test 是否适合小型 JavaScript CLI 项目：概括 3 个适用场景、2 个限制，并给出采用建议。输出一页以内的中文简报。";

const DEBUG_RUNS_ROOT = "/debug_workspace/runs";
const DEBUG_SKILLS_ROOT = "/skills-debug/";
export const DEFAULT_PHASE_RECURSION_LIMIT = 64;//`recursionLimit` 统计 LangGraph 子图执行步数。因此，`recursionLimit: 20` 并不表示允许调用模型二十次。调研阶段需要读取技能、读取问题、搜索一至两次并写入文件，`20` 个图步数可能不足。

/**
 * 读取正整数环境变量，并在变量缺失或非法时返回回退值。
 * @param {string} name 环境变量名称。
 * @param {number} fallback 环境变量不可用时采用的默认值。
 * @returns {number} 可用于预算配置的正整数。
 */
function readPositiveIntegerEnv(name, fallback) {
  const parsed = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

const PHASE_RECURSION_LIMIT = readPositiveIntegerEnv(
  "DEBUG_PHASE_RECURSION_LIMIT",
  DEFAULT_PHASE_RECURSION_LIMIT,
);
//Agent 可以读写自己的调试工作区，可以读取新的调试技能。
const DEBUG_PERMISSIONS = [
  { operations: ["read", "write"], paths: ["/debug_workspace/**"] },
  { operations: ["read"], paths: ["/skills-debug/**"] },
  { operations: ["read", "write"], paths: ["/**"], mode: "deny" },
];

const PipelineState = z.object({
  runId: z.string(),
  query: z.string(),
  questionPath: z.string(),
  findingsPath: z.string(),
  draftPath: z.string(),
  reviewPath: z.string(),
  finalPath: z.string(),
  stageLog: z.array(z.string()).default(() => []),
  editorCompleted: z.boolean().default(false),
});

/**
 * 使用当前时间生成适合作为目录名的运行标识。
 * @returns {string} 已移除冒号和小数点的 ISO 时间字符串。
 */
function createRunId() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

/**
 * 将以斜杠开头的虚拟路径解析为工程目录内的本地绝对路径。
 * @param {string} virtualPath Agent 文件系统使用的虚拟路径。
 * @returns {string} 位于 projectDir 内的本地绝对路径。
 * @throws {Error} 当路径不是绝对虚拟路径，或解析后逃逸出工程目录时抛出。
 */
export function resolveVirtualPath(virtualPath) {
  if (!virtualPath.startsWith("/")) {
    throw new Error(`虚拟路径必须以 / 开头：${virtualPath}`);
  }

  const resolved = path.resolve(projectDir, `.${virtualPath}`);
  const relative = path.relative(projectDir, resolved);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`虚拟路径超出工程目录：${virtualPath}`);
  }
  return resolved;
}

/**
 * 为一次受控流水线运行创建稳定的虚拟文件路径集合。避免每次运行所有的文件都在一个目录下，使用时间戳作为文件目录的 名称，例如：debug_workspace\runs\2026-05-30T13-17-02-907Z
 * @param {string} runId 原始运行标识；默认使用当前时间。
 * @returns {{runId: string, runRoot: string, questionPath: string, findingsPath: string, draftPath: string, reviewPath: string, finalPath: string}}
 * 清理后的运行标识、运行根目录和各阶段文件路径。
 */
export function createRunPaths(runId = createRunId()) {
  const safeRunId = runId.replace(/[^a-zA-Z0-9_-]/g, "-");
  const runRoot = `${DEBUG_RUNS_ROOT}/${safeRunId}`;

  return {
    runId: safeRunId,
    runRoot,
    questionPath: `${runRoot}/sources/question.md`,
    findingsPath: `${runRoot}/sources/findings_node_test.md`,
    draftPath: `${runRoot}/reports/draft_node_test.md`,
    reviewPath: `${runRoot}/reports/review_node_test.md`,
    finalPath: `${runRoot}/reports/report_node_test.md`,
  };
}

/**
 * 初始化agent写入文件时需要使用到的 运行目录（debug_workspace\runs\{runId}）、写入问题文件，并返回外层 StateGraph 的初始状态。
 * @param {string} query 用户提交的调研问题。
 * @param {{runId?: string}} options 可选运行标识，便于测试生成可预测目录。
 * @returns {{runId: string, runRoot: string, query: string, questionPath: string, findingsPath: string, draftPath: string, reviewPath: string, finalPath: string, stageLog: string[], editorCompleted: boolean}}
 * 可直接传给 pipeline.invoke() 的初始状态。
 */
export function prepareControlledRun(
  query = DEFAULT_TEST_QUERY,
  { runId } = {},
) {
  const paths = createRunPaths(runId);
  fs.mkdirSync(resolveVirtualPath(`${paths.runRoot}/sources`), {
    recursive: true,
  });
  fs.mkdirSync(resolveVirtualPath(`${paths.runRoot}/reports`), {
    recursive: true,
  });
  fs.writeFileSync(
    resolveVirtualPath(paths.questionPath),
    `# 调试问题\n\n${query.trim()}\n`,
    "utf8",
  );

  return {
    ...paths,
    query: query.trim(),
    stageLog: [],
    editorCompleted: false,
  };
}

/**
 * 根据环境变量创建供各阶段共用的 ChatOpenAI 模型。
 * 输入来自 OPENAI_API_KEY、DEBUG_PIPELINE_MODEL、OPENAI_MODEL 和 OPENAI_BASE_URL。
 * @returns {ChatOpenAI} 温度为 0 的聊天模型实例。
 * @throws {Error} 当 OPENAI_API_KEY 未配置时抛出。
 */
function createChatModel() {
  const apiKey = process.env.OPENAI_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("未设置 OPENAI_API_KEY 环境变量");
  }

  const model = process.env.DEBUG_PIPELINE_MODEL?.trim()
    || process.env.OPENAI_MODEL?.trim()
    || "gpt-4o";
  const baseURL = process.env.OPENAI_BASE_URL?.trim() || undefined;

  return new ChatOpenAI({
    model,
    temperature: 0,
    apiKey,
    ...(baseURL ? { configuration: { baseURL } } : {}),
  });
}

/**
 * 为单个阶段创建文件、skill、模型调用预算和工具调用预算中间件。
 * @param {{backend: FilesystemBackend, maxModelCalls: number, maxToolCalls: number}} options
 * 阶段共享的文件后端，以及模型和工具调用次数上限。
 * @returns {Array<object>} 可传给 createAgent() 的中间件数组。
 */
function createPhaseMiddleware({ backend, maxModelCalls, maxToolCalls }) {
  return [
    createFilesystemMiddleware({
      backend,
      permissions: DEBUG_PERMISSIONS,
      toolTokenLimitBeforeEvict: 4_000,
      humanMessageTokenLimitBeforeEvict: 4_000,
    }),
    createSkillsMiddleware({
      backend,
      sources: [DEBUG_SKILLS_ROOT],
    }),
    modelCallLimitMiddleware({//限制模型调用次数，也就是 Agent 最多可以向 LLM 请求多少次回复
      runLimit: maxModelCalls,//最多允许调用模型 8 次；threadLimit 整个对话线程累计允许的最大调用次数。当前代码没有设置
      exitBehavior: "error",//超限后的处理方式。"error" 表示抛出异常；默认 "end" 表示结束 Agent 并返回提示消息。
    }),
    toolCallLimitMiddleware({//限制工具调用次数
      runLimit: maxToolCalls,//每次阶段执行最多允许 7 次工具调用
      exitBehavior: "error",//"error"：超限后抛异常；"continue"：阻止该次工具调用并让模型继续处理；"end"：立即终止 Agent。默认值是 "continue"。 
    }),//toolName 可选。只限制指定工具，例如 { toolName: "compact_web_search", runLimit: 2 }。未设置时统计所有工具。
  ];
}

/**
 * 创建 research、writer 和 editor 三个受控阶段 Agent。
 * 输入来自环境变量、工程目录和调试 skill；输出 Agent 共享文件后端和模型配置。
 * @returns {{researcher: object, writer: object, editor: object}} 三个可被外层 StateGraph 调用的 Agent。
 */
function createPhaseAgents() {
  const backend = new FilesystemBackend({
    rootDir: projectDir,
    virtualMode: true,
  });
  const model = createChatModel();
  const compactWebSearch = createCompactWebSearch();
  // research 阶段的 Agent 具有联网搜索工具；writer 和 editor 仅能读写文件。
  const researcher = createAgent({
    name: "debug_researcher",
    model,
    tools: [compactWebSearch],
    systemPrompt: [
      "你是调试版调研员。只完成一个小型研究任务。",
      "开始时读取 /skills-debug/compact-research/SKILL.md，并严格遵守。",
      "只使用 compact_web_search，最多搜索 2 次。不要扩展主题。",
      "将完整结果写入任务指定的 findings 文件，然后用一句话确认完成并停止。",
      "所有输出使用中文。",
    ].join("\n"),
    middleware: createPhaseMiddleware({
      backend,
      maxModelCalls: 8,
      maxToolCalls: 7,
    }),
  });
  // writer 和 editor 阶段的 Agent 不具备联网工具，专注于文件读写。
  const writer = createAgent({
    name: "debug_writer",
    model,
    tools: [],
    systemPrompt: [
      "你是调试版简报写作者。",
      "开始时读取 /skills-debug/concise-report-writer/SKILL.md，并严格遵守。",
      "只读取任务明确列出的文件。不要联网搜索，不要浏览其他目录。",
      "将结果写入任务指定文件，然后用一句话确认完成并停止。",
      "所有输出使用中文。",
    ].join("\n"),
    middleware: createPhaseMiddleware({
      backend,
      maxModelCalls: 8,
      maxToolCalls: 7,
    }),
  });
  // editor 阶段的 Agent 需要审阅草稿并给出修改意见，因此允许写 review 文件，但不允许其他写操作。
  const editor = createAgent({
    name: "debug_editor",
    model,
    tools: [],
    systemPrompt: [
      "你是调试版 Editor。",
      "开始时读取 /skills-debug/mandatory-editor-review/SKILL.md，并严格遵守。",
      "只读取任务明确列出的文件。不要联网搜索，不要修改草稿。",
      "必须将审阅意见写入任务指定 review 文件，然后用一句话确认完成并停止。",
      "所有输出使用中文。",
    ].join("\n"),
    middleware: createPhaseMiddleware({
      backend,
      maxModelCalls: 8,
      maxToolCalls: 7,
    }),
  });

  return { researcher, writer, editor };
}

/**
 * 将 Agent 最后一条消息规范化为适合阶段日志展示的文本。
 * @param {{messages?: Array<{content?: unknown}>}} result Agent 调用返回的状态。
 * @returns {string} 最后一条消息的文本或 JSON 字符串。
 */
function getLastMessageText(result) {
  const content = result.messages?.at(-1)?.content;
  if (typeof content === "string") return content;
  return JSON.stringify(content ?? "");
}

/**
 * 断言阶段输出文件存在且不是空文件。
 * @param {string} virtualPath 需要检查的虚拟文件路径。
 * @param {string} phaseName 用于错误信息的阶段名称。
 * @returns {void}
 * @throws {Error} 当文件不存在或为空时抛出。
 */
function assertVirtualFile(virtualPath, phaseName) {
  const physicalPath = resolveVirtualPath(virtualPath);
  if (!fs.existsSync(physicalPath)) {
    throw new Error(`${phaseName} 未生成预期文件：${virtualPath}`);
  }
  if (fs.statSync(physicalPath).size === 0) {
    throw new Error(`${phaseName} 生成了空文件：${virtualPath}`);
  }
}

/**
 * 使用统一配置调用一个阶段 Agent，并向观察者发送开始和完成日志。
 * @param {{invoke: Function}} agent 需要执行的阶段 Agent。
 * @param {string} phaseName 阶段名称，用于 trace 和错误信息。
 * @param {string} prompt 当前阶段收到的任务说明。
 * @param {(message: string) => void} onStage 阶段日志回调。
 * @returns {Promise<void>} Agent 完成后结束；阶段产物由 Agent 写入文件。
 * @throws {Error} 将 LangGraph 递归上限错误转换为包含调参提示的错误。
 */
async function invokePhase(agent, phaseName, prompt, onStage) {
  onStage(`开始阶段：${phaseName}`);
  let result;
  try {
    result = await agent.invoke(
      { messages: [new HumanMessage(prompt)] },
      {
        recursionLimit: PHASE_RECURSION_LIMIT,//限制本次 LangGraph 执行的最大图节点步数。默认值来自 DEBUG_PHASE_RECURSION_LIMIT 环境变量，未设置时为 64。
        runName: `debug_pipeline:${phaseName}`,//给本次运行设置名称，例如 debug_pipeline:research。主要用于 LangSmith trace 和日志定位。
        tags: ["debug-pipeline", phaseName],//给本次运行添加标签，例如 ["debug-pipeline", "research"]。方便在 trace 平台中过滤和分类运行记录。
      },
    );
  } catch (error) {
    if (error?.lc_error_code === "GRAPH_RECURSION_LIMIT") {
      throw new Error(
        `${phaseName} 阶段达到 LangGraph 步数上限 ${PHASE_RECURSION_LIMIT}。`
          + "该上限统计模型节点、工具节点和中间件节点，不等于模型调用次数。"
          + "请先检查是否存在重复工具调用；确认流程合理后，可通过 "
          + "DEBUG_PHASE_RECURSION_LIMIT 调整。",
        { cause: error },
      );
    }
    throw error;
  }
  onStage(`完成阶段：${phaseName}；${getLastMessageText(result)}`);
}

/**
 * 构造固定顺序的 research、draft、editor_review 和 finalize StateGraph。
 * @param {{agents: {researcher: object, writer: object, editor: object}, onStage?: (message: string) => void}} options
 * 三个阶段 Agent 和可选阶段日志回调。
 * @returns {object} 已编译、可调用 invoke() 的受控流水线。
 * @throws {Error} 当任意必需阶段 Agent 缺失时抛出。
 */
export function buildControlledPipeline({
  agents,
  onStage = () => {},
} = {}) {
  if (!agents?.researcher || !agents?.writer || !agents?.editor) {
    throw new Error("必须提供 researcher、writer 和 editor 三个阶段 Agent");
  }

  /**
   * 执行调研阶段，并确认结构化 findings 已写入。
   * @param {object} state 当前流水线状态。
   * @returns {Promise<{stageLog: string[]}>} 追加 research 后的阶段日志更新。
   */
  async function researchNode(state) {
    await invokePhase(
      agents.researcher,
      "research",
      [
        `用户问题：${state.query}`,
        `读取问题文件：${state.questionPath}`,
        "只调研 node:test 的适用场景、限制和采用建议。",
        `将结构化结果写入：${state.findingsPath}`,
      ].join("\n"),
      onStage,
    );
    assertVirtualFile(state.findingsPath, "research");
    return { stageLog: [...state.stageLog, "research"] };
  }

  /**
   * 根据调研材料生成草稿，并确认草稿文件已写入。
   * @param {object} state 当前流水线状态。
   * @returns {Promise<{stageLog: string[]}>} 追加 draft 后的阶段日志更新。
   */
  async function draftNode(state) {
    await invokePhase(
      agents.writer,
      "draft",
      [
        "根据问题和调研材料撰写一页以内的中文简报。",
        `读取问题：${state.questionPath}`,
        `读取调研材料：${state.findingsPath}`,
        `将草稿写入：${state.draftPath}`,
        "此阶段只写草稿，不要写终稿。",
      ].join("\n"),
      onStage,
    );
    assertVirtualFile(state.draftPath, "draft");
    return { stageLog: [...state.stageLog, "draft"] };
  }

  /**
   * 调用 Editor 审阅草稿，并在 review 文件存在后打开定稿 gate。
   * @param {object} state 当前流水线状态。
   * @returns {Promise<{stageLog: string[], editorCompleted: boolean}>} 阶段日志和 Editor 完成标记。
   */
  async function reviewNode(state) {
    await invokePhase(
      agents.editor,
      "editor_review",
      [
        "审阅草稿。检查是否直接回答问题、结论是否有调研材料支撑、内容是否精简。",
        `读取问题：${state.questionPath}`,
        `读取调研材料：${state.findingsPath}`,
        `读取草稿：${state.draftPath}`,
        `将审阅意见写入：${state.reviewPath}`,
      ].join("\n"),
      onStage,
    );
    assertVirtualFile(state.reviewPath, "editor_review");
    return {
      stageLog: [...state.stageLog, "editor_review"],
      editorCompleted: true,
    };
  }

  /**
   * 在 Editor gate 通过后生成终稿，并确认终稿文件已写入。
   * @param {object} state 当前流水线状态。
   * @returns {Promise<{stageLog: string[]}>} 追加 finalize 后的阶段日志更新。
   * @throws {Error} 当 Editor 尚未完成或 review 文件缺失时抛出。
   */
  async function finalizeNode(state) {
    if (!state.editorCompleted) {
      throw new Error("Editor gate 阻止定稿：尚未完成 Editor 审阅");
    }
    assertVirtualFile(state.reviewPath, "finalize");

    await invokePhase(
      agents.writer,
      "finalize",
      [
        "根据 Editor 审阅意见修订草稿并生成终稿。",
        `读取问题：${state.questionPath}`,
        `读取草稿：${state.draftPath}`,
        `读取审阅意见：${state.reviewPath}`,
        `将终稿写入：${state.finalPath}`,
        "终稿控制在一页以内。完成后停止。",
      ].join("\n"),
      onStage,
    );
    assertVirtualFile(state.finalPath, "finalize");
    return { stageLog: [...state.stageLog, "finalize"] };
  }

  return new StateGraph(PipelineState)
    .addNode("research", researchNode)
    .addNode("draft", draftNode)
    .addNode("editor_review", reviewNode)
    .addNode("finalize", finalizeNode)
    .addEdge(START, "research")
    .addEdge("research", "draft")
    .addEdge("draft", "editor_review")
    .addEdge("editor_review", "finalize")
    .addEdge("finalize", END)
    .compile({ name: "controlled_debug_pipeline" });
}

/**
 * 使用真实阶段 Agent 创建默认受控流水线。
 * @param {{onStage?: (message: string) => void}} options 可选阶段日志回调函数。
 * @returns {object} 已编译、可调用 invoke() 的受控流水线。
 */
export function createControlledPipeline({ onStage = console.log } = {}) {
  return buildControlledPipeline({
    agents: createPhaseAgents(),
    onStage,
  });
}

/*
{ onStage = console.log } = {} 

这是 JavaScript 的“参数解构 + 默认值”写法：

```js
export function createControlledPipeline({ onStage = console.log } = {}) {
  // ...
}
```

它等价于更容易理解的写法：

```js
function createControlledPipeline(options = {}) {
  const { onStage = console.log } = options;

  // 这里可以使用 onStage
}
```

可以拆成两层理解。

**第一层：`= {}`**
```js
function createControlledPipeline(options = {})
```

调用函数时可以不传参数：

```js
createControlledPipeline();
```

此时使用空对象 `{}`，避免解构 `undefined` 导致报错。


**第二层：`{ onStage = console.log }`**
从参数对象中 解构 取出 `onStage` 属性：

```js
const { onStage = console.log } = options;
```

如果调用方没有提供 `onStage`，则默认使用 `console.log`。
  = console.log 是默认值。如果 options.onStage 为 undefined，则使用 console.log

也就是说如果调用时没有提供 onStage，options里面就是一个 {} 空对象，解构时 onStage 就是 undefined，所以创建 const { onStage = console.log } 对象时 会使用默认值 console.log。

*/


/*
**不同调用方式**
```js
// 使用默认值 console.log
createControlledPipeline();

// 同样使用默认值 console.log
createControlledPipeline({});

// 使用自定义函数
createControlledPipeline({
  onStage: (message) => {
    console.log(`[阶段日志] ${message}`);
  },
});

// 关闭阶段日志
createControlledPipeline({
  onStage: () => {},
});
```

当前函数随后把 `onStage` 传给 `buildControlledPipeline()`：

```js
return buildControlledPipeline({
  agents: createPhaseAgents(),
  onStage,
});
```

执行每个阶段时，[`invokePhase()`](D:/AI_Agent_Project/deep-research-assistant/src/debug/controlled-pipeline.mjs:308) 会调用它：

```js
onStage(`开始阶段：${phaseName}`);
```

因此，这个参数本质上是一个可选的日志回调函数。
*/
