import assert from "node:assert/strict";
import fs from "node:fs";
import { Command, isCommand } from "@langchain/langgraph";

import {
  buildHybridDeepPipeline,
  createHybridDeepPhaseAgents,
  DEFAULT_HYBRID_PHASE_RECURSION_LIMIT,
  NESTED_RESEARCH_LOCAL_STATE_KEYS,
  NESTED_RESEARCH_SUBAGENT_MAX_MODEL_CALLS,
  NESTED_RESEARCH_SUBAGENT_MAX_TOOL_CALLS,
  NESTED_RESEARCH_SUBAGENT_NAMES,
  omitNestedResearchLocalState,
  prepareHybridRun,
  projectDir,
  resolveHybridVirtualPath,
  sanitizeNestedResearchTaskResult,
} from "./hybrid-deep-pipeline.mjs";

function createFakeAgent(outputPath, content, phaseConfigs = []) {
  return {
    async invoke(_input, config) {
      phaseConfigs.push(config);
      fs.writeFileSync(resolveHybridVirtualPath(outputPath), content, "utf8");
      return { messages: [{ content: `已写入 ${outputPath}` }] };
    },
  };
}

async function testPipelineOrderAndEditorGate() {
  const initialState = prepareHybridRun("hybrid smoke test", {
    runId: `hybrid-smoke-${Date.now()}`,
  });
  const phaseConfigs = [];

  const pipeline = buildHybridDeepPipeline({
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
          fs.writeFileSync(
            resolveHybridVirtualPath(outputPath),
            "# report\n",
            "utf8",
          );
          return { messages: [{ content: `已写入 ${outputPath}` }] };
        },
      },
      editor: createFakeAgent(
        initialState.reviewPath,
        "# review\n",
        phaseConfigs,
      ),
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
  assert.equal(fs.existsSync(resolveHybridVirtualPath(result.finalPath)), true);
  assert.equal(phaseConfigs.length, 4);
  assert.equal(
    phaseConfigs.every(
      (config) =>
        config.recursionLimit === DEFAULT_HYBRID_PHASE_RECURSION_LIMIT,
    ),
    true,
  );

  fs.rmSync(resolveHybridVirtualPath(initialState.runRoot), {
    recursive: true,
    force: true,
  });
}

async function testMissingEditorOutputStopsPipeline() {
  const initialState = prepareHybridRun("missing editor output", {
    runId: `hybrid-missing-editor-${Date.now()}`,
  });

  const pipeline = buildHybridDeepPipeline({
    agents: {
      researcher: createFakeAgent(initialState.findingsPath, "# findings\n"),
      writer: createFakeAgent(initialState.draftPath, "# draft\n"),
      editor: {
        async invoke() {
          return { messages: [{ content: "未写入 review 文件" }] };
        },
      },
    },
  });

  await assert.rejects(
    () => pipeline.invoke(initialState, { recursionLimit: 10 }),
    /editor_review 未生成预期文件/,
  );

  fs.rmSync(resolveHybridVirtualPath(initialState.runRoot), {
    recursive: true,
    force: true,
  });
}

async function testNestedResearchPrompt() {
  const initialState = prepareHybridRun("nested research prompt", {
    runId: `hybrid-nested-prompt-${Date.now()}`,
  });
  let researchPrompt = "";

  const pipeline = buildHybridDeepPipeline({
    nestedResearch: true,
    agents: {
      researcher: {
        async invoke(input) {
          researchPrompt = input.messages[0].content;
          fs.writeFileSync(
            resolveHybridVirtualPath(initialState.findingsPath),
            "# merged findings\n",
            "utf8",
          );
          fs.writeFileSync(
            resolveHybridVirtualPath(initialState.scenarioFindingsPath),
            "# scenario findings\n",
            "utf8",
          );
          fs.writeFileSync(
            resolveHybridVirtualPath(initialState.limitsFindingsPath),
            "# limits findings\n",
            "utf8",
          );
          return { messages: [{ content: "已合并子 Agent 调研结果" }] };
        },
      },
      writer: {
        calls: 0,
        async invoke() {
          this.calls += 1;
          const outputPath = this.calls === 1
            ? initialState.draftPath
            : initialState.finalPath;
          fs.writeFileSync(resolveHybridVirtualPath(outputPath), "# report\n");
          return { messages: [{ content: `已写入 ${outputPath}` }] };
        },
      },
      editor: createFakeAgent(initialState.reviewPath, "# review\n"),
    },
  });

  await pipeline.invoke(initialState, { recursionLimit: 10 });
  assert.match(researchPrompt, /scenario_researcher/);
  assert.match(researchPrompt, /limits_researcher/);
  assert.match(researchPrompt, new RegExp(initialState.scenarioFindingsPath));
  assert.match(researchPrompt, new RegExp(initialState.limitsFindingsPath));

  fs.rmSync(resolveHybridVirtualPath(initialState.runRoot), {
    recursive: true,
    force: true,
  });
}

