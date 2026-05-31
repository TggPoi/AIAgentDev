import { config as loadEnv } from "dotenv";
import path from "node:path";

import {
  createHybridDeepPipeline,
  DEFAULT_HYBRID_TEST_QUERY,
  prepareHybridRun,
  projectDir,
  resolveHybridVirtualPath,
} from "./hybrid-deep-pipeline.mjs";

loadEnv({ path: path.join(projectDir, ".env") });

function readQuery() {
  const fromArgs = process.argv.slice(2).join(" ").trim();
  return fromArgs || DEFAULT_HYBRID_TEST_QUERY;
}

async function main() {
  const query = readQuery();
  const initialState = prepareHybridRun(query);

  console.log("StateGraph + createDeepAgent 混合流水线");
  console.log(`runId: ${initialState.runId}`);
  console.log(`query: ${query}\n`);

  const pipeline = createHybridDeepPipeline({
    onStage: (message) => console.log(`[hybrid] ${message}`),
  });
  const result = await pipeline.invoke(initialState, {
    recursionLimit: 10,
    runName: "hybrid_deep_agent_pipeline",
    tags: ["hybrid-deep-pipeline"],
  });

  console.log("\n阶段顺序:", result.stageLog.join(" -> "));
  console.log("Editor 已执行:", result.editorCompleted);
  console.log("终稿虚拟路径:", result.finalPath);
  console.log("终稿本地路径:", resolveHybridVirtualPath(result.finalPath));
}

main().catch((error) => {
  console.error("\n混合流水线执行失败：", error);
  process.exit(1);
});
