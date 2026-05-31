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

function createRunId() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

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

export function omitNestedResearchLocalState(state) {
  if (!state || typeof state !== "object" || Array.isArray(state)) return state;

  return Object.fromEntries(
    Object.entries(state).filter(
      ([key]) => !nestedResearchLocalStateKeys.has(key),
    ),
  );
}

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
    memory: [HYBRID_MEMORY_PATH],
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
      toolCallLimitMiddleware({
        toolName: "task",
        runLimit: maxTaskCalls,
        exitBehavior: "error",
      }),
      ...extraMiddleware,
    ],
  });
}

function createNestedResearchTaskGuard() {
  const allowedTypes = new Set(NESTED_RESEARCH_SUBAGENT_NAMES);
  const usedTypes = new Set();

  return createMiddleware({
    name: "NestedResearchTaskGuardMiddleware",
    beforeAgent() {
      usedTypes.clear();
    },
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
    runnable: RunnableLambda.from(async (state, config) => {
      const isolatedInput = omitNestedResearchLocalState(state);
      const result = await agent.invoke(isolatedInput, config);
      return omitNestedResearchLocalState(result);
    }),
  };
}

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

export function createHybridDeepPhaseAgents({ nestedResearch = false } = {}) {
  const backend = new FilesystemBackend({
    rootDir: projectDir,
    virtualMode: true,
  });
  const model = createChatModel();
  const researcher = nestedResearch
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

function getLastMessageText(result) {
  const content = result.messages?.at(-1)?.content;
  if (typeof content === "string") return content;
  return JSON.stringify(content ?? "");
}

function assertVirtualFile(virtualPath, phaseName) {
  const physicalPath = resolveHybridVirtualPath(virtualPath);
  if (!fs.existsSync(physicalPath)) {
    throw new Error(`${phaseName} 未生成预期文件：${virtualPath}`);
  }
  if (fs.statSync(physicalPath).size === 0) {
    throw new Error(`${phaseName} 生成了空文件：${virtualPath}`);
  }
}

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

export function buildHybridDeepPipeline({
  agents,
  onStage = () => {},
  nestedResearch = false,
} = {}) {
  if (!agents?.researcher || !agents?.writer || !agents?.editor) {
    throw new Error("必须提供 researcher、writer 和 editor 三个阶段 Deep Agent");
  }

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

export function createHybridDeepPipeline({ onStage = console.log } = {}) {
  return buildHybridDeepPipeline({
    agents: createHybridDeepPhaseAgents(),
    onStage,
  });
}

export function createNestedHybridDeepPipeline({ onStage = console.log } = {}) {
  return buildHybridDeepPipeline({
    agents: createHybridDeepPhaseAgents({ nestedResearch: true }),
    onStage,
    nestedResearch: true,
  });
}
