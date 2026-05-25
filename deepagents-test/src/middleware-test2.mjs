import "dotenv/config";
import { Command } from "@langchain/langgraph";
import { z } from "zod";
import { ChatOpenAI } from "@langchain/openai";
import {
  createAgent,
  createMiddleware,
  HumanMessage,
  ToolMessage,
  tool,
} from "langchain";

const getCurrentTime = tool(() => new Date().toISOString(), {
  name: "get_current_time",
  description: "返回当前 UTC 时间的 ISO 8601 字符串",
  schema: z.object({}),
});

/** 通过 middleware 注册工具，并用 wrapToolCall 包装执行 */
const extendedToolsMiddleware = createMiddleware({
  name: "ExtendedToolsMiddleware",

  stateSchema: z.object({
    toolInvocationCount: z.number().default(0),
  }),

  //这里绑定tool和创建Agent时绑定tool的区别在于，middleware注册的工具可以访问到agent的state，从而实现调用次数统计等功能
  tools: [getCurrentTime],

  //wrapToolCall 的调用时机是在工具调用前，可以修改传入工具的请求参数，或者在工具调用后修改结果
  //和直接绑定tool的区别在于，wrapToolCall可以访问到agent的state，从而实现调用次数统计等功能
  /**
   * 
    @param request — The tool call request containing toolCall, state, and runtime.

    @param handler — The function that executes the tool. Call this with a ToolCallRequest to get the result.

    @returns — The tool result as a ToolMessage or a Command for advanced control flow.
   */
  wrapToolCall: async (request, handler) => {
    const toolName = request.tool?.name ?? request.toolCall.name;

    console.log(
      `[Tools] 即将执行: ${toolName}`,
      "args:",
      request.toolCall.args ?? {}
    );
    /**
     * request：工具调用请求，包含toolCall message
      handler：真正执行工具调用的函数，解析Request里面的toolcall信息，参数，然后执行具体的工具逻辑
     */
    const result = await handler(request);

    // 如果result 不是 ToolMessage 说明工具执行失败了，直接返回结果不做包装
    if (!ToolMessage.isInstance(result)) return result;

    const wrapped = new ToolMessage({
      content: `${result.content}\n[wrapToolCall] 已由 ExtendedToolsMiddleware 包装`,
      tool_call_id: result.tool_call_id,
      name: result.name,
    });

    console.log(
      `[Tools] 执行完成: ${toolName}`,
      typeof wrapped.content === "string"
        ? wrapped.content.slice(0, 120)
        : wrapped
    );

    //使用Command主动更新State内部参数
    return new Command({
      update: {
        toolInvocationCount: request.state.toolInvocationCount + 1,
        messages: [wrapped],
      },
    });
  },
  afterAgent: (state) => {
    console.log(
      `[Tools] agent 结束，middleware 统计工具调用: ${state.toolInvocationCount} 次`
    );
  },
});

const model = new ChatOpenAI({
  model: process.env.MODEL_NAME,
  apiKey: process.env.OPENAI_API_KEY,
  configuration: {
    baseURL: process.env.OPENAI_BASE_URL,
  },
  temperature: 0,
});

//这里没有绑定tool，如果默认某个tool是模型必备的能力，应该在这里绑定，否则就放在middleware里面作为可选工具绑定
const agent = createAgent({
  model,
  tools: [],
  systemPrompt:
    "你是一个助手。",
  middleware: [extendedToolsMiddleware],
});

for (const text of [
  "给我当前时间",
]) {
  console.log("\n用户:", text);

  const { messages, toolInvocationCount } = await agent.invoke({
    messages: [new HumanMessage(text)],
  });

  console.log("回复:", messages.at(-1)?.content);
  console.log("toolInvocationCount:", toolInvocationCount);
}