// loadEnv：从指定 .env 文件加载环境变量。
import { config as loadEnv } from "dotenv";
// fs：读取生成的 Markdown 文件并获取文件修改时间。
import fs from "node:fs";
// path：拼接工程路径并生成相对展示路径。
import path from "node:path";
// fileURLToPath：将当前 ES Module 的 URL 转换为本地文件路径。
import { fileURLToPath } from "node:url";
// readline：在未提供命令行参数时读取用户输入。
import readline from "node:readline/promises";
// input、output：readline 使用的标准输入流和标准输出流。
import { stdin as input, stdout as output } from "node:process";
// HumanMessage：将用户问题封装为 LangChain 消息。
import { HumanMessage } from "@langchain/core/messages";

// createIntelligenceDeskAgent：创建调研 Agent；projectDir：Agent 工程根目录。
import { createIntelligenceDeskAgent, projectDir } from "./agent.mjs";

// projectRoot：CLI 所在工程的根目录，用于定位 .env 文件。
const projectRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
loadEnv({ path: path.join(projectRoot, ".env") });

// recursionLimit：Agent 图允许执行的最大递归步数，默认值为 300。
const recursionLimit = Number(process.env.RECURSION_LIMIT) || 300;

// FILE_TOOLS：需要在终端中展示目标路径的文件工具名称集合。
const FILE_TOOLS = new Set([
  "write_file",
  "edit_file",
  "read_file",
  "ls",
  "glob",
  "grep",
]);

// EVAL_TOOL：代码解释器工具名称。
const EVAL_TOOL = "eval";
// PREVIEW_LEN：终端中展示 eval 输入代码时允许的最大字符数。
const PREVIEW_LEN = 100;
// RESULT_PREVIEW_LEN：终端中展示 eval 执行结果时允许的最大字符数。
const RESULT_PREVIEW_LEN = 120;

// printBanner：打印 CLI 标题。
// 调用位置：main()。
function printBanner() {
  console.log("╔══════════════════════════════════════════╗");
  console.log("║              深度调研助手              ║");
  console.log("╚══════════════════════════════════════════╝\n");
}

// readQuery：优先读取命令行参数；没有参数时通过终端交互读取调研问题。
// 调用位置：main()。
async function readQuery() {
  // fromArgs：将命令行参数合并后得到的调研问题。
  const fromArgs = process.argv.slice(2).join(" ").trim();
  if (fromArgs) return fromArgs;

  // rl：终端交互接口，负责提问并读取用户输入。
  const rl = readline.createInterface({ input, output });
  try {
    return (await rl.question("请输入调研主题: ")).trim();
  } finally {
    rl.close();
  }
}

// stepLabel：根据事件命名空间和节点名称生成便于阅读的步骤标签。
// 参数 namespace：当前流式事件所属图路径；node：当前节点名称。
// 调用位置：run()。
function stepLabel(namespace, node) {
  if (namespace.length === 0) return `[主 Agent] ${node}`;
  // id：用于展示的主 Agent 或子 Agent 标识。
  const id = namespace[0]?.replace(/^tools:/, "subagent:") ?? namespace[0];
  return `[${id}] ${node}`;
}

// displayPath：将虚拟工作区路径整理为适合终端展示的形式。
// 参数 p：工具调用中返回的虚拟文件路径。
// 调用位置：logToolResults()。
function displayPath(p) {
  return p.startsWith("/workspace/") ? p.slice(1) : p.replace(/^\/+/, "");
}

