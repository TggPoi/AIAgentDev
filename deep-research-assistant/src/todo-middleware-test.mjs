// 加载 .env 中的模型连接配置。
import "dotenv/config";
// ChatOpenAI：创建测试用聊天模型。
import { ChatOpenAI } from "@langchain/openai";
// createAgent：创建测试 Agent；HumanMessage：封装用户消息；todoListMiddleware：提供待办列表能力。
import {
  createAgent,
  HumanMessage,
  todoListMiddleware,
} from "langchain";

// model：测试 todoListMiddleware 时使用的聊天模型。
const model = new ChatOpenAI({
  model: process.env.OPENAI_MODEL,
  apiKey: process.env.OPENAI_API_KEY,
  temperature: 0,
  configuration: { 
    baseURL: process.env.OPENAI_BASE_URL
  }
});

// agent：启用了 todoListMiddleware 的测试 Agent。
const agent = createAgent({
  model,
  tools: [],
  systemPrompt:
    "你是生活规划助手。收到需要多步完成的请求时，先用 write_todos 列出中文执行步骤，然后简要说明你的计划。",
  middleware: [todoListMiddleware()],//这个中间件自带了 write_todos 的 tool，会生成 todo 列表写到 graph 的 state 里
});

// query：用于触发多步骤任务拆解的测试问题。
const query =
  "我下周末想带爸妈去杭州玩两天，帮我规划一下：交通怎么选、住哪里方便、必去景点和吃什么，预算控制在人均 1500 元左右。";

// result：Agent 执行结果，其中包含中间件生成的 todos 和最终回复。
const result = await agent.invoke({
  messages: [new HumanMessage(query)],
});

console.log("todos:", JSON.stringify(result.todos, null, 2));
console.log("─".repeat(50));
console.log("回复:", result.messages.at(-1)?.content);