function testDeepAgentFactory() {
  const previousApiKey = process.env.OPENAI_API_KEY;
  process.env.OPENAI_API_KEY = previousApiKey || "smoke-test-key";

  try {
    const agents = createHybridDeepPhaseAgents();
    assert.equal(typeof agents.researcher.invoke, "function");
    assert.equal(typeof agents.writer.invoke, "function");
    assert.equal(typeof agents.editor.invoke, "function");

    const nestedAgents = createHybridDeepPhaseAgents({ nestedResearch: true });
    assert.equal(typeof nestedAgents.researcher.invoke, "function");
    assert.deepEqual(NESTED_RESEARCH_SUBAGENT_NAMES, [
      "scenario_researcher",
      "limits_researcher",
    ]);
    assert.equal(NESTED_RESEARCH_SUBAGENT_MAX_MODEL_CALLS, 7);
    assert.equal(NESTED_RESEARCH_SUBAGENT_MAX_TOOL_CALLS, 8);
  } finally {
    if (previousApiKey === undefined) {
      delete process.env.OPENAI_API_KEY;
    } else {
      process.env.OPENAI_API_KEY = previousApiKey;
    }
  }
}

function testNestedResearchLocalStateIsolation() {
  const state = {
    files: { "/shared.md": { content: ["shared"] } },
    threadModelCallCount: 5,
    runModelCallCount: 4,
    threadToolCallCount: { __all__: 6 },
    runToolCallCount: { __all__: 5 },
    _summarizationEvent: { cutoffIndex: 2 },
    _summarizationSessionId: "subagent-session",
  };
  const isolatedState = omitNestedResearchLocalState(state);

  assert.deepEqual(Object.keys(isolatedState), ["files"]);
  assert.equal(NESTED_RESEARCH_LOCAL_STATE_KEYS.length, 6);

  const sanitizedCommand = sanitizeNestedResearchTaskResult(
    new Command({
      update: {
        ...state,
        messages: [{ content: "task completed" }],
      },
    }),
  );

  assert.equal(isCommand(sanitizedCommand), true);
  assert.deepEqual(Object.keys(sanitizedCommand.update).sort(), [
    "files",
    "messages",
  ]);
}

function testLearningFilesExist() {
  for (const relativePath of [
    "hybrid-memory/AGENTS.md",
    "skills-hybrid/research/compact-research/SKILL.md",
    "skills-hybrid/research-coordinator/nested-research-coordinator/SKILL.md",
    "skills-hybrid/research-subagent/compact-subtopic-research/SKILL.md",
    "skills-hybrid/writer/concise-report-writer/SKILL.md",
    "skills-hybrid/editor/mandatory-editor-review/SKILL.md",
  ]) {
    assert.equal(fs.existsSync(`${projectDir}/${relativePath}`), true);
  }
}

await testPipelineOrderAndEditorGate();
await testMissingEditorOutputStopsPipeline();
await testNestedResearchPrompt();
testDeepAgentFactory();
testNestedResearchLocalStateIsolation();
testLearningFilesExist();
console.log("hybrid deep pipeline smoke test passed");
