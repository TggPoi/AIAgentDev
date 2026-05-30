import assert from "node:assert/strict";
import fs from "node:fs";

import {
  buildControlledPipeline,
  prepareControlledRun,
  resolveVirtualPath,
} from "./controlled-pipeline.mjs";
import {
  clampSearchCount,
  formatCompactPages,
} from "./compact-search.mjs";

function createFakeAgent(outputPath, content) {
  return {
    async invoke() {
      fs.writeFileSync(resolveVirtualPath(outputPath), content, "utf8");
      return { messages: [{ content: `已写入 ${outputPath}` }] };
    },
  };
}

async function testPipelineOrderAndEditorGate() {
  const initialState = prepareControlledRun("smoke test", {
    runId: `smoke-${Date.now()}`,
  });

  const pipeline = buildControlledPipeline({
    agents: {
      researcher: createFakeAgent(initialState.findingsPath, "# findings\n"),
      writer: {
        calls: 0,
        async invoke() {
          this.calls += 1;
          const outputPath = this.calls === 1
            ? initialState.draftPath
            : initialState.finalPath;
          fs.writeFileSync(resolveVirtualPath(outputPath), "# report\n", "utf8");
          return { messages: [{ content: `已写入 ${outputPath}` }] };
        },
      },
      editor: createFakeAgent(initialState.reviewPath, "# review\n"),
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

  const runDir = resolveVirtualPath(initialState.runRoot);
  const allowedRoot = resolveVirtualPath("/debug_workspace/runs");
  assert.equal(runDir.startsWith(`${allowedRoot}${process.platform === "win32" ? "\\" : "/"}`), true);
  fs.rmSync(runDir, { recursive: true, force: true });
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
testCompactSearchFormatting();
console.log("controlled pipeline smoke test passed");
