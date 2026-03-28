import 'dotenv/config'; //设置AI模型参数，例如temperature
import { ChatOpenAI } from'@langchain/openai';
import { tool } from'@langchain/core/tools';
import { HumanMessage, SystemMessage, ToolMessage } from'@langchain/core/messages';
import fs from'node:fs/promises';
import { z } from'zod';

const model = new ChatOpenAI({ 
modelName: process.env.MODEL_NAME || "qwen3-coder-plus",
apiKey: process.env.OPENAI_API_KEY,
temperature: 0,
configuration: {
      baseURL: process.env.OPENAI_BASE_URL,
  },
});

const readFileTool = tool(
async ({ filePath }) => {
    const content = await fs.readFile(filePath, 'utf-8');
    console.log(`  [工具调用] read_file("${filePath}") - 成功读取 ${content.length} 字节`);
    return`文件内容:\n${content}`;
  },
  {
    name: 'read_file',
    description: '用此工具来读取文件内容。当用户要求读取文件、查看代码、分析文件内容时，调用此工具。输入文件路径（可以是相对路径或绝对路径）。',
    schema: z.object({
      filePath: z.string().describe('要读取的文件路径'),
    }),
  }
);

const listDirTool = tool(
  async ({ dirPath }) => {
    const files = await fs.readdir(dirPath);
    return files.join('\n');
  },
  {
    name: 'list_dir',
    description: '用此工具来读取文件目录，当用户要求读取指定路径的文件夹下的文件列表时，调用此工具。输入文件路径（可以是相对路径或绝对路径）。',
    schema: z.object({
      dirPath: z.string().describe('要读取的文件夹路径'),
    }),
  }
);

const tools = [
  readFileTool,listDirTool
];

const modelWithTools = model.bindTools(tools);

const messages = [
new SystemMessage(`你是一个代码助手，可以使用工具读取文件并解释代码，以及使用工具读取一个文件夹下的所有文件列表。

工作流程：
1. 用户要求读取文件时，立即调用 read_file 工具；用户要求读取指定路径下的目录列表时，立即调用 listDirTool 工具
2. 等待工具返回文件内容或文件目录
3. 基于文件内容进行分析和解释

可用工具：
- read_file: 读取文件内容（使用此工具来获取文件内容）
- list_dir： 读取指定路径下的文件目录列表（使用此工具来获取指定目录下的文件列表）
`),
//new HumanMessage('请读取 src/tool-file-read.mjs 文件内容并解释代码')
new HumanMessage('请读取 src目录下的文件列表')
];

let response = await modelWithTools.invoke(messages);
console.log(response);


messages.push(response);

while (response.tool_calls && response.tool_calls.length > 0) {

console.log(`\n[检测到 ${response.tool_calls.length} 个工具调用]`);

// 执行所有工具调用
const toolResults = await Promise.all(
    response.tool_calls.map(async (toolCall) => {
      const tool = tools.find(t => t.name === toolCall.name);
      if (!tool) {
        return`错误: 找不到工具 ${toolCall.name}`;
      }
      
      console.log(`  [执行工具] ${toolCall.name}(${JSON.stringify(toolCall.args)})`);

      try {
        const result = await tool.invoke(toolCall.args);
        return result;
      } catch (error) {
        return`错误: ${error.message}`;
      }
    })
  );

// 将工具结果添加到消息历史
  response.tool_calls.forEach((toolCall, index) => {
    messages.push(
      new ToolMessage({
        content: toolResults[index],
        tool_call_id: toolCall.id,
      })
    );
  });

// 再次调用模型，传入工具结果 (如果进入调用工具的死循环，那就是模型调用后回答的内容满足了 while循环的条件，也就是说模型一直在调用工具！)
  response = await modelWithTools.invoke(messages);
}

console.log('\n[最终回复]');
console.log(response.content);
