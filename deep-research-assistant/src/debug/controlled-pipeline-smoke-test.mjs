import assert from "node:assert/strict";
import fs from "node:fs";

import {
  buildControlledPipeline,
  DEFAULT_PHASE_RECURSION_LIMIT,
  prepareControlledRun,
  resolveVirtualPath,
} from "./controlled-pipeline.mjs";
import {
  clampSearchCount,
  formatCompactPages,
} from "./compact-search.mjs";

/**
 * 创建一个会把固定内容写入指定路径的模拟阶段 Agent。
 * @param {string} outputPath 模拟 Agent 需要写入的虚拟路径。
 * @param {string} content 写入文件的固定文本。
 * @param {object[]} phaseConfigs 用于收集每次 invoke() 配置的数组。
 * @returns {{invoke: Function}} 可替代真实 Agent 的最小对象。
 */
function createFakeAgent(outputPath, content, phaseConfigs = []) {
  return {
    /**
     * 记录调用配置、写入固定文件并返回模拟完成消息。
     * @param {unknown} _input 未使用的 Agent 输入。
     * @param {object} config 当前阶段调用配置。
     * @returns {Promise<{messages: Array<{content: string}>}>} 模拟 Agent 状态。
     */
    async invoke(_input, config) {
      phaseConfigs.push(config);
      fs.writeFileSync(resolveVirtualPath(outputPath), content, "utf8");
      return { messages: [{ content: `已写入 ${outputPath}` }] };
    },
  };
}

/**
 * 验证外层图严格执行四个阶段、Editor gate 生效，并向阶段传入统一递归上限。
 * @returns {Promise<void>} 所有断言通过并清理临时运行目录后结束。
 */
async function testPipelineOrderAndEditorGate() {
  const initialState = prepareControlledRun("smoke test", {
    runId: `smoke-${Date.now()}`,
  });
  const phaseConfigs = [];

  const pipeline = buildControlledPipeline({
    agents: {
      researcher: createFakeAgent(
        initialState.findingsPath,
        "# findings\n",
        phaseConfigs,
      ),
      writer: {
        calls: 0,
        async invoke(_input, config) {
          phaseConfigs.push(config);
          this.calls += 1;
          const outputPath = this.calls === 1
            ? initialState.draftPath
            : initialState.finalPath;
          fs.writeFileSync(resolveVirtualPath(outputPath), "# report\n", "utf8");
          return { messages: [{ content: `已写入 ${outputPath}` }] };
        },
      },
      editor: createFakeAgent(initialState.reviewPath, "# review\n", phaseConfigs),
    },
  });

  const result = await pipeline.invoke(initialState, { recursionLimit: 10 });
  assert.deepEqual(result.stageLog, [
    "research",
    "draft",
    "editor_review",
    "finalize",
  ]);
  assert.equal(result.editorCompleted, true);
  assert.equal(fs.existsSync(resolveVirtualPath(result.finalPath)), true);
  assert.equal(phaseConfigs.length, 4);
  assert.equal(
    phaseConfigs.every(
      (config) => config.recursionLimit === DEFAULT_PHASE_RECURSION_LIMIT,
    ),
    true,
  );

  const runDir = resolveVirtualPath(initialState.runRoot);
  const allowedRoot = resolveVirtualPath("/debug_workspace/runs");
  assert.equal(runDir.startsWith(`${allowedRoot}${process.platform === "win32" ? "\\" : "/"}`), true);
  fs.rmSync(runDir, { recursive: true, force: true });
}

/**
 * 验证阶段内部递归上限错误会被转换为包含阶段名称和调参提示的错误。
 * @returns {Promise<void>} 捕获预期错误并清理临时运行目录后结束。
 */
async function testRecursionErrorContext() {
  const initialState = prepareControlledRun("recursion error test", {
    runId: `recursion-error-${Date.now()}`,
  });
  const recursionError = new Error("simulated recursion limit");
  recursionError.lc_error_code = "GRAPH_RECURSION_LIMIT";

  const pipeline = buildControlledPipeline({
    agents: {
      researcher: {
        async invoke() {
          throw recursionError;
        },
      },
      writer: createFakeAgent(initialState.draftPath, "# draft\n"),
      editor: createFakeAgent(initialState.reviewPath, "# review\n"),
    },
  });

  await assert.rejects(
    () => pipeline.invoke(initialState, { recursionLimit: 10 }),
    new RegExp(`research 阶段达到 LangGraph 步数上限 ${DEFAULT_PHASE_RECURSION_LIMIT}`),
  );

  fs.rmSync(resolveVirtualPath(initialState.runRoot), {
    recursive: true,
    force: true,
  });
}

/**
 * 验证搜索结果数量限制和摘要截断格式。
 * @returns {void}
 */
function testCompactSearchFormatting() {
  assert.equal(clampSearchCount(undefined), 3);
  assert.equal(clampSearchCount(99), 3);
  assert.equal(clampSearchCount(0), 1);

  const formatted = formatCompactPages(
    [
      { name: "A", url: "https://a.example", summary: "x".repeat(500) },
      { name: "B", url: "https://b.example", summary: "summary" },
      { name: "C", url: "https://c.example", summary: "summary" },
      { name: "D", url: "https://d.example", summary: "must not appear" },
    ],
    { maxResults: 3, maxSummaryChars: 20 },
  );

  assert.match(formatted, /结果 1/);
  assert.match(formatted, /结果 3/);
  assert.doesNotMatch(formatted, /结果 4/);
  assert.doesNotMatch(formatted, /must not appear/);
}

await testPipelineOrderAndEditorGate();
await testRecursionErrorContext();
testCompactSearchFormatting();
console.log("controlled pipeline smoke test passed");
