import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { ChatOpenAI } from "@langchain/openai";
import { HumanMessage } from "@langchain/core/messages";
import { RunnableLambda } from "@langchain/core/runnables";
import {
  Command,
  END,
  START,
  StateGraph,
  isCommand,
} from "@langchain/langgraph";
import {
  createAgent,
  createMiddleware,
  modelCallLimitMiddleware,
  todoListMiddleware,
  toolCallLimitMiddleware,
} from "langchain";
import {
  createDeepAgent,
  createFilesystemMiddleware,
  createPatchToolCallsMiddleware,
  createSkillsMiddleware,
  createSummarizationMiddleware,
  FilesystemBackend,
} from "deepagents";
import { z } from "zod";

import { createCompactWebSearch } from "./compact-search.mjs";

export const projectDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);

export const DEFAULT_HYBRID_TEST_QUERY =
  "调研 Node.js 内置测试运行器 node:test 是否适合小型 JavaScript CLI 项目：概括 3 个适用场景、2 个限制，并给出采用建议。输出一页以内的中文简报。";

const HYBRID_RUNS_ROOT = "/hybrid_workspace/runs";
const HYBRID_MEMORY_PATH = "/hybrid-memory/AGENTS.md";
const RESEARCH_SKILLS_ROOT = "/skills-hybrid/research/";
const RESEARCH_COORDINATOR_SKILLS_ROOT = "/skills-hybrid/research-coordinator/";
const RESEARCH_SUBAGENT_SKILLS_ROOT = "/skills-hybrid/research-subagent/";
const WRITER_SKILLS_ROOT = "/skills-hybrid/writer/";
const EDITOR_SKILLS_ROOT = "/skills-hybrid/editor/";
export const DEFAULT_HYBRID_PHASE_RECURSION_LIMIT = 96;
export const NESTED_RESEARCH_SUBAGENT_NAMES = [
  "scenario_researcher",
  "limits_researcher",
];
export const NESTED_RESEARCH_SUBAGENT_MAX_MODEL_CALLS = 7;
export const NESTED_RESEARCH_SUBAGENT_MAX_TOOL_CALLS = 8;
export const NESTED_RESEARCH_LOCAL_STATE_KEYS = [
  "threadModelCallCount",
  "runModelCallCount",
  "threadToolCallCount",
  "runToolCallCount",
  "_summarizationEvent",
  "_summarizationSessionId",
];

const nestedResearchLocalStateKeys = new Set(NESTED_RESEARCH_LOCAL_STATE_KEYS);

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
  "HYBRID_PHASE_RECURSION_LIMIT",
  DEFAULT_HYBRID_PHASE_RECURSION_LIMIT,
);

export const HYBRID_PERMISSIONS = [
  { operations: ["read", "write"], paths: ["/hybrid_workspace/**"] },
  { operations: ["read"], paths: ["/skills-hybrid/**"] },
  { operations: ["read"], paths: ["/hybrid-memory/**"] },
  { operations: ["read", "write"], paths: ["/**"], mode: "deny" },
];