// pathFromArgs：从文件工具参数中提取目标路径或搜索描述。
// 参数 name：工具名称；args：解析后的工具参数。
// 调用位置：trackFileCalls()。
function pathFromArgs(name, args) {
  if (!args || typeof args !== "object") return null;
  if (name === "write_file" || name === "edit_file" || name === "read_file") {
    return typeof args.file_path === "string" ? args.file_path : null;
  }
  if (name === "ls") return typeof args.path === "string" ? args.path : null;
  if (name === "glob" || name === "grep") {
    // dir：glob 或 grep 的搜索目录，缺省时从虚拟工作区根目录开始。
    const dir = typeof args.path === "string" ? args.path : "/";
    // pattern：glob 或 grep 使用的搜索模式。
    const pattern = typeof args.pattern === "string" ? args.pattern : "";
    return pattern ? `${pattern} @ ${dir}` : dir;
  }
  return null;
}

// parseArgs：将字符串形式的工具参数解析为对象；非字符串参数保持原样。
// 参数 args：工具调用携带的原始参数。
// 调用位置：trackEvalCalls()、trackFileCalls()。
function parseArgs(args) {
  if (typeof args === "string") {
    try {
      return JSON.parse(args);
    } catch {
      return args;
    }
  }
  return args;
}

// previewText：把多行文本压缩为单行预览，并按长度截断。
// 参数 text：需要预览的文本；maxLen：预览允许的最大字符数。
// 调用位置：trackEvalCalls()、logToolResults()。
function previewText(text, maxLen) {
  // oneLine：移除多余空白后的单行文本。
  const oneLine = String(text).replace(/\s+/g, " ").trim();
  if (!oneLine) return "(empty)";
  return oneLine.length <= maxLen ? oneLine : `${oneLine.slice(0, maxLen - 1)}…`;
}

// trackEvalCalls：记录模型请求中的 eval 调用，并立即打印代码预览。
// 参数 data：模型请求节点数据；pendingEval：等待返回结果的 eval 调用映射。
// 调用位置：run()。
function trackEvalCalls(data, pendingEval) {
  // msg：当前节点数据中的一条消息。
  for (const msg of data?.messages ?? []) {
    // tc：当前消息中的一条工具调用。
    for (const tc of msg.tool_calls ?? []) {
      if (!tc.id || tc.name !== EVAL_TOOL) continue;
      // args：解析后的 eval 工具参数。
      const args = parseArgs(tc.args);
      // code：eval 工具即将执行的 JavaScript 代码。
      const code =
        args && typeof args === "object" && typeof args.code === "string"
          ? args.code
          : "";
      pendingEval.set(tc.id, code);
      console.log(`  🧮 eval: ${previewText(code, PREVIEW_LEN)}`);
    }
  }
}

// trackFileCalls：记录模型请求中的文件工具调用，供结果返回时展示目标路径。
// 参数 data：模型请求节点数据；pending：等待返回结果的文件工具调用映射。
// 调用位置：run()。
function trackFileCalls(data, pending) {
  // msg：当前节点数据中的一条消息。
  for (const msg of data?.messages ?? []) {
    // tc：当前消息中的一条工具调用。
    for (const tc of msg.tool_calls ?? []) {
      if (!tc.id || !tc.name || !FILE_TOOLS.has(tc.name)) continue;
      // p：从工具参数中提取出的目标路径或搜索描述。
      const p = pathFromArgs(tc.name, parseArgs(tc.args));
      if (p) pending.set(tc.id, { name: tc.name, path: p });
    }
  }
}

// logToolResults：处理工具执行结果，并在终端中打印简洁状态。
// 参数 data：工具节点数据；pending：文件工具调用映射；pendingEval：eval 调用映射。
// 调用位置：run()。
function logToolResults(data, pending, pendingEval) {
  // msg：当前工具节点数据中的一条消息。
  for (const msg of data?.messages ?? []) {
    if (msg.type !== "tool") continue;

    if (msg.name === "task") {
      // preview：子 Agent 任务完成信息的单行摘要。
      const preview = String(msg.content).slice(0, 120).replace(/\n/g, " ");
      console.log(`  task done: ${preview}...`);
      continue;
    }

    if (msg.name === EVAL_TOOL) {
      console.log(
        `  🧮 eval → ${previewText(msg.content, RESULT_PREVIEW_LEN)}`,
      );
      if (msg.tool_call_id) pendingEval.delete(msg.tool_call_id);
      continue;
    }

    if (!msg.name || !FILE_TOOLS.has(msg.name)) continue;

    // op：此前保存的文件工具调用信息。
    const op = msg.tool_call_id ? pending.get(msg.tool_call_id) : undefined;
    // filePath：优先使用调用参数中的路径，缺失时尝试从工具结果正文中提取。
    const filePath =
      op?.path ?? String(msg.content).match(/['`](\/[^'`]+)['`]/)?.[1] ?? null;

    console.log(
      filePath ? `  ${msg.name}: ${displayPath(filePath)}` : `  ${msg.name}`,
    );
    if (msg.tool_call_id) pending.delete(msg.tool_call_id);
  }
}

