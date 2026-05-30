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
const PHASE_RECURSION_LIMIT = 20;

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

function createRunId() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

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
    modelCallLimitMiddleware({
      runLimit: maxModelCalls,
      exitBehavior: "error",
    }),
    toolCallLimitMiddleware({
      runLimit: maxToolCalls,
      exitBehavior: "error",
    }),
  ];
}

function createPhaseAgents() {
  const backend = new FilesystemBackend({
    rootDir: projectDir,
    virtualMode: true,
  });
  const model = createChatModel();
  const compactWebSearch = createCompactWebSearch();

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

function getLastMessageText(result) {
  const content = result.messages?.at(-1)?.content;
  if (typeof content === "string") return content;
  return JSON.stringify(content ?? "");
}

function assertVirtualFile(virtualPath, phaseName) {
  const physicalPath = resolveVirtualPath(virtualPath);
  if (!fs.existsSync(physicalPath)) {
    throw new Error(`${phaseName} 未生成预期文件：${virtualPath}`);
  }
  if (fs.statSync(physicalPath).size === 0) {
    throw new Error(`${phaseName} 生成了空文件：${virtualPath}`);
  }
}

async function invokePhase(agent, phaseName, prompt, onStage) {
  onStage(`开始阶段：${phaseName}`);
  const result = await agent.invoke(
    { messages: [new HumanMessage(prompt)] },
    {
      recursionLimit: PHASE_RECURSION_LIMIT,
      runName: `debug_pipeline:${phaseName}`,
      tags: ["debug-pipeline", phaseName],
    },
  );
  onStage(`完成阶段：${phaseName}；${getLastMessageText(result)}`);
}

export function buildControlledPipeline({
  agents,
  onStage = () => {},
} = {}) {
  if (!agents?.researcher || !agents?.writer || !agents?.editor) {
    throw new Error("必须提供 researcher、writer 和 editor 三个阶段 Agent");
  }

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

export function createControlledPipeline({ onStage = console.log } = {}) {
  return buildControlledPipeline({
    agents: createPhaseAgents(),
    onStage,
  });
}