const HybridPipelineState = z.object({
  runId: z.string(),
  query: z.string(),
  questionPath: z.string(),
  scenarioFindingsPath: z.string(),
  limitsFindingsPath: z.string(),
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
export function resolveHybridVirtualPath(virtualPath) {
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
 * 为一次混合流水线运行创建稳定的虚拟文件路径集合。
 * @param {string} runId 原始运行标识；默认使用当前时间。
 * @returns {object} 清理后的运行标识、运行根目录和各阶段文件路径。
 */
export function createHybridRunPaths(runId = createRunId()) {
  const safeRunId = runId.replace(/[^a-zA-Z0-9_-]/g, "-");
  const runRoot = `${HYBRID_RUNS_ROOT}/${safeRunId}`;

  return {
    runId: safeRunId,
    runRoot,
    questionPath: `${runRoot}/sources/question.md`,
    scenarioFindingsPath: `${runRoot}/sources/findings_scenarios.md`,
    limitsFindingsPath: `${runRoot}/sources/findings_limits.md`,
    findingsPath: `${runRoot}/sources/findings_node_test.md`,
    draftPath: `${runRoot}/reports/draft_node_test.md`,
    reviewPath: `${runRoot}/reports/review_node_test.md`,
    finalPath: `${runRoot}/reports/report_node_test.md`,
  };
}

/**
 * 从父子 Agent 共享状态中移除只应属于单次嵌套执行的局部字段。
 * @param {unknown} state 候选状态对象。
 * @returns {unknown} 非对象输入会原样返回；对象输入会返回过滤后的浅拷贝。
 */
export function omitNestedResearchLocalState(state) {
  if (!state || typeof state !== "object" || Array.isArray(state)) return state;

  return Object.fromEntries(
    Object.entries(state).filter(
      ([key]) => !nestedResearchLocalStateKeys.has(key),
    ),
  );
}

/**
 * 清理 task 工具返回的 Command，避免并行子 Agent 回写 LastValue 局部通道。
 * @param {unknown} result task 工具处理器返回的值。
 * @returns {unknown} 普通返回值原样返回；Command 返回值会替换为过滤后的 Command。
 */
export function sanitizeNestedResearchTaskResult(result) {
  if (!isCommand(result) || result.update == null) return result;

  const update = Array.isArray(result.update)
    ? result.update.filter(([key]) => !nestedResearchLocalStateKeys.has(key))
    : omitNestedResearchLocalState(result.update);

  return new Command({
    graph: result.graph,
    update,
    resume: result.resume,
    goto: result.goto,
  });
}

/**
 * 创建运行目录、写入问题文件，并返回混合 StateGraph 的初始状态。
 * @param {string} query 用户提交的调研问题。
 * @param {{runId?: string}} options 可选运行标识，便于测试生成可预测目录。
 * @returns {object} 可直接传给 pipeline.invoke() 的初始状态。
 */
export function prepareHybridRun(
  query = DEFAULT_HYBRID_TEST_QUERY,
  { runId } = {},
) {
  const paths = createHybridRunPaths(runId);
  fs.mkdirSync(resolveHybridVirtualPath(`${paths.runRoot}/sources`), {
    recursive: true,
  });
  fs.mkdirSync(resolveHybridVirtualPath(`${paths.runRoot}/reports`), {
    recursive: true,
  });
  fs.writeFileSync(
    resolveHybridVirtualPath(paths.questionPath),
    `# 混合流水线调试问题\n\n${query.trim()}\n`,
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
 * 输入来自 OPENAI_API_KEY、HYBRID_PIPELINE_MODEL、OPENAI_MODEL 和 OPENAI_BASE_URL。
 * @returns {ChatOpenAI} 温度为 0 的聊天模型实例。
 * @throws {Error} 当 OPENAI_API_KEY 未配置时抛出。
 */
function createChatModel() {
  const apiKey = process.env.OPENAI_API_KEY?.trim();
  if (!apiKey) {
    throw new Error("未设置 OPENAI_API_KEY 环境变量");
  }

  const model = process.env.HYBRID_PIPELINE_MODEL?.trim()
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
 * 创建一个具有 memory、skill、文件权限和调用预算的阶段 Deep Agent。
 * @param {object} options Deep Agent 名称、模型、后端、skill、工具、Prompt、预算和子 Agent 配置。
 * @param {string} options.name Agent 名称。
 * @param {object} options.model Agent 使用的聊天模型。
 * @param {FilesystemBackend} options.backend 虚拟文件系统后端。
 * @param {string} options.skillsRoot 当前阶段可读取的 skill 根目录。
 * @param {Array<object>} options.tools 当前阶段额外开放的工具。
 * @param {string} options.systemPrompt 当前阶段角色和行为约束。
 * @param {number} options.maxModelCalls 当前阶段最多模型调用次数。
 * @param {number} options.maxToolCalls 当前阶段最多工具调用次数。
 * @param {number} options.maxTaskCalls 当前阶段最多 task 委派次数。
 * @param {Array<object>} options.subagents 当前阶段可委派的子 Agent。
 * @param {Array<object>} options.extraMiddleware 当前阶段追加的中间件。
 * @returns {object} 可被外层 StateGraph 调用的 Deep Agent。
 */
export function createPhaseDeepAgent({
  name,
  model,
  backend,
  skillsRoot,
  tools = [],
  systemPrompt,
  maxModelCalls,
  maxToolCalls,
  maxTaskCalls = 0,
  subagents = [],
  extraMiddleware = [],
}) {
  return createDeepAgent({
    name,
    model,
    backend,
    tools,
    systemPrompt,
    memory: [HYBRID_MEMORY_PATH],//每次 agent.invoke() 开始时读取文件beforeAgent() 会读取 AGENTS.md，并将内容保存到当前 Agent state 的 memoryContents 中，wrapModelCall() 会把已加载的 memory 内容追加到 SystemMessage 中，然后再调用模型。
    skills: [skillsRoot],
    permissions: HYBRID_PERMISSIONS,
    subagents,
    middleware: [
      modelCallLimitMiddleware({
        runLimit: maxModelCalls,
        exitBehavior: "error",
      }),
      toolCallLimitMiddleware({
        runLimit: maxToolCalls,
        exitBehavior: "error",
      }),
      toolCallLimitMiddleware({//仅统计 task 工具，单独限制创建子 Agent 的次数
        toolName: "task",
        runLimit: maxTaskCalls,
        exitBehavior: "error",
      }),
      ...extraMiddleware,
    ],
  });
}

/**
 * 创建嵌套调研协调员的 task 白名单和单次调用限制中间件。
 * @returns {object} 可传给 createDeepAgent() 的自定义中间件。
 */
function createNestedResearchTaskGuard() {
  const allowedTypes = new Set(NESTED_RESEARCH_SUBAGENT_NAMES);
  const usedTypes = new Set();

  return createMiddleware({
    name: "NestedResearchTaskGuardMiddleware",
    /**
     * 在每次协调员运行开始时清空已使用的子 Agent 类型。
     * @returns {void}
     */
    beforeAgent() {
      usedTypes.clear();
    },
    /**
     * 校验 task 的子 Agent 类型和调用次数，并清理 task 返回状态。
     * @param {object} request 当前工具调用请求。
     * @param {(request: object) => Promise<unknown>} handler 下一个工具调用处理器。
     * @returns {Promise<unknown>} 原始工具结果或清理后的 task Command。
     */
    async wrapToolCall(request, handler) {
      if (request.toolCall.name !== "task") {
        return handler(request);
      }

      const subagentType = request.toolCall.args?.subagent_type;
      if (!allowedTypes.has(subagentType)) {
        throw new Error(`嵌套调研不允许调用子 Agent：${subagentType}`);
      }
      if (usedTypes.has(subagentType)) {
        throw new Error(`嵌套调研子 Agent 只能调用一次：${subagentType}`);
      }

      usedTypes.add(subagentType);
      return sanitizeNestedResearchTaskResult(await handler(request));
    },
  });
}

/**
 * 创建一个具有独立局部状态的嵌套调研子 Agent。
 * @param {object} options 子 Agent 配置。
 * @param {string} options.name 子 Agent 类型名称。
 * @param {string} options.description 提供给协调员的职责说明。
 * @param {object} options.model 子 Agent 使用的聊天模型。
 * @param {FilesystemBackend} options.backend 与协调员共享的虚拟文件后端。
 * @param {string} options.systemPrompt 子 Agent 的角色和停止条件。
 * @returns {{name: string, description: string, runnable: object}} 可注册到 Deep Agent 的预编译子 Agent。
 */
function createIsolatedNestedResearchSubagent({
  name,
  description,
  model,
  backend,
  systemPrompt,
}) {
  const agent = createAgent({
    name,
    model,
    tools: [createCompactWebSearch({ maxCalls: 1 })],
    systemPrompt,
    middleware: [
      todoListMiddleware(),
      createFilesystemMiddleware({
        backend,
        permissions: HYBRID_PERMISSIONS,
      }),
      createSummarizationMiddleware({ backend }),
      createPatchToolCallsMiddleware(),
      createSkillsMiddleware({
        backend,
        sources: [RESEARCH_SUBAGENT_SKILLS_ROOT],
      }),
      modelCallLimitMiddleware({
        runLimit: NESTED_RESEARCH_SUBAGENT_MAX_MODEL_CALLS,
        exitBehavior: "error",
      }),
      toolCallLimitMiddleware({
        runLimit: NESTED_RESEARCH_SUBAGENT_MAX_TOOL_CALLS,
        exitBehavior: "error",
      }),
    ],
  });

  return {
    name,
    description,
    /**
     * 在调用子 Agent 前后过滤局部预算和摘要状态，同时保留可合并文件状态。
     * @param {object} state 从父 Agent 传入的状态。
     * @param {object} config LangGraph 调用配置。
     * @returns {Promise<object>} 过滤局部字段后的子 Agent 结果。
     */
    runnable: RunnableLambda.from(async (state, config) => {
      const isolatedInput = omitNestedResearchLocalState(state);
      const result = await agent.invoke(isolatedInput, config);
      return omitNestedResearchLocalState(result);
    }),
  };
}

/**
 * 创建场景调研员和限制调研员两个隔离的嵌套子 Agent。
 * @param {{model: object, backend: FilesystemBackend}} options 共用模型和文件后端。
 * @returns {Array<{name: string, description: string, runnable: object}>} 可注册给 research 协调员的子 Agent 列表。
 */
function createNestedResearchSubagents({ model, backend }) {
  return [
    createIsolatedNestedResearchSubagent({
      name: "scenario_researcher",
      description:
        "调研当前问题中的适用场景或主要价值。只处理场景，不分析限制。",
      model,
      backend,
      systemPrompt: [
        "你是嵌套调研子 Agent，负责调研适用场景。",
        "读取 compact-subtopic-research skill。",
        "只处理 task 描述中的一个子主题，最多搜索 1 次。",
        "将完整结果写入 task 指定文件，然后用一句话确认完成并停止。",
        "所有输出使用中文。",
      ].join("\n"),
    }),
    createIsolatedNestedResearchSubagent({
      name: "limits_researcher",
      description:
        "调研当前问题中的限制、风险和采用建议。只处理限制与建议。",
      model,
      backend,
      systemPrompt: [
        "你是嵌套调研子 Agent，负责调研限制和采用建议。",
        "读取 compact-subtopic-research skill。",
        "只处理 task 描述中的一个子主题，最多搜索 1 次。",
        "将完整结果写入 task 指定文件，然后用一句话确认完成并停止。",
        "所有输出使用中文。",
      ].join("\n"),
    }),
  ];
}

/**
 * 创建 research、writer 和 editor 三个混合流水线阶段 Deep Agent。
 * @param {{nestedResearch?: boolean}} options 是否让 research 阶段使用两个受控嵌套子 Agent。
 * @returns {{researcher: object, writer: object, editor: object}} 三个可被外层 StateGraph 调用的 Deep Agent。
 */
export function createHybridDeepPhaseAgents({ nestedResearch = false } = {}) {
  const backend = new FilesystemBackend({
    rootDir: projectDir,
    virtualMode: true,
  });
  const model = createChatModel();
  const researcher = nestedResearch // 配置是否启用子agent，默认不开启，开启后research阶段会并行调用两个子agent分别调研场景和限制，并将结果写入不同文件，最后由协调员合并结果；
    ? createPhaseDeepAgent({
        name: "hybrid_research_coordinator",
        model,
        backend,
        skillsRoot: RESEARCH_COORDINATOR_SKILLS_ROOT,
        subagents: createNestedResearchSubagents({ model, backend }),
        systemPrompt: [
          "你是混合流水线中的调研协调员 Deep Agent。",
          "读取 nested-research-coordinator skill。",
          "必须使用 task 并行委派 scenario_researcher 和 limits_researcher 各一次。",
          "等待两个子 Agent 完成后，读取它们写入的文件并合并为指定 findings 文件。",
          "不要自行联网搜索，不要调用第三次 task。",
          "所有输出使用中文。",
        ].join("\n"),
        maxModelCalls: 8,
        maxToolCalls: 10,
        maxTaskCalls: 2,
        extraMiddleware: [createNestedResearchTaskGuard()],
      })
    : createPhaseDeepAgent({
        name: "hybrid_researcher",
        model,
        backend,
        skillsRoot: RESEARCH_SKILLS_ROOT,
        tools: [createCompactWebSearch()],
        systemPrompt: [
          "你是混合流水线中的调研阶段 Deep Agent。",
          "读取 compact-research skill，并只完成当前问题的一次短调研。",
          "只使用 compact_web_search，最多搜索 2 次。",
          "将结果写入任务指定的 findings 文件后立即停止。",
          "不要调用 task 委派子 Agent；默认学习运行禁止阶段内部继续拆分任务。",
          "所有输出使用中文。",
        ].join("\n"),
        maxModelCalls: 8,
        maxToolCalls: 8,
      });

  const writer = createPhaseDeepAgent({
    name: "hybrid_writer",
    model,
    backend,
    skillsRoot: WRITER_SKILLS_ROOT,
    systemPrompt: [
      "你是混合流水线中的写作阶段 Deep Agent。",
      "读取 concise-report-writer skill，并严格区分草稿和终稿。",
      "只读取任务明确列出的文件，不要联网搜索，不要浏览其他目录。",
      "将结果写入任务指定文件后立即停止。",
      "不要调用 task 委派子 Agent；默认学习运行禁止阶段内部继续拆分任务。",
      "所有输出使用中文。",
    ].join("\n"),
    maxModelCalls: 7,
    maxToolCalls: 7,
  });

  const editor = createPhaseDeepAgent({
    name: "hybrid_editor",
    model,
    backend,
    skillsRoot: EDITOR_SKILLS_ROOT,
    systemPrompt: [
      "你是混合流水线中的 Editor 阶段 Deep Agent。",
      "读取 mandatory-editor-review skill，只审阅指定草稿，不要改写报告。",
      "必须将意见写入任务指定的 review 文件后立即停止。",
      "不要调用 task 委派子 Agent；默认学习运行禁止阶段内部继续拆分任务。",
      "所有输出使用中文。",
    ].join("\n"),
    maxModelCalls: 7,
    maxToolCalls: 7,
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
  const physicalPath = resolveHybridVirtualPath(virtualPath);
  if (!fs.existsSync(physicalPath)) {
    throw new Error(`${phaseName} 未生成预期文件：${virtualPath}`);
  }
  if (fs.statSync(physicalPath).size === 0) {
    throw new Error(`${phaseName} 生成了空文件：${virtualPath}`);
  }
}

/**
 * 使用统一配置调用一个阶段 Deep Agent，并向观察者发送开始和完成日志。
 * @param {{invoke: Function}} agent 需要执行的阶段 Deep Agent。
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
        recursionLimit: PHASE_RECURSION_LIMIT,
        runName: `hybrid_deep_pipeline:${phaseName}`,
        tags: ["hybrid-deep-pipeline", phaseName],
      },
    );
  } catch (error) {
    if (error?.lc_error_code === "GRAPH_RECURSION_LIMIT") {
      throw new Error(
        `${phaseName} 阶段达到 LangGraph 步数上限 ${PHASE_RECURSION_LIMIT}。`
          + "该阶段内部使用 createDeepAgent，默认中间件会增加图步数。"
          + "请先检查重复工具调用；确认流程合理后，可通过 "
          + "HYBRID_PHASE_RECURSION_LIMIT 调整。",
        { cause: error },
      );
    }
    throw error;
  }
  onStage(`完成阶段：${phaseName}；${getLastMessageText(result)}`);
}

/**
 * 构造固定顺序的 research、draft、editor_review 和 finalize StateGraph。
 * @param {object} options 外层图配置。
 * @param {{researcher: object, writer: object, editor: object}} options.agents 三个阶段 Deep Agent。
 * @param {(message: string) => void} options.onStage 可选阶段日志回调。
 * @param {boolean} options.nestedResearch 是否启用 research 阶段嵌套委派。
 * @returns {object} 已编译、可调用 invoke() 的混合流水线。
 * @throws {Error} 当任意必需阶段 Deep Agent 缺失时抛出。
 */
export function buildHybridDeepPipeline({
  agents,
  onStage = () => {},
  nestedResearch = false,
} = {}) {
  if (!agents?.researcher || !agents?.writer || !agents?.editor) {
    throw new Error("必须提供 researcher、writer 和 editor 三个阶段 Deep Agent");
  }

  /**
   * 执行调研阶段，并确认普通或嵌套模式要求的 findings 已写入。
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
        ...(nestedResearch
          ? [
              "必须在同一轮中并行调用两个 task，分别委派以下子 Agent：",
              `1. scenario_researcher：调研适用场景，写入 ${state.scenarioFindingsPath}`,
              `2. limits_researcher：调研限制和采用建议，写入 ${state.limitsFindingsPath}`,
              "等待两个 task 完成后，读取上述两个文件并合并结果。",
            ]
          : ["只围绕用户问题收集直接相关的信息，不要扩展主题。"]),
        `将结构化结果写入：${state.findingsPath}`,
      ].join("\n"),
      onStage,
    );
    if (nestedResearch) {
      assertVirtualFile(state.scenarioFindingsPath, "research:scenario_researcher");
      assertVirtualFile(state.limitsFindingsPath, "research:limits_researcher");
    }
    assertVirtualFile(state.findingsPath, "research");
    return { stageLog: [...state.stageLog, "research"] };
  }

  /**
   * 根据合并后的调研材料生成草稿，并确认草稿文件已写入。
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
        "审阅草稿。检查是否直接回答问题、结论是否有材料支撑、内容是否精简。",
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
      throw new Error("Editor gate 阻止定稿：尚未完成 Editor 审阅");//未对异常进行捕获处理，抛出异常直接终止后续节点的执行
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
}

/**
 * 使用真实阶段 Deep Agent 创建默认混合流水线。
 * @param {{onStage?: (message: string) => void}} options 可选阶段日志回调。
 * @returns {object} 已编译、可调用 invoke() 的普通混合流水线。
 */
export function createHybridDeepPipeline({ onStage = console.log } = {}) {
  return buildHybridDeepPipeline({
    agents: createHybridDeepPhaseAgents(),
    onStage,
  });
}

/**
 * 使用受控并行子 Agent 创建嵌套调研混合流水线。
 * @param {{onStage?: (message: string) => void}} options 可选阶段日志回调。
 * @returns {object} 已编译、可调用 invoke() 的嵌套调研混合流水线。
 */
export function createNestedHybridDeepPipeline({ onStage = console.log } = {}) {
  return buildHybridDeepPipeline({
    agents: createHybridDeepPhaseAgents({ nestedResearch: true }),
    onStage,
    nestedResearch: true,
  });
}
