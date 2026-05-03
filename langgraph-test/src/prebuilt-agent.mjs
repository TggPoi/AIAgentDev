import "dotenv/config";

import { HumanMessage } from "@langchain/core/messages";
import { ChatOpenAI } from "@langchain/openai";
import { MemorySaver } from "@langchain/langgraph";
import { createAgent, tool } from "langchain";
import { z } from "zod";

import { getProductBySku } from "./inventory-mock.mjs";

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

const model = new ChatOpenAI({ 
  modelName: process.env.MODEL_NAME,
  apiKey: process.env.OPENAI_API_KEY,
  configuration: {
      baseURL: process.env.OPENAI_BASE_URL,
  },
});

// 创建一个智能体，传入语言模型、工具函数和系统提示语。
// 系统提示语中明确告诉智能体在回答库存相关问题时必须调用 get_product_stock 工具函数，禁止编造库存信息。
// 这里使用了 MemorySaver 作为 checkpointer，可以在智能体的执行过程中保存状态，方便调试和分析。
const agent = createAgent({
  model,
  tools: [getProductStock],
  systemPrompt:
    "你是仓库助手。问库存时必须调用 get_product_stock（模拟数据），禁止编造。",
  checkpointer: new MemorySaver(),
});

const result = await agent.invoke(
  { messages: [new HumanMessage("SKU-002 还剩多少库存？")] },
  { configurable: { thread_id: "demo-thread" } }
);

// 导出为 Mermaid：可复制到 https://mermaid.live 或 Markdown 的 ```mermaid 代码块
const drawable = await agent.graph.getGraphAsync();

const mermaid = drawable.drawMermaid({ withStyles: true });
console.log(mermaid);

const last = result.messages.at(-1);
console.log(last?.content ?? result);