import { config as loadEnv } from "dotenv";
import path from "node:path";

import {
  createControlledPipeline,
  DEFAULT_TEST_QUERY,
  prepareControlledRun,
  projectDir,
  resolveVirtualPath,
} from "./controlled-pipeline.mjs";

loadEnv({ path: path.join(projectDir, ".env") });

/**
 * 读取命令行中的用户问题；未传参数时使用受控流水线默认问题。
 * @returns {string} 将作为流水线输入的完整问题文本。
 */
function readQuery() {
  const fromArgs = process.argv.slice(2).join(" ").trim();
  return fromArgs || DEFAULT_TEST_QUERY;
}

/**
 * 创建并执行受控调试流水线，然后将阶段顺序和终稿路径输出到控制台。
 * 输入来自命令行参数和 .env 环境变量；输出为控制台日志和运行目录中的报告文件。
 * @returns {Promise<void>} 流水线执行和日志输出完成后结束。
 */
async function main() {
  const query = readQuery();
  const initialState = prepareControlledRun(query);

  console.log("受控调试流水线");
  console.log(`runId: ${initialState.runId}`);
  console.log(`query: ${query}\n`);

  const pipeline = createControlledPipeline({
    onStage: (message) => console.log(`[pipeline] ${message}`),
  });
  const result = await pipeline.invoke(initialState, {
    recursionLimit: 10,
    runName: "controlled_debug_pipeline",
    tags: ["debug-pipeline"],
  });

  console.log("\n阶段顺序:", result.stageLog.join(" -> "));
  console.log("Editor 已执行:", result.editorCompleted);
  console.log("终稿虚拟路径:", result.finalPath);
  console.log("终稿本地路径:", resolveVirtualPath(result.finalPath));
}

main().catch((error) => {
  console.error("\n受控调试流水线执行失败：", error);
  process.exit(1);
});