// run：流式执行一次调研任务，并持续打印 Agent 的关键步骤。
// 参数 query：用户输入的调研问题。
// 调用位置：main()。
async function run(query) {
  console.log(`query: ${query}`);
  console.log(`recursionLimit: ${recursionLimit}\n`);
  console.log("─".repeat(50));

  // agent：本次调研任务使用的深度调研 Agent。
  const agent = createIntelligenceDeskAgent();
  // pending：等待返回结果的文件工具调用映射，键为工具调用 ID。
  const pending = new Map();
  // pendingEval：等待返回结果的 eval 调用映射，键为工具调用 ID。
  const pendingEval = new Map();

  // namespace：事件所属图路径；chunk：本次流式更新包含的节点数据。
  for await (const [namespace, chunk] of await agent.stream(
    { messages: [new HumanMessage(query)] },
    { streamMode: "updates", subgraphs: true, recursionLimit },
  )) {
    // node：节点名称；data：节点在本次更新中返回的数据。
    for (const [node, data] of Object.entries(chunk)) {
      if (node === "model_request") {
        trackFileCalls(data, pending);
        trackEvalCalls(data, pendingEval);
        console.log(stepLabel(namespace, node));
      } else if (node === "tools") {
        logToolResults(data, pending, pendingEval);
      } else if (node === "todoListMiddleware.after_model") {
        console.log(stepLabel(namespace, node));
      }
    }
  }

  console.log("─".repeat(50));
}

// listMd：读取目录中的 Markdown 文件，并按最后修改时间从新到旧排序。
// 参数 dir：需要扫描的本地目录路径。
// 调用位置：printOutputs()。
function listMd(dir) {
  if (!fs.existsSync(dir)) return [];
  return fs
    .readdirSync(dir)
    // filter 回调函数：仅保留 Markdown 文件；由 listMd() 中的 filter() 调用。
    // 参数 f：目录中的当前文件名。
    .filter((f) => f.endsWith(".md"))
    // map 回调函数：将文件名转换为绝对路径；由 listMd() 中的 map() 调用。
    // 参数 f：通过筛选的 Markdown 文件名。
    .map((f) => path.join(dir, f))
    // sort 回调函数：按修改时间倒序排列文件；由 listMd() 中的 sort() 调用。
    // 参数 a、b：排序时比较的两个 Markdown 文件绝对路径。
    .sort((a, b) => fs.statSync(b).mtimeMs - fs.statSync(a).mtimeMs);
}

// printOutputs：列出最近生成的调研材料和报告文件。
// 调用位置：main() 的正常完成分支和异常处理分支。
function printOutputs() {
  // sources：按修改时间排序后的调研材料 Markdown 文件。
  const sources = listMd(path.join(projectDir, "workspace/sources"));
  // reports：按修改时间排序后的报告 Markdown 文件。
  const reports = listMd(path.join(projectDir, "workspace/reports"));

  if (sources.length) {
    console.log("\n sources:");
    // f：当前需要展示的调研材料文件路径。
    for (const f of sources.slice(0, 8)) {
      console.log(`   ${path.relative(projectDir, f)}`);
    }
  }
  if (reports.length) {
    console.log("\n reports:");
    // f：当前需要展示的报告文件路径。
    for (const f of reports.slice(0, 5)) {
      console.log(`   ${path.relative(projectDir, f)}`);
    }
  }
}

