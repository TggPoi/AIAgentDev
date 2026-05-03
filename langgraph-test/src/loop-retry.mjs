import { Annotation, END, MemorySaver, START, StateGraph } from "@langchain/langgraph";

//创建了三个状态注解：tries、ok 和 message。
//每个注解都有一个 reducer 函数和一个默认值。tries 用于记录尝试的次数，ok 用于记录是否成功，message 用于记录每次尝试的结果消息。
const StateAnnotation = Annotation.Root({
  tries: Annotation({
    reducer: (_prev, next) => next,
    default: () => 0,
  }),
  ok: Annotation({
    reducer: (_prev, next) => next,
    default: () => false,
  }),
  message: Annotation({
    reducer: (_prev, next) => next,
    default: () => "",
  }),
});

//定义了一个 attempt 节点，它会增加 tries 的值，并根据 tries 的值来设置 ok 和 message 的状态。
//当 tries 大于等于 3 时，ok 设置为 true，并返回成功消息；否则，ok 设置为 false，并返回失败消息。
const attempt = (state) => {
  const tries = state.tries + 1;
  const ok = tries >= 3;
  return {
    tries,
    ok,
    message: ok ? `第 ${tries} 次成功` : `第 ${tries} 次失败，继续重试`,
  };
};

//const memory = new MemorySaver();

const graph = new StateGraph(StateAnnotation)
  .addNode("attempt", attempt)
  .addEdge(START, "attempt")
  .addConditionalEdges("attempt", (state) => (state.ok ? "done" : "retry"), {//根据 attempt 节点的输出状态中的 ok 属性来决定走哪个分支。
    retry: "attempt",//如果 ok 是 false，就继续重试，回到 attempt 节点。这种也能实现循环的效果。
    done: END,
  })
  .compile();

// 导出为 Mermaid：可复制到 https://mermaid.live 或 Markdown 的 ```mermaid 代码块
const drawable = await graph.getGraphAsync();
const mermaid = drawable.drawMermaid({ withStyles: true });
console.log(mermaid);

const result = await graph.invoke({ tries: 0 });
console.log("result:", result);

/**
 * PS D:\AI_Agent_Project\langgraph-test> node .\src\loop-retry.mjs         
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD;
        __start__([<p>__start__</p>]):::first
        attempt(attempt)
        __end__([<p>__end__</p>]):::last
        __start__ --> attempt;
        attempt -. &nbsp;done&nbsp; .-> __end__;
        attempt -. &nbsp;retry&nbsp; .-> attempt;
        classDef default fill:#f2f0ff,line-height:1.2;
        classDef first fill-opacity:0;
        classDef last fill:#bfb6fc;

result: { tries: 3, ok: true, message: '第 3 次成功' }
 */