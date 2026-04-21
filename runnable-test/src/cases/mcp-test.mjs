import 'dotenv/config';
import { MultiServerMCPClient } from '@langchain/mcp-adapters';
import { ChatOpenAI } from '@langchain/openai';
import chalk from 'chalk';
import { HumanMessage, ToolMessage } from '@langchain/core/messages';
import { ChatPromptTemplate, MessagesPlaceholder } from '@langchain/core/prompts';
import { RunnableSequence, RunnableLambda, RunnableBranch, RunnablePassthrough } from '@langchain/core/runnables';

const model = new ChatOpenAI({ 
    modelName: "qwen-plus",
    apiKey: process.env.OPENAI_API_KEY,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
});

const mcpClient = new MultiServerMCPClient({
    mcpServers: {
        "amap-maps-streamableHTTP": {
            "url": "https://mcp.amap.com/mcp?key=" + process.env.AMAP_MAPS_API_KEY
        },
        "chrome-devtools": {
            "command": "npx",
            "args": [
                "-y",
                "chrome-devtools-mcp@latest"
            ]
        },
    }
});

const tools = await mcpClient.getTools();
const modelWithTools = model.bindTools(tools);

const prompt = ChatPromptTemplate.fromMessages([
    ["system", "你是一个可以调用 MCP 工具的智能助手。"],
    new MessagesPlaceholder("messages"),
]);

const llmChain = prompt.pipe(modelWithTools);

// 1. 定义处理工具调用的逻辑 (封装为 Runnable)
const toolExecutor = new RunnableLambda({
    func: async (input) => {

        //对象解包
        const { response, tools } = input;
        const toolResults = [];

        for (const toolCall of response.tool_calls ?? []) {
            const foundTool = tools.find(t => t.name === toolCall.name);
            if (!foundTool) continue;

            const toolResult = await foundTool.invoke(toolCall.args);

            // 兼容不同返回格式的字符串化
            const contentStr = typeof toolResult === 'string'
                ? toolResult
                : (toolResult?.text || JSON.stringify(toolResult));

            toolResults.push(new ToolMessage({
                content: contentStr,
                tool_call_id: toolCall.id,
            }));
        }

        return toolResults;
    }
});

/**
 * 
 *RunnablePassthrough.assign({
   response: llmChain,
   }),

   等价于：

 * (state) => ({
  ...state,
  response: llmChain.invoke(state)
})
 */
// 2. 对结果的处理
const agentStepChain = RunnableSequence.from([
    // step1: 将 LLM 输出挂到 state.response 上
    RunnablePassthrough.assign({
        response: llmChain,
    }),
    // step2: 使用 RunnableBranch 根据是否有 tool_calls 走不同分支
    RunnableBranch.from([
        // 分支1：没有 tool_calls，认为本轮已经完成
        [
            (state) =>
                !state.response?.tool_calls ||
                state.response.tool_calls.length === 0,
            new RunnableLambda({
                func: async (state) => {
                    const { messages, response } = state;
                    const newMessages = [...messages, response];
                    return {
                        ...state,
                        messages: newMessages,
                        done: true,
                        final: response.content,
                    };
                },
            }),
        ],
        
        // 默认分支：有 tool_calls，调用工具并把 ToolMessage 写回 messages
        RunnableSequence.from([
            new RunnableLambda({
                func: async (state) => {
                    const { messages, response } = state;
                    const newMessages = [...messages, response];

                    console.log(
                        chalk.bgBlue(
                            `🔍 检测到 ${response.tool_calls.length} 个工具调用`
                        )
                    );
                    console.log(
                        chalk.bgBlue(
                            `🔍 工具调用: ${response.tool_calls
                                .map((t) => t.name)
                                .join(', ')}`
                        )
                    );

                    return {
                        ...state,
                        messages: newMessages,
                    };
                },
            }),
            // 调用工具执行器，得到 toolMessages
            RunnablePassthrough.assign({
                toolMessages: toolExecutor,
            }),
            new RunnableLambda({
                func: async (state) => {
                    const { messages, toolMessages } = state;
                    return {
                        ...state,
                        messages: [...messages, ...(toolMessages ?? [])],
                        done: false,
                    };
                },
            }),
        ]),
    ]),
]);

