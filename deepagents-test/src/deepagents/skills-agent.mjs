import "dotenv/config";
import { existsSync, mkdirSync } from "node:fs";
import { ChatOpenAI } from "@langchain/openai";
import { createAgent, HumanMessage } from "langchain";
import {
  LocalShellBackend,
  createFilesystemMiddleware,
  createSkillsMiddleware,
} from "deepagents";

//npx skills add https://github.com/github/awesome-copilot --skill excalidraw-diagram-generator
//使用绘制流程图的skill测试，通过openclaw模式安装

const skills = "/.agents/skills/";
const output = "src/deepagents/output/deepagents-skills-flow.excalidraw";

if (!existsSync(".agents/skills/excalidraw-diagram-generator/SKILL.md")) {
  throw new Error(
    "未找到 excalidraw-diagram-generator，请先: npx skills add github/awesome-copilot --skill excalidraw-diagram-generator -y"
  );
}

mkdirSync("src/deepagents/output", { recursive: true });

const model = new ChatOpenAI({
  model: process.env.MODEL_NAME,
  apiKey: process.env.OPENAI_API_KEY,
  configuration: { baseURL: process.env.OPENAI_BASE_URL },
  temperature: 0,
  streaming: true,
});

//这里使用了能够执行shell命令的 LocalShellBackend，配合技能和文件系统中间件，可以让模型通过技能调用和文件操作来完成任务
const backend = await LocalShellBackend.create({
  rootDir: ".",
  virtualMode: true,
  inheritEnv: true,
});

const agent = createAgent({
  model,
  tools: [],
  systemPrompt: "按 skills 库完成任务，需要时 read_file 对应 SKILL.md。中文回答。",
  middleware: [
    
    createSkillsMiddleware({ backend, sources: [skills] }),
    createFilesystemMiddleware({ backend }),
  ],
});

const prompt = [
  "画一张流程图，描述本项目的 skills-agent 工作流：",
  "用户 Prompt → createAgent → createSkillsMiddleware → createFilesystemMiddleware → 模型回复。",
  `保存为 ${output}。要求：`,
  "- 顶部大标题 + 副标题",
  "- 每个主节点 numbered（①②…）且框内 2～3 行中文说明",
  "- 右侧一列「说明：…」补充细节",
  "- 箭头上标注阶段名（如 invoke、wrapModelCall）",
  "- 底部图例（颜色含义 + 如何运行 demo）",
].join("\n");

console.log("用户:", prompt);

function chunkText(chunk) {
  if (!chunk?.content) return "";

  if (typeof chunk.content === "string") return chunk.content;

  if (Array.isArray(chunk.content)) {
    return chunk.content
      .map((p) => (typeof p === "string" ? p : (p?.text ?? "")))
      .join("");
  }
  return "";
}

const stream = await agent.streamEvents(
  { messages: [new HumanMessage(prompt)] },
  { recursionLimit: 100 }
);

let skillsMetadata;
console.log("\n--- 流式输出 ---\n");

try {
  for await (const event of stream) {
    if (event.event === "on_chat_model_stream") {
      const text = chunkText(event.data?.chunk);
      if (text) process.stdout.write(text);
    }
    if (event.event === "on_tool_start") {
      const name = event.name?.split("/").pop() ?? event.name;
      process.stdout.write(`\n\n→ ${name}\n\n`);
    }
    if (event.event === "on_chain_end" && event.data?.output?.skillsMetadata) {
      skillsMetadata = event.data.output.skillsMetadata;
    }
  }
} catch (e) {
  console.error("\n\n[错误]", e.cause?.message ?? e.message);
  throw e;
}

console.log("\n");
console.log("skills:", skillsMetadata?.map((s) => s.name));
if (existsSync(output)) {
  console.log("图表:", output);
  console.log("打开: https://excalidraw.com → Open → 选择该文件");
} else {
  console.log("未生成:", output);
}

await backend.close();


/*
PS D:\AI_Agent_Project\deepagents-test> node .\src\deepagents\skills-agent.mjs                                                       
用户: 画一张流程图，描述本项目的 skills-agent 工作流：
用户 Prompt → createAgent → createSkillsMiddleware → createFilesystemMiddleware → 模型回复。
保存为 src/deepagents/output/deepagents-skills-flow.excalidraw。要求：
- 顶部大标题 + 副标题
- 每个主节点 numbered（①②…）且框内 2～3 行中文说明
- 右侧一列「说明：…」补充细节
- 箭头上标注阶段名（如 invoke、wrapModelCall）
- 底部图例（颜色含义 + 如何运行 demo）

--- 流式输出 ---

我需要使用 `excalidraw-diagram-generator` 技能来创建这个流程图。首先，让我阅读该技能的完整说明：



→ read_file

现在我理解了 `excalidraw-diagram-generator` 技能的要求。根据用户需求，我需要创建一个描述 skills-agent 工作流的流程图。

让我分析需求：
- 类型：流程图（Flowchart）
- 内容：用户 Prompt → createAgent → createSkillsMiddleware → createFilesystemMiddleware → 模型回复
- 要求：顶部大标题+副标题、每个主节点 numbered（①②…）、右侧说明列、箭头标注阶段名、底部图例

根据技能文档，我需要创建一个 Excalidraw JSON 文件，包含：
- 标题文本元素
- 5个矩形节点（带编号和2-3行中文说明）
- 右侧说明文本元素
- 连接箭头（标注阶段名）
- 底部图例文本

让我创建这个流程图：




→ write_file

✅ 已成功创建 skills-agent 工作流流程图！

**文件已保存为：** `src/deepagents/output/deepagents-skills-flow.excalidraw`

**图表详情：**
- **类型：** 流程图（Flowchart）
- **元素总数：** 18个（5个主节点 + 5个箭头 + 7个文本元素）
- **布局：** 清晰的垂直流程，从上到下展示完整工作流

**图表特点：**
- 🎯 **顶部标题**："skills-agent 工作流" + 副标题"用户请求到模型响应的完整处理链路"
- 🔢 **5个编号主节点**（①-⑤），每个包含2-3行中文说明
- 📝 **右侧说明列**：详细解释各阶段的关键功能和作用
- ➡️ **箭头标注**：清晰标注了各阶段的名称（invoke、wrapModelCall、injectSkills、addFilesystem、generateResponse）
- 📊 **底部图例**：说明颜色含义（蓝色输入层、绿色Agent初始化、黄色技能中间件、青色文件系统中间件、红色输出层）和如何运行demo

**如何使用：**
1. 访问 https://excalidraw.com
2. 点击"Open"或直接拖放 `src/deepagents/output/deepagents-skills-flow.excalidraw` 文件
3. 或使用 VS Code 的 Excalidraw 扩展打开

这个流程图完整展示了 skills-agent 从接收用户请求到生成最终响应的整个处理链路，体现了分层架构设计和各中间件的职责分工。

skills: [ 'excalidraw-diagram-generator' ]
图表: src/deepagents/output/deepagents-skills-flow.excalidraw
打开: https://excalidraw.com → Open → 选择该文件

*/