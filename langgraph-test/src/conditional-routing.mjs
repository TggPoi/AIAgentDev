import { Annotation, END, START, StateGraph } from "@langchain/langgraph";

//创建了三个状态注解：query、route 和 answer。
//每个注解都有一个 reducer 函数和一个默认值。query 用于存储用户输入的文本，route 用于存储路由结果（chat 或 math），answer 用于存储最终的回答。
const StateAnnotation = Annotation.Root({
  query: Annotation({
    reducer: (_prev, next) => next,
    default: () => "",
  }),
  route: Annotation({
    reducer: (_prev, next) => next,
    default: () => "chat",
  }),
  answer: Annotation({
    reducer: (_prev, next) => next,
    default: () => "",
  }),
});

//判断文本如果有+-*/字符就走 math 分支，否则走 chat 分支
const router = (state) => {
  const isMath = /[+\-*/]/.test(state.query);
  return { route: isMath ? "math" : "chat" };
};

const mathNode = (state) => {
  try {
    // 使用 eval 计算数学表达式的结果，并将结果作为 answer 返回。如果表达式无法计算，则返回一个错误消息。
    return { answer: String(eval(state.query)) };
  } catch {
    return { answer: "表达式无法计算" };
  }
};

const chatNode = (state) => ({ answer: `你说的是：${state.query}` });

const graph = new StateGraph(StateAnnotation)
  .addNode("router", router)
  .addNode("math", mathNode)
  .addNode("chat", chatNode)
  .addEdge(START, "router")
  .addConditionalEdges("router", (state) => state.route, {//用 addConditionalEdges 添加分支，根据 router 节点的输出状态中的 route 属性来决定走哪个分支。
    math: "math",
    chat: "chat",
  })
  .addEdge("math", END)
  .addEdge("chat", END)
  .compile();

// 导出为 Mermaid：可复制到 https://mermaid.live 或 Markdown 的 ```mermaid 代码块
const drawable = await graph.getGraphAsync();
const mermaid = drawable.drawMermaid({ withStyles: true });
console.log(mermaid);

console.log(
  "result:",
  await graph.invoke({ query: "你好" })
);

console.log(
    "result:",
    await graph.invoke({ query: "10 * 8" })
);

/**
 * PS D:\AI_Agent_Project\langgraph-test> node .\src\conditional-routing.mjs
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD;
        __start__([<p>__start__</p>]):::first
        router(router)
        math(math)
        chat(chat)
        __end__([<p>__end__</p>]):::last
        __start__ --> router;
        chat --> __end__;
        math --> __end__;
        router -.-> math;
        router -.-> chat;
        classDef default fill:#f2f0ff,line-height:1.2;
        classDef first fill-opacity:0;
        classDef last fill:#bfb6fc;

result: { query: '你好', route: 'chat', answer: '你说的是：你好' }
result: { query: '10 * 8', route: 'math', answer: '80' }
 */