import { Annotation, END, START, StateGraph } from "@langchain/langgraph";

// 定义一个状态注解（StateAnnotation），它包含一个文本属性（text）。这个注解的 reducer 函数简单地返回下一个状态的文本，而默认值是一个空字符串。
//Annotation 用于创建 State，指定默认值（default）和合并逻辑（reducer）
const StateAnnotation = Annotation.Root({
  text: Annotation({
    reducer: (_prev, next) => next,// 这里的 reducer 函数接受前一个状态和下一个状态，并返回下一个状态的文本。
    default: () => "",// 默认值是一个空字符串。
  }),
});

const step1 = (state) => ({ text: `${state.text} -> step1` });
const step2 = (state) => ({ text: `${state.text} -> step2` });

//添加两个节点（node），加上固定的 START、END 节点然后用边（edge）连起来，最后编译成一个可执行的图（graph）。每个节点都可以访问和修改状态（state），状态由 StateAnnotation 定义。
//节点之间通过StateAnnotation传递状态，最终在END节点处输出结果。这个图的执行流程是：START -> step1 -> step2 -> END，每个步骤都会修改状态文本，最终输出完整的文本链。
const graph = new StateGraph(StateAnnotation)
  .addNode("step1", step1)
  .addNode("step2", step2)
  .addEdge(START, "step1")
  .addEdge("step1", "step2")
  .addEdge("step2", END)
  .compile();

// 导出为 Mermaid：可复制到 https://mermaid.live 或 Markdown 的 ```mermaid 代码块
const drawable = await graph.getGraphAsync();

const mermaid = drawable.drawMermaid({ withStyles: true });

console.log(mermaid);

const result = await graph.invoke({ text: "hello" });
console.log("result:", result);

/**
 * PS D:\AI_Agent_Project\langgraph-test> node .\src\basic-graph.mjs
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD;
        __start__([<p>__start__</p>]):::first
        step1(step1)
        step2(step2)
        __end__([<p>__end__</p>]):::last
        __start__ --> step1;
        step1 --> step2;
        step2 --> __end__;
        classDef default fill:#f2f0ff,line-height:1.2;
        classDef first fill-opacity:0;
        classDef last fill:#bfb6fc;

result: { text: 'hello -> step1 -> step2' }
 */