// main：CLI 入口，负责校验配置、读取问题、执行任务并打印结果。
// 调用位置：文件底部的 main().catch(...)。
async function main() {
  printBanner();

  if (!process.env.OPENAI_API_KEY?.trim()) {
    console.error("Missing OPENAI_API_KEY — copy .env.example to .env");
    process.exit(1);
  }

  // query：本次执行使用的用户调研问题。
  const query = await readQuery();
  if (!query) {
    console.error("请提供调研主题");
    process.exit(1);
  }

  try {
    await run(query);
    printOutputs();
    console.log("\n✅ done");
  } catch (err) {
    // err：执行调研任务时捕获的异常。
    // msg：统一转换后的异常文本，用于判断是否为递归上限错误。
    const msg = err instanceof Error ? err.message : String(err);
    if (msg.includes("Recursion limit")) {
      console.error(`\n❌ recursion limit (${recursionLimit}) — set RECURSION_LIMIT in .env`);
    } else {
      console.error("\n❌", err);
    }
    printOutputs();
    process.exit(1);
  }
}

// catch 回调函数：兜底记录 main() 未处理的异常；由 main() 返回 Promise 被拒绝时调用。
// 参数 err：main() 自身未处理的异常。
main().catch((err) => {
  console.error(err);
  process.exit(1);
});


