import 'dotenv/config';
import { MultiServerMCPClient } from'@langchain/mcp-adapters';
import { ChatOpenAI } from'@langchain/openai';
import chalk from'chalk';
import { HumanMessage, ToolMessage,SystemMessage } from'@langchain/core/messages';

const model = new ChatOpenAI({ 
    modelName: "qwen3.5-plus",
    apiKey: process.env.OPENAI_API_KEY,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
});

// const mcpClient = new MultiServerMCPClient({
//     mcpServers: {
//         'my-mcp-server': {
//             command: "node",
//             args: [
//                 "D:/AI_Agent_Project/mcp-npx-test/src/index.mjs"
//             ]
//         }
//     }
// });

const mcpClient = new MultiServerMCPClient({
    mcpServers: {
        'my-mcp-server': {
            command: "my-mcp-server",
            args: []
        }
    }
});

const tools = await mcpClient.getTools();
const modelWithTools = model.bindTools(tools);

console.log(tools);

//获取Resource里面的静态信息
const res = await mcpClient.listResources();

//console.log(res);

//const res = await mcpClient.listResources();
//遍历依次读取 uri 内容
for (const [serverName, resources] of Object.entries(res)) {
    for (const resource of resources) {
        const content = await mcpClient.readResource(serverName, resource.uri);
        //console.log(content);
    }
}

//把Resource里面的静态信息放入对话历史的 system message 里作为上下文
//resource 可以用在 system message 里，也可以用在 human message 里，总之，是作为信息引用的
let resourceContent = '';
for (const [serverName, resources] of Object.entries(res)) {
    for (const resource of resources) {
        const content = await mcpClient.readResource(serverName, resource.uri);
        resourceContent += content[0].text;
    }
}

/*
const messages = [
    new SystemMessage(resourceContent),
    new HumanMessage(query)
];
*/

async function runAgentWithTools(query, maxIterations = 30) {
    const messages = [
        new SystemMessage(resourceContent),
        new HumanMessage(query)
    ];

    for (let i = 0; i < maxIterations; i++) {
        console.log(chalk.bgGreen(`⏳ 正在等待 AI 思考...`));
        const response = await modelWithTools.invoke(messages);
        messages.push(response);

        // 检查是否有工具调用
        if (!response.tool_calls || response.tool_calls.length === 0) {
            console.log(`\n✨ AI 最终回复:\n${response.content}\n`);
            return response.content;
        }

        console.log(chalk.bgBlue(`🔍 检测到 ${response.tool_calls.length} 个工具调用`));
        console.log(chalk.bgBlue(`🔍 工具调用: ${response.tool_calls.map(t => t.name).join(', ')}`));
        // 执行工具调用
        for (const toolCall of response.tool_calls) {
            const foundTool = tools.find(t => t.name === toolCall.name);
            if (foundTool) {
                const toolResult = await foundTool.invoke(toolCall.args);
                messages.push(new ToolMessage({
                    content: toolResult,
                    tool_call_id: toolCall.id,
                }));
            }
        }
    }

    return messages[messages.length - 1].content;
}

await runAgentWithTools("查一下用户 002 的信息");





//查询上面resourceContent注入到模型的 静态信息是否存在
//await runAgentWithTools("MCP Server 的使用指南是什么");


//让大模型查询用户，它识别到了工具调用，然后调用了 mcp 的工具。这里进程没退出，因为跑了一个子进程作为 mcp server，需要把那个关掉才可以退出进程
await mcpClient.close();