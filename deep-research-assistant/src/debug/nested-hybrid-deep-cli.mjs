import { config as loadEnv } from "dotenv";
import path from "node:path";

import {
  createNestedHybridDeepPipeline,
  DEFAULT_HYBRID_TEST_QUERY,
  prepareHybridRun,
  projectDir,
  resolveHybridVirtualPath,
} from "./hybrid-deep-pipeline.mjs";

loadEnv({ path: path.join(projectDir, ".env") });

/**
 * 读取命令行中的用户问题；未传参数时使用混合流水线默认问题。
 * @returns {string} 将作为嵌套流水线输入的完整问题文本。
 */
function readQuery() {
  const fromArgs = process.argv.slice(2).join(" ").trim();
  return fromArgs || DEFAULT_HYBRID_TEST_QUERY;
}

/**
 * 创建并执行允许 research 阶段并行委派子 Agent 的混合流水线。
 * 输入来自命令行参数和 .env 环境变量；输出为控制台日志以及子 Agent 和终稿文件路径。
 * @returns {Promise<void>} 流水线执行和日志输出完成后结束。
 */
async function main() {
  const query = readQuery();
  const initialState = prepareHybridRun(query);

  console.log("嵌套子 Agent 测试流水线");
  console.log("research 协调员将委派 scenario_researcher 和 limits_researcher");
  console.log(`runId: ${initialState.runId}`);
  console.log(`query: ${query}\n`);

  const pipeline = createNestedHybridDeepPipeline({
    onStage: (message) => console.log(`[nested-hybrid] ${message}`),
  });
  const result = await pipeline.invoke(initialState, {
    recursionLimit: 10,
    runName: "nested_hybrid_deep_agent_pipeline",
    tags: ["hybrid-deep-pipeline", "nested-subagents"],
  });

  console.log("\n阶段顺序:", result.stageLog.join(" -> "));
  console.log("Editor 已执行:", result.editorCompleted);
  console.log("子 Agent 场景材料:", resolveHybridVirtualPath(result.scenarioFindingsPath));
  console.log("子 Agent 限制材料:", resolveHybridVirtualPath(result.limitsFindingsPath));
  console.log("合并调研材料:", resolveHybridVirtualPath(result.findingsPath));
  console.log("终稿本地路径:", resolveHybridVirtualPath(result.finalPath));
}

main().catch((error) => {
  console.error("\n嵌套子 Agent 测试失败：", error);
  process.exit(1);
});

