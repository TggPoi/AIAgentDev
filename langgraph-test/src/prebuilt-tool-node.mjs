import "dotenv/config";

import { HumanMessage } from "@langchain/core/messages";
import { tool } from "@langchain/core/tools";
import {
  END,
  MessagesAnnotation,
  START,
  StateGraph,
} from "@langchain/langgraph";
import { ToolNode, toolsCondition } from "@langchain/langgraph/prebuilt";
import { ChatOpenAI } from "@langchain/openai";
import { z } from "zod";
import { getProductBySku } from "./inventory.mock.mjs"

//这里使用了mock的测试函数 getProductBySku 来模拟一个工具函数，这个函数接受一个 SKU 参数，返回对应的商品信息和库存数量。你可以根据自己的需求替换成实际的工具函数，比如调用数据库查询、第三方 API 等。
const getProductStock = tool(
  async ({ sku }) => getProductBySku(sku),
  {
    name: "get_product_stock",
    description:
      "按 SKU 查商品名与库存，SKU 如 SKU-001。",
    schema: z.object({
      sku: z.string().describe("商品 SKU"),
    }),
  }
);

const tools = [getProductStock];

const llm = new ChatOpenAI({ 
  modelName: process.env.MODEL_NAME,
  apiKey: process.env.OPENAI_API_KEY,
  configuration: {
      baseURL: process.env.OPENAI_BASE_URL,
  },
}).bindTools(tools);

async function agent(state) {
  const response = await llm.invoke(state.messages);

  //这里使用的是MessagesAnnotation，所以状态中有一个 messages 属性，它是一个消息列表。每次调用模型后，我们把模型的回复作为新的消息添加到这个列表中，并返回更新后的状态。这样模型就可以在后续的交互中看到之前的对话历史。
  //所以下面返回的这个messages是直接按照MessagesAnnotation的定义，将{ messages: response }拼接到之前的状态中，供下一轮模型调用时使用。
  return { messages: response };

  //返回多条消息的情况，messages: [message1, message2] 让 MessagesAnnotation 自己处理合并。
}

// 创建一个工具节点，并将工具列表传入。工具节点会根据条件判断是否需要调用工具函数。
const toolNode = new ToolNode(tools);

const graph = new StateGraph(MessagesAnnotation)
  .addNode("agent", agent)
  .addNode("tools", toolNode)
  .addEdge(START, "agent")
  //agent 执行完后，如果模型要调用工具，就去 tools；否则进入end节点结束。
  //toolsCondition默认值就是返回"tools",或者END
  .addConditionalEdges("agent", toolsCondition, ["tools", END])
  //让工具执行完后回到模型节点，继续处理工具的结果，构成Agent loop的效果。直到addConditionalEdges节点判断不需要再调用工具了，才进入END节点结束。
  .addEdge("tools", "agent")
  .compile();

const result = await graph.invoke({
  messages: [
    new HumanMessage(
      "查一下 SKU-001 的库存还有多少，回答里带上商品名和数字。"
    ),
  ],
});

// 导出为 Mermaid：可复制到 https://mermaid.live 或 Markdown 的 ```mermaid 代码块
const drawable = await graph.getGraphAsync();
const mermaid = drawable.drawMermaid({ withStyles: true });
console.log(mermaid);

const last = result.messages.at(-1);

console.log(last?.content ?? result.messages);

/**
 * PS D:\AI_Agent_Project\langgraph-test> node .\src\prebuilt-tool-node.mjs
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD;
        __start__([<p>__start__</p>]):::first
        agent(agent)
        tools(tools)
        __end__([<p>__end__</p>]):::last
        __start__ --> agent;
        tools --> agent;
        agent -.-> tools;
        agent -.-> __end__;
        classDef default fill:#f2f0ff,line-height:1.2;
        classDef first fill-opacity:0;
        classDef last fill:#bfb6fc;

无线鼠标的库存还有 42。
 */