//state 在多个 Runnable 之间传递，记录了 messages 数组、是否 done、以及最终的回复 final 以及所有 tools
async function runAgentWithTools(query, maxIterations = 30) {
    let state = {
        messages: [new HumanMessage(query)],
        done: false,
        final: null,
        tools,
    };

    for (let i = 0; i < maxIterations; i++) {
        console.log(chalk.bgGreen(`⏳ 正在等待 AI 思考...`));

        // 每一轮都通过一个完整的 Runnable chain（LLM + 工具调用处理）
        state = await agentStepChain.invoke(state);

        if (state.done) {
            console.log(`\n✨ AI 最终回复:\n${state.final}\n`);
            return state.final;
        }
    }

    return state.messages[state.messages.length - 1].content;
}

await runAgentWithTools("北京南站附近的酒店，最近的 3 个酒店，拿到酒店图片，打开浏览器，展示每个酒店的图片，每个 tab 一个 url 展示，并且在把那个页面标题改为酒店名。在调用 evaluate_script 或 click 等交互工具之前，必须先调用 take_snapshot 工具来获取当前页面的 DOM 结构和状态。不要在没有快照的情况下直接执行脚本。");

//await mcpClient.close();


/**
 * PS D:\AI_Agent_Project\runnable-test> node .\src\cases\mcp-test.mjs
chrome-devtools-mcp exposes content of the browser instance to the MCP clients allowing them to inspect,
debug, and modify any data in the browser or DevTools.
Avoid sharing sensitive or personal information that you do not want to share with MCP clients.
Performance tools may send trace URLs to the Google CrUX API to fetch real-user experience data. To disable, run with --no-performance-crux.

Google collects usage statistics to improve Chrome DevTools MCP. To opt-out, run with --no-usage-statistics.
For more details, visit: https://github.com/ChromeDevTools/chrome-devtools-mcp#usage-statistics
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: maps_geo
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: maps_around_search
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: new_page
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: new_page
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: new_page
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: select_page
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: evaluate_script
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: evaluate_script
file:///D:/AI_Agent_Project/runnable-test/node_modules/.pnpm/@langchain+mcp-adapters@1.1_9afa5544420c489b13e3a7f81987a2e0/node_modules/@langchain/mcp-adapters/dist/tools.js:314
        if (result.isError) throw new ToolException(`MCP tool '${toolName}' on server '${serverName}' returned an error: ${result.content.map((content) => content.type === "text" ? content.text : "").join("\n")}`);
                                  ^

ToolException: MCP tool 'evaluate_script' on server 'chrome-devtools' returned an error: No snapshot found for page 2. Use take_snapshot to capture one.
    at _convertCallToolResult (file:///D:/AI_Agent_Project/runnable-test/node_modules/.pnpm/@langchain+mcp-adapters@1.1_9afa5544420c489b13e3a7f81987a2e0/node_modules/@langchain/mcp-adapters/dist/tools.js:314:28)
    at _callTool (file:///D:/AI_Agent_Project/runnable-test/node_modules/.pnpm/@langchain+mcp-adapters@1.1_9afa5544420c489b13e3a7f81987a2e0/node_modules/@langchain/mcp-adapters/dist/tools.js:392:38)    
    at process.processTicksAndRejections (node:internal/process/task_queues:104:5)
    at async DynamicStructuredTool.call (file:///D:/AI_Agent_Project/runnable-test/node_modules/.pnpm/@langchain+core@1.1.39_openai@6.34.0_zod@4.3.6_/node_modules/@langchain/core/dist/tools/index.js:133:16)
    at async RunnableLambda.func (file:///D:/AI_Agent_Project/runnable-test/src/cases/mcp-test.mjs:54:32)
    at async file:///D:/AI_Agent_Project/runnable-test/node_modules/.pnpm/@langchain+core@1.1.39_openai@6.34.0_zod@4.3.6_/node_modules/@langchain/core/dist/runnables/base.js:1233:19

Node.js v24.14.0
 */