/*
PS D:\AI_Agent_Project\deep-research-assistant> node src/cli.mjs "调研国家统计局公开的2023年省级地区生产总值（GDP）数据：提取GDP总量前6名省份的具体数值及同 比增速，计算六省GDP总和、各省占全国GDP的比重，
并按增速从高到低排名"
◇ injected env (16) from .env // tip: ⌘ custom filepath { path: '/custom/path/.env' }
╔══════════════════════════════════════════╗
║              深度调研助手              ║
╚══════════════════════════════════════════╝

query: 调研国家统计局公开的2023年省级地区生产总值（GDP）数据：提取GDP总量前6名省份的具体数值及同 比增速，计算六省GDP总和、各省占全国GDP的比重，并按增速从高到低排名
recursionLimit: 300

──────────────────────────────────────────────────
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
  write_file: workspace/sources/question.txt
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
  read_file: skills/web-research/SKILL.md
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
  write_file: workspace/sources/research_plan.md
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] model_request
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] todoListMiddleware.after_model
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] model_request
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] todoListMiddleware.after_model
  🔎 搜索: 国家统计局官网 数据开放平台 data.stats.gov.cn（10 条）
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] model_request
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] todoListMiddleware.after_model
  🔎 搜索: 国家统计局数据开放平台 data.stats.gov.cn 功能介绍 官方说明（10 条）
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] model_request
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] todoListMiddleware.after_model
  🔎 搜索: 国家统计局 官方数据源定位 机构职能 法定职责（10 条）
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] model_request
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] todoListMiddleware.after_model
  write_file: workspace/sources/findings_official_source.md
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] model_request
[subagent:7829b965-550f-5f29-a499-be7fa996a34c] todoListMiddleware.after_model
  task done: 调研完成，已将【国家统计局官方数据源定位】的完整 findings 写入 `/workspace/sources/findings_official_source.md`。...
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
[subagent:4568164b-0039-51da-9e3c-213169220ba5] model_request
[subagent:4568164b-0039-51da-9e3c-213169220ba5] todoListMiddleware.after_model
[subagent:4568164b-0039-51da-9e3c-213169220ba5] model_request
[subagent:4568164b-0039-51da-9e3c-213169220ba5] todoListMiddleware.after_model
  🔎 搜索: 2023年各省GDP总量排名 官方数据 国家统计局（10 条）
[subagent:4568164b-0039-51da-9e3c-213169220ba5] model_request
[subagent:4568164b-0039-51da-9e3c-213169220ba5] todoListMiddleware.after_model
  🔎 搜索: 2023年各省GDP数据 国家统计局官网（10 条）
[subagent:4568164b-0039-51da-9e3c-213169220ba5] model_request
[subagent:4568164b-0039-51da-9e3c-213169220ba5] todoListMiddleware.after_model
  🔎 搜索: 2023年各省GDP数据 权威来源 国家统计局或省级统计局官网（10 条）
[subagent:4568164b-0039-51da-9e3c-213169220ba5] model_request
[subagent:4568164b-0039-51da-9e3c-213169220ba5] todoListMiddleware.after_model
  write_file: workspace/sources/findings_gdp_total.md
[subagent:4568164b-0039-51da-9e3c-213169220ba5] model_request
[subagent:4568164b-0039-51da-9e3c-213169220ba5] todoListMiddleware.after_model
  task done: 调研完成，已将2023年省级GDP总量权威数据整理并写入 `/workspace/sources/findings_gdp_total.md`。...
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] model_request
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] todoListMiddleware.after_model
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] model_request
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] todoListMiddleware.after_model
  🔎 搜索: 2023年各省GDP增速 官方数据 国家统计局（10 条）
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] model_request
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] todoListMiddleware.after_model
  🔎 搜索: 2023年各省GDP实际增速 国家统计局 官方发布（10 条）
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] model_request
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] todoListMiddleware.after_model
  🔎 搜索: 2023年各省GDP实际增速 国家统计局 2024年发布（10 条）
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] model_request
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] todoListMiddleware.after_model
  write_file: workspace/sources/findings_gdp_growth.md
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] model_request
[subagent:9cc3c953-21ca-5e73-ab0f-13c79782008b] todoListMiddleware.after_model
  task done: 调研已完成，2023年省级GDP增速数据已整理并保存到 /workspace/sources/findings_gdp_growth.md 文件中。...
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
  read_file: workspace/sources/findings_official_source.md
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
  read_file: workspace/sources/findings_gdp_total.md
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
  read_file: workspace/sources/findings_gdp_growth.md
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] model_request
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] todoListMiddleware.after_model
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] model_request
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] todoListMiddleware.after_model
  🔎 搜索: 2023年各省GDP增速 官方数据 国家统计局（10 条）
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] model_request
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] todoListMiddleware.after_model
  🔎 搜索: 2023年各省GDP增速 实际完成数据 国家统计局（10 条）
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] model_request
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] todoListMiddleware.after_model
  🔎 搜索: 2023年各省GDP增速完整排名 国家统计局官方数据（10 条）
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] model_request
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] todoListMiddleware.after_model
  write_file: workspace/sources/findings_gdp_growth_detailed.md
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] model_request
[subagent:7ead9c96-b723-54d1-914b-39132a33eaa9] todoListMiddleware.after_model
  task done: 调研已完成，2023年省级GDP增速详细数据已整理并保存到 /workspace/sources/findings_gdp_growth_detailed.md 文件中。...
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
  read_file: workspace/sources/findings_gdp_growth_detailed.md
New LangChain packages are available that more efficiently handle tool calling.

Please upgrade your packages to versions that set message tool calls. e.g., `pnpm install @langchain/anthropic`, pnpm install @langchain/openai`, etc.
New LangChain packages are available that more efficiently handle tool calling.

Please upgrade your packages to versions that set message tool calls. e.g., `pnpm install @langchain/anthropic`, pnpm install @langchain/openai`, etc.
[主 Agent] model_request
[主 Agent] todoListMiddleware.after_model
──────────────────────────────────────────────────

 sources:
   workspace\sources\findings_gdp_growth_detailed.md
   workspace\sources\findings_gdp_growth.md
   workspace\sources\findings_gdp_total.md
   workspace\sources\findings_official_source.md
   workspace\sources\research_plan.md

✅ done

*/
