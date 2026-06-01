import assert from "node:assert/strict";

import { AIMessage, HumanMessage } from "@langchain/core/messages";
import { RunnableLambda } from "@langchain/core/runnables";
import { StateBackend, createDeepAgent } from "deepagents";
import {
  FakeToolCallingModel,
  createMiddleware,
} from "langchain";
import { z } from "zod";

const QUESTION_PATH = "/workspace/sources/question.md";
const SCENARIO_PATH = "/workspace/sources/findings_scenarios.md";
const LIMITS_PATH = "/workspace/sources/findings_limits.md";

const childRuns = [];

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function createInitialFiles() {
  const backend = new StateBackend({ state: { files: {} } });
  const result = backend.write(
    QUESTION_PATH,
    "# 问题\n\nnode:test 是否适合小型 Node.js CLI 项目？\n",
  );
  assert.ok(result.filesUpdate);
  return result.filesUpdate;
}

function createLocalResearcher({
  name,
  description,
  outputPath,
  content,
  delayMs,
}) {
  return {
    name,
    description,
    runnable: RunnableLambda.from(async (state) => {
      const startedAt = Date.now();
      const backend = new StateBackend({ state });
      const question = backend.read(QUESTION_PATH);

      assert.equal(typeof question.content, "string");
      assert.equal(state.messages.length, 1);
      assert.equal(state.todos, undefined);

      await wait(delayMs);

      const writeResult = backend.write(outputPath, content);
      assert.ok(writeResult.filesUpdate);

      childRuns.push({
        name,
        startedAt,
        finishedAt: Date.now(),
        receivedStateKeys: Object.keys(state).sort(),
        receivedMessage: state.messages[0].content,
        inheritedParentMarker: state.parentMarker,
        readQuestion: question.content.trim(),
        outputPath,
      });

      return {
        files: writeResult.filesUpdate,
        messages: [
          new AIMessage(`${name} 已完成，结果写入 ${outputPath}`),
        ],
      };
    }),
  };
}

const scenarioResearcher = createLocalResearcher({
  name: "scenario_researcher",
  description: "只整理 node:test 的适用场景。",
  outputPath: SCENARIO_PATH,
  content: [
    "# 适用场景",
    "",
    "- 小型 Node.js CLI 可以直接使用内置测试运行器。",
    "- 无需额外安装测试框架，适合降低依赖数量。",
    "",
  ].join("\n"),
  delayMs: 120,
});

const limitsResearcher = createLocalResearcher({
  name: "limits_researcher",
  description: "只整理 node:test 的限制。",
  outputPath: LIMITS_PATH,
  content: [
    "# 限制",
    "",
    "- 团队已有成熟测试框架时，迁移需要评估插件生态。",
    "- 复杂 mock 或历史工具链可能仍依赖现有框架。",
    "",
  ].join("\n"),
  delayMs: 80,
});

const parentStateMiddleware = createMiddleware({
  name: "ParentStateDemoMiddleware",
  stateSchema: z.object({
    parentMarker: z.string().default(""),
  }),
});

const model = new FakeToolCallingModel({
  toolCalls: [
    [
      {
        name: "task",
        id: "task_scenarios",
        args: {
          subagent_type: "scenario_researcher",
          description: [
            "读取 /workspace/sources/question.md。",
            "只整理适用场景。",
            "将结果写入 /workspace/sources/findings_scenarios.md。",
          ].join("\n"),
        },
      },
      {
        name: "task",
        id: "task_limits",
        args: {
          subagent_type: "limits_researcher",
          description: [
            "读取 /workspace/sources/question.md。",
            "只整理限制。",
            "将结果写入 /workspace/sources/findings_limits.md。",
          ].join("\n"),
        },
      },
    ],
    [],
  ],
});

const agent = createDeepAgent({
  name: "offline_subagent_task_flow_demo",
  model,
  subagents: [scenarioResearcher, limitsResearcher],
  middleware: [parentStateMiddleware],
});

const result = await agent.invoke({
  messages: [
    new HumanMessage(
      "请并行调研 node:test 对小型 Node.js CLI 项目的价值与限制。",
    ),
  ],
  files: createInitialFiles(),
  todos: [
    {
      content: "父 Agent 的规划不会传给子 Agent",
      status: "in_progress",
    },
  ],
  parentMarker: "未列入默认排除列表的自定义状态会传给子 Agent",
});

const taskMessages = result.messages.filter(
  (message) => message.getType() === "tool" && message.name === "task",
);
const starts = childRuns.map((run) => run.startedAt);
const finishes = childRuns.map((run) => run.finishedAt);
const ranInParallel = Math.max(...starts) < Math.min(...finishes);

assert.equal(childRuns.length, 2);
assert.equal(taskMessages.length, 2);
assert.equal(ranInParallel, true);
assert.equal(typeof result.files[SCENARIO_PATH]?.content, "string");
assert.equal(typeof result.files[LIMITS_PATH]?.content, "string");

console.log("=== 1. 父 Agent 生成的两个 task 已由框架执行 ===");
for (const message of taskMessages) {
  console.log(`- ${message.tool_call_id}: ${message.content}`);
}

console.log("\n=== 2. 子 Agent 收到隔离后的任务上下文 ===");
for (const run of childRuns.sort((a, b) => a.name.localeCompare(b.name))) {
  console.log(`- ${run.name}`);
  console.log(`  状态字段: ${run.receivedStateKeys.join(", ")}`);
  console.log(`  唯一 HumanMessage: ${run.receivedMessage}`);
  console.log(`  可读取共享文件: ${run.readQuestion.replace(/\n/g, " | ")}`);
  console.log(`  自定义父状态: ${run.inheritedParentMarker}`);
}

console.log("\n=== 3. 两个 task 是否并行 ===");
console.log(`- ${ranInParallel ? "是" : "否"}`);

console.log("\n=== 4. files reducer 合并后的结果 ===");
for (const path of [QUESTION_PATH, SCENARIO_PATH, LIMITS_PATH]) {
  console.log(`\n--- ${path} ---`);
  console.log(result.files[path].content.trim());
}

console.log("\n离线案例执行成功。");