/**
 * 上面报错的原因是因为 你尝试在 第 2 个页面（Page 2） 上执行 evaluate_script（运行 JavaScript 代码），但是系统里没有这个页面的“快照”（Snapshot）。
    简单来说： AI 想要操作一个它“看不见”的页面。在 chrome-devtools-mcp 的设计中，AI 必须先通过 take_snapshot 工具“看一眼”页面（获取 DOM 结构），建立上下文后，才能对该页面执行脚本或操作。

    详细流程分析
    根据你提供的日志，我们可以还原 AI 的“作案过程”：
    疯狂开新页：
    AI 连续调用了 3 次 new_page。
    此时浏览器里应该有 Page 1, Page 2, Page 3。
    切换页面：
    AI 调用了 select_page。看日志推测，它成功切换到了 Page 2。
    直接操作（导致报错）：
    AI 紧接着调用了 evaluate_script。
    错误点：它以为切换过去就能直接运行代码，但它忘记先调用 take_snapshot 来获取页面的当前状态。
    服务器因此拒绝执行，并报错：“没找到快照，请先拍照（take_snapshot）”

    解决方案 Prompt中加一句：
    在调用 evaluate_script 或 click 等交互工具之前，必须先调用 take_snapshot 工具来获取当前页面的 DOM 结构和状态。不要在没有快照的情况下直接执行脚本。

 * 
 * PS D:\AI_Agent_Project\runnable-test> node .\src\cases\mcp-test.mjs
chrome-devtools-mcp exposes content of the browser instance to the MCP clients allowing them to inspect,
debug, and modify any data in the browser or DevTools.
Avoid sharing sensitive or personal information that you do not want to share with MCP clients.
Performance tools may send trace URLs to the Google CrUX API to fetch real-user experience data. To disable, run with --no-performance-crux.

Google collects usage statistics to improve Chrome DevTools MCP. To opt-out, run with --no-usage-statistics.
For more details, visit: https://github.com/ChromeDevTools/chrome-devtools-mcp#usage-statistics
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: maps_geo
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: maps_around_search
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: maps_search_detail
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: maps_search_detail
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: maps_search_detail
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: new_page
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: new_page
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: new_page
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: select_page
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: evaluate_script
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: select_page
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: evaluate_script
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: select_page
⏳ 正在等待 AI 思考...
🔍 检测到 1 个工具调用
🔍 工具调用: evaluate_script
⏳ 正在等待 AI 思考...

✨ AI 最终回复:
任务已完成！我已经：

1. ✅ 获取了北京南站的坐标（116.378059,39.867679）
2. ✅ 搜索到北京南站附近的酒店
3. ✅ 获取了最近的3个酒店的详细信息和图片URL
4. ✅ 为每个酒店创建了新标签页并展示了图片：
   - 标签页2：米家青年酒店(北京南站店) - https://store.is.autonavi.com/showpic/357bcafee9e1ab90ac1460eb0bda5150
   - 标签页3：汉庭酒店(北京南站护城河店) - https://store.is.autonavi.com/showpic/78d705155330ee031e4e644d6207b68f
   - 标签页4：北京佳伟来福宾馆 - https://store.is.autonavi.com/showpic/6c9008e5c66fc1b34df92daa631c20ed
5. ✅ 将每个页面的标题修改为对应的酒店名称

现在您可以在浏览器中看到三个标签页，每个标签页都显示了对应酒店的图片，并且页面标题已更新为酒店名称。

如果您需要查看更多酒店信息、获取其他详细信息或执行其他操作，请告诉我！
 */