/*
PS D:\AI_Agent_Project\deep-research-assistant> node src/debug/nested-hybrid-deep-cli.mjs
◇ injected env (16) from .env // tip: ◈ secrets for agents [www.dotenvx.com]
嵌套子 Agent 测试流水线
research 协调员将委派 scenario_researcher 和 limits_researcher
runId: 2026-05-30T14-18-08-456Z
query: 调研 Node.js 内置测试运行器 node:test 是否适合小型 JavaScript CLI 项目：概括 3 个适用场景、2 个限制，并给出采用建议。输出一页以内的中文简报。

[nested-hybrid] 开始阶段：research

嵌套子 Agent 测试失败： InvalidUpdateError: Invalid update for channel "threadModelCallCount" with values [6,6]: LastValue can only receive one value per step.

Troubleshooting URL: https://docs.langchain.com/oss/javascript/langgraph/INVALID_CONCURRENT_GRAPH_UPDATE/

    at _applyWrites (file:///D:/AI_Agent_Project/deep-research-assistant/node_modules/.pnpm/@langchain+langgraph@1.3.2__bf17d67a14c3b5b5d8fdc349f962b034/node_modules/@langchain/langgraph/dist/pregel/algo.js:120:26)
    at PregelLoop.tick (file:///D:/AI_Agent_Project/deep-research-assistant/node_modules/.pnpm/@langchain+langgraph@1.3.2__bf17d67a14c3b5b5d8fdc349f962b034/node_modules/@langchain/langgraph/dist/pregel/loop.js:332:27)
    at CompiledStateGraph._runLoop (file:///D:/AI_Agent_Project/deep-research-assistant/node_modules/.pnpm/@langchain+langgraph@1.3.2__bf17d67a14c3b5b5d8fdc349f962b034/node_modules/@langchain/langgraph/dist/pregel/index.js:1188:22)
    at process.processTicksAndRejections (node:internal/process/task_queues:104:5)
    at async createAndRunLoop (file:///D:/AI_Agent_Project/deep-research-assistant/node_modules/.pnpm/@langchain+langgraph@1.3.2__bf17d67a14c3b5b5d8fdc349f962b034/node_modules/@langchain/langgraph/dist/pregel/index.js:1086:5) {
  lc_error_code: 'INVALID_CONCURRENT_GRAPH_UPDATE',
  pregelTaskId: '15e86766-9ab3-5368-946b-fd0eb7538073'
}
PS D:\AI_Agent_Project\deep-research-assistant> 
 *  History restored 

PS D:\AI_Agent_Project\deep-research-assistant> node src/debug/nested-hybrid-deep-cli.mjs
◇ injected env (16) from .env // tip: ◈ encrypted .env [www.dotenvx.com]
嵌套子 Agent 测试流水线
research 协调员将委派 scenario_researcher 和 limits_researcher
runId: 2026-05-31T04-31-06-707Z
query: 调研 Node.js 内置测试运行器 node:test 是否适合小型 JavaScript CLI 项目：概括 3 个适用场景、2 个限制，并给出采用建议。输出一页以内的中文简报。

[nested-hybrid] 开始阶段：research

嵌套子 Agent 测试失败： InvalidUpdateError: Invalid update for channel "threadModelCallCount" with values [5,4]: LastValue can only receive one value per step.

Troubleshooting URL: https://docs.langchain.com/oss/javascript/langgraph/INVALID_CONCURRENT_GRAPH_UPDATE/

    at _applyWrites (file:///D:/AI_Agent_Project/deep-research-assistant/node_modules/.pnpm/@langchain+langgraph@1.3.2__bf17d67a14c3b5b5d8fdc349f962b034/node_modules/@langchain/langgraph/dist/pregel/algo.js:120:26)
    at PregelLoop.tick (file:///D:/AI_Agent_Project/deep-research-assistant/node_modules/.pnpm/@langchain+langgraph@1.3.2__bf17d67a14c3b5b5d8fdc349f962b034/node_modules/@langchain/langgraph/dist/pregel/loop.js:332:27)dist/pregel/index.js:1188:22)
    at process.processTicksAndRejections (node:internal/process/task_queues:104:5)
    at async createAndRunLoop (file:///D:/AI_Agent_Project/deep-research-assistant/node_modules/.pnpm/@langchain+langgraph@1.3.2__bf17d67a14c3b5b5d8fdc349f962b034/node_modules/@langchain/langgraph/dist/pregel/index.js:1086:5) {
  lc_error_code: 'INVALID_CONCURRENT_GRAPH_UPDATE',
  pregelTaskId: '10c61f40-8edf-50d2-a204-e17957848aa3'
}
PS D:\AI_Agent_Project\deep-research-assistant> node src/debug/nested-hybrid-deep-cli.mjs
◇ injected env (16) from .env // tip: ⌁ auth for agents [www.vestauth.com]
嵌套子 Agent 测试流水线
research 协调员将委派 scenario_researcher 和 limits_researcher
runId: 2026-05-31T04-43-47-379Z
query: 调研 Node.js 内置测试运行器 node:test 是否适合小型 JavaScript CLI 项目：概括 3 个适用场景、2 个限制，并给出采用建议。输出一页以内的中文简报。

[nested-hybrid] 开始阶段：research
[nested-hybrid] 完成阶段：research；已完成调研并生成简报。

**任务执行摘要：**
1. ✅ 并行委派 `scenario_researcher` 调研适用场景 → 写入 `findings_scenarios.md`
2. ✅ 并行委派 `limits_researcher` 调研限制与建议 → 写入 `findings_limits.md`
3. ✅ 合并两份报告为结构化简报 → 写入 `findings_node_test.md`

**核心结论：**
- **3 个适用场景**：快速原型验证、CI/CD 自动化测试、依赖隔离 Mock 测试
- **2 个限制**：生态系统不成熟、开发者工具链不完善
- **建议**：仅当项目保持轻量且测试需求简单时采用 `node:test`；若预期增长或需要覆盖率/快照测试等功能，建议使用 Jest/Vitest
[nested-hybrid] 开始阶段：draft
[nested-hybrid] 完成阶段：draft；草稿已写入 `/hybrid_workspace/runs/2026-05-31T04-43-47-379Z/reports/draft_node_test.md`。

简报包含：
- 3 个适用场景：快速原型验证、CI/CD 集成、函数 Mock 与依赖隔离
- 2 个主要限制：生态系统不足、开发者体验不完善
- 采用建议：根据项目特征给出决策表格
[nested-hybrid] 开始阶段：editor_review
[nested-hybrid] 完成阶段：editor_review；审阅完成。意见已写入 `/hybrid_workspace/runs/2026-05-31T04-43-47-379Z/reports/review_node_test.md`。

**结论**：草稿质量良好，直接回答了问题、结论有材料支撑、内容精简，无需修改。
[nested-hybrid] 开始阶段：finalize
[nested-hybrid] 完成阶段：finalize；终稿已写入 `/hybrid_workspace/runs/2026-05-31T04-43-47-379Z/reports/report_node_test.md`。

Editor 审阅意见确认草稿质量良好、无需修改，因此终稿与草稿内容一致，已控制在一页以内。任务完成。

阶段顺序: research -> draft -> editor_review -> finalize
Editor 已执行: true
子 Agent 场景材料: D:\AI_Agent_Project\deep-research-assistant\hybrid_workspace\runs\2026-05-31T04-43-47-379Z\sources\findings_scenarios.md
子 Agent 限制材料: D:\AI_Agent_Project\deep-research-assistant\hybrid_workspace\runs\2026-05-31T04-43-47-379Z\sources\findings_limits.md
合并调研材料: D:\AI_Agent_Project\deep-research-assistant\hybrid_workspace\runs\2026-05-31T04-43-47-379Z\sources\findings_node_test.md
终稿本地路径: D:\AI_Agent_Project\deep-research-assistant\hybrid_workspace\runs\2026-05-31T04-43-47-379Z\reports\report_node_test.md

*/
