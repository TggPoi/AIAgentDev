import "dotenv/config";

import { HumanMessage } from "@langchain/core/messages";
import { createSupervisor } from "@langchain/langgraph-supervisor";
import { ChatOpenAI } from "@langchain/openai";
import { createAgent, tool } from "langchain";
import { z } from "zod";

import { lookupCityTrivia, lookupWeather } from "./simple-mock.mjs";

const model = new ChatOpenAI({
  modelName: process.env.MODEL_NAME,
  apiKey: process.env.OPENAI_API_KEY,
  configuration: {
    baseURL: process.env.OPENAI_BASE_URL,
  },
});

const lookupWeatherTool = tool(
  async ({ city }) => lookupWeather(city),
  {
    name: "lookup_weather",
    description: "查询某城市当日天气概况（气温区间、天气、空气质量等）。",
    schema: z.object({
      city: z.string().describe("城市名，如 杭州"),
    }),
  }
);

const lookupCityTriviaTool = tool(
  async ({ city }) => lookupCityTrivia(city),
  {
    name: "lookup_city_trivia",
    description: "查询与某城市相关的一句趣味知识。",
    schema: z.object({
      city: z.string().describe("城市名，如 杭州"),
    }),
  }
);

/** 子代理 A：只回答「天气」类问题 */
const weatherAgent = createAgent({
  name: "weather_agent",
  description: "专门查天气",
  model,
  tools: [lookupWeatherTool],
  systemPrompt: "你只处理天气。用户提到城市时，用 lookup_weather 查询后再用中文简短说明。",
});

/** 子代理 B：只回答「城市小知识」 */
const triviaAgent = createAgent({
  name: "trivia_agent",
  description: "专门讲与城市相关的小知识；必须调用 lookup_city_trivia。",
  model,
  tools: [lookupCityTriviaTool],
  systemPrompt: "你只讲城市小知识。先 lookup_city_trivia，再用人话转述，不要编造工具里没有的内容。",
});

/**
 * Supervisor：根据用户问的是「天气」还是「小知识」切换子代理。
 * （真实业务里还可以再加更多子代理，思路一样。）
 */
const workflow = createSupervisor({
  agents: [weatherAgent.graph, triviaAgent.graph],
  llm: model,
  prompt: `你是调度员，只负责选人，不要自己报气温、也不要自己讲城市百科。

- 问天气、气温、下不下雨、空气 → 用 weather_agent
- 问小知识、名胜、历史、一句介绍 → 用 trivia_agent
`,
});

const app = workflow.compile();

const drawable = await app.getGraphAsync();
console.log(drawable.drawMermaid({ withStyles: true }));

const input = {
  messages: [
    new HumanMessage("查一下杭州的天气，再讲一条和杭州有关的小知识。"),
  ],
};

const nodePath = [];
let finalState = null;

const stream = await app.stream(input, { streamMode: ["updates", "values"] });
// 监听执行过程中的状态更新和最终结果。状态更新里会包含当前执行到哪个节点了，最终结果里会包含整个对话的消息列表。
//使用updates模式监听状态更新，values模式监听最终结果。每当状态更新时，就把当前节点的名字记录下来；等到执行结束时，拿到最终的消息列表并打印出来。通过这种方式，我们可以清楚地看到智能体在执行过程中是如何在不同子代理之间切换的，以及最终的回答是什么。
for await (const event of stream) {

  const [mode, payload] = event;

  if (mode === "updates" && payload && typeof payload === "object") {
    
    //在这步断点调试，观察当前执行的Agent信息
    //...Object.keys(payload) 是 展开运算符（spread operator） 与 Object.keys() 的组合用法，作用是把对象的所有键名逐个添加到数组中。
    nodePath.push(...Object.keys(payload));

  } else if (mode === "values") {
    finalState = payload;
  }
}

console.log("路径:", nodePath.join(" → "));
const last = finalState?.messages?.at(-1);
console.log(last?.content ?? finalState?.messages);

/**
 * 
D:\SoftwareAI\NodeJs2414\node.exe .\src\multi-agent-supervisor.mjs
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD;
	__start__([<p>__start__</p>]):::first
	supervisor(supervisor)
	weather_agent(weather_agent)
	trivia_agent(trivia_agent)
	__start__ --> supervisor;
	trivia_agent --> supervisor;
	weather_agent --> supervisor;
	supervisor -.-> weather_agent;
	supervisor -.-> trivia_agent;
	classDef default fill:#f2f0ff,line-height:1.2;
	classDef first fill-opacity:0;
	classDef last fill:#bfb6fc;

路径: supervisor → weather_agent → supervisor → trivia_agent → supervisor
杭州今天多云转小雨，气温在15℃到22℃之间，空气质量为良。

关于杭州的小知识：西湖文化景观是世界文化遗产之一。
 */