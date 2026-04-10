import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import { HumanMessage, SystemMessage, ToolMessage } from '@langchain/core/messages';
import { InMemoryChatMessageHistory } from '@langchain/core/chat_history';
import { JsonOutputToolsParser } from '@langchain/core/output_parsers/openai_tools';
import { executeCommandTool, listDirectoryTool, readFileTool, writeFileTool } from './all-tools.mjs';
import chalk from 'chalk';

const model = new ChatOpenAI({ 
    modelName: "qwen-plus",
    apiKey: process.env.OPENAI_API_KEY,
    temperature: 0,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
});

const tools = [
    readFileTool,
    writeFileTool,
    executeCommandTool,
    listDirectoryTool,
];

// 绑定工具到模型
const modelWithTools = model.bindTools(tools);

// Agent 执行函数
async function runAgentWithTools(query, maxIterations = 30) {
    const history = new InMemoryChatMessageHistory();

    await history.addMessage(new SystemMessage(`你是一个项目管理助手，使用工具完成任务。

当前工作目录: ${process.cwd()}

工具：
1. read_file: 读取文件
2. write_file: 写入文件
3. execute_command: 执行命令（支持 workingDirectory 参数）
4. list_directory: 列出目录

重要规则 - execute_command：
- workingDirectory 参数会自动切换到指定目录
- 当使用 workingDirectory 时，绝对不要在 command 中使用 cd
- 错误示例: { command: "cd react-todo-app && pnpm install", workingDirectory: "react-todo-app" }
- 正确示例: { command: "pnpm install", workingDirectory: "react-todo-app" }

重要规则 - write_file：
- 当写入 React 组件文件（如 App.tsx）时，如果存在对应的 CSS 文件（如 App.css），在其他 import 语句后加上这个 css 的导入
`));

    await history.addMessage(new HumanMessage(query));

    for (let i = 0; i < maxIterations; i++) {
        console.log(chalk.bgGreen(`⏳ 正在等待 AI 思考...`));

        // 获取当前消息历史
        const messages = await history.getMessages();

        const rawStream = await modelWithTools.stream(messages);

        // 准备一个空的容器来拼接完整的 AIMessage
        let fullAIMessage = null;

        // 准备一个 tool_call_chunks 的 JSON 增量解析器
        const toolParser = new JsonOutputToolsParser();

        // 记录每个工具调用时 AImessage流式打印出来的内容长度（用 id 或 filePath 作为 key）
        const printedLengths = new Map();

        console.log(chalk.bgBlue(`\n🚀 Agent 开始思考并生成流...\n`));

        for await (const chunk of rawStream) {

            // 这里的 chunk 是 AIMessageChunk，把它拼接起来
            //之前实现的非流式mini cursor 是在 AIMessage 完整返回完成后一次性输出的，而现在我们要在流式过程中就尽可能地输出内容，
            // 所以这里每次拿到 chunk 就先把它拼接到 fullAIMessage 上，然后尝试解析工具调用，如果解析出工具调用了，
            // 就优先输出工具调用相关的内容（比如文件写入工具就输出正在写入的内容），如果没有解析出工具调用或者当前 chunk 不是工具调用相关的内容，
            // 就直接输出 chunk 的文本内容（如果有的话）。这样就实现了在流式过程中根据内容类型智能地控制输出。
            fullAIMessage = fullAIMessage ? fullAIMessage.concat(chunk) : chunk;

            let parsedTools = null;
            try {
                parsedTools = await toolParser.parseResult([{ message: fullAIMessage }]);
            } catch (e) {
                // 解析失败说明 JSON 还不完整，忽略错误继续累积
            }

            //开始解析工具调用的参数，在没有解析完成之前（参数没有传完整）就一直打印chunk的内容
            if (parsedTools && parsedTools.length > 0) {
                for (const toolCall of parsedTools) {
                    
                    //文件写入工具调用
                    if (toolCall.type === 'write_file' && toolCall.args?.content) {
                        const toolCallId = toolCall.id || toolCall.args.filePath || 'default';
                        const currentContent = String(toolCall.args.content);

                        const previousLength = printedLengths.get(toolCallId);

                        //第一次遇到这个工具调用，打印提示并初始化已打印长度
                        if (previousLength === undefined) {
                            printedLengths.set(toolCallId, 0);
                            console.log(
                                chalk.bgBlue(
                                    `\n[工具调用] write_file("${toolCall.args.filePath}") - 开始写入（流式预览）\n`,
                                ),
                            );
                        }

                        if (currentContent.length > previousLength) {
                            // 只打印新增的部分，截断之前保存过的 已经打印过的内容
                            const newContent = currentContent.slice(previousLength);
                            process.stdout.write(newContent);
                            printedLengths.set(toolCallId, currentContent.length);
                        }
                    }
                }
            } else {
                // 当前还没有解析出工具调用时，如果有文本内容就直接输出
                if (chunk.content) {
                    process.stdout.write(
                        typeof chunk.content === 'string'
                            ? chunk.content
                            : JSON.stringify(chunk.content),
                    );
                }
            }
        }

        // 此时 fullAIMessage 已经完美还原，直接存入 history
        await history.addMessage(fullAIMessage);
        console.log(chalk.green('\n✅ 消息已完整存入历史'));

        // 检查是否有工具调用
        if (!fullAIMessage.tool_calls || fullAIMessage.tool_calls.length === 0) {
            console.log(`\n✨ AI 最终回复:\n${fullAIMessage.content}\n`);
            return fullAIMessage.content;
        }

        // 工具调用参数解析完成，执行工具调用
        for (const toolCall of fullAIMessage.tool_calls) {
            const foundTool = tools.find((t) => t.name === toolCall.name);
            if (foundTool) {
                const toolResult = await foundTool.invoke(toolCall.args);
                await history.addMessage(
                    new ToolMessage({
                        content: toolResult,
                        tool_call_id: toolCall.id,
                    }),
                );
            }
        }
    }

    const finalMessages = await history.getMessages();
    return finalMessages[finalMessages.length - 1].content;
}

const case1 = `创建一个功能丰富的 React TodoList 应用：

1. 创建项目：echo -e "n\nn" | pnpm create vite react-todo-app --template react-ts
2. 修改 src/App.tsx，实现完整功能的 TodoList：
 - 添加、删除、编辑、标记完成
 - 分类筛选（全部/进行中/已完成）
 - 统计信息显示
 - localStorage 数据持久化
3. 添加复杂样式：
 - 渐变背景（蓝到紫）
 - 卡片阴影、圆角
 - 悬停效果
4. 添加动画：
 - 添加/删除时的过渡动画
 - 使用 CSS transitions
5. 列出目录确认

注意：使用 pnpm，功能要完整，样式要美观，要有动画效果

去掉 main.tsx 里的 index.css 导入

之后在 react-todo-app 项目中：
1. 使用 pnpm install 安装依赖
2. 使用 pnpm run dev 启动服务器
`;

try {
    await runAgentWithTools(case1);
} catch (error) {
    console.error(`\n❌ 错误: ${error.message}\n`);
}
