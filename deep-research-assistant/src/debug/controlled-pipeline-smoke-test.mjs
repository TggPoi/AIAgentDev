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

function createFakeAgent(outputPath, content, phaseConfigs = []) {
  return {
    async invoke(_input, config) {
      phaseConfigs.push(config);
      fs.writeFileSync(resolveVirtualPath(outputPath), content, "utf8");
      return { messages: [{ content: `已写入 ${outputPath}` }] };
    },
  };
}

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
