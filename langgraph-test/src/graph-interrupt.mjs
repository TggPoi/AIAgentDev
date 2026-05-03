import { createInterface } from "node:readline/promises";
import {
  Annotation,
  Command,
  END,
  MemorySaver,
  START,
  StateGraph,
  interrupt,
} from "@langchain/langgraph";

const StateAnnotation = Annotation.Root({
  actionSummary: Annotation({
    reducer: (_prev, next) => next,
    default: () => "",
  }),
  userInput: Annotation({
    reducer: (_prev, next) => next,
    default: () => "",
  }),
});

/** 展示一笔待确认的转账 */
const showTransfer = () => ({
  actionSummary: "向张三转账 ¥100（模拟，不会真扣款）",
});

//用 interrupt 中断图的执行等待用户输入之后再次 invoke，传入 new Command({resume: 'xxx'})
//这样图就会在上次断点位置继续执行
// 这里用了 nodejs 的 readline 包读取键盘输入

/** 停在这里等人输入；resume 的值会写进 userInput */
const waitConfirm = (state) => {
    // interrupt 的参数会传给前端界面（如果有的话）或者终端，提示用户输入。图会在这里暂停，直到用户输入并提交后才继续执行。
  const text = interrupt({
    hint: "终端里输入「确认」或备注后回车，图才会继续",
    actionSummary: state.actionSummary,
  });

  return { userInput: String(text) };
};

const graph = new StateGraph(StateAnnotation)
  .addNode("showTransfer", showTransfer)
  .addNode("waitConfirm", waitConfirm)
  .addEdge(START, "showTransfer")
  .addEdge("showTransfer", "waitConfirm")
  .addEdge("waitConfirm", END)
  .compile({ checkpointer: new MemorySaver() });

// 导出为 Mermaid：可复制到 https://mermaid.live 或 Markdown 的 ```mermaid 代码块
const drawable = await graph.getGraphAsync();
const mermaid = drawable.drawMermaid({ withStyles: true });
console.log(mermaid);

const config = { configurable: { thread_id: "interrupt-demo" } };

const paused = await graph.invoke({}, config);

console.log("\n待你确认：", paused.__interrupt__?.[0]?.value);

//等待用户输入，输入的值会传给 resume，图继续执行
const rl = createInterface({ input: process.stdin, output: process.stdout });

//rl.question 的参数会显示在终端里，提示用户输入；用户输入后按回车，输入的值会作为 resume 继续执行图，图会在上次 interrupt 的地方继续，并把输入的值写入 userInput 状态。
const line = (await rl.question("> ")).trim();
await rl.close();

if (!line) {
  console.error("未输入，退出。");
  process.exit(1);
}

//使用者输入的 line 作为 resume 的值继续执行图，图会在 waitConfirm 的 interrupt 处继续执行，并把 line 写入 userInput 状态，最终在 END 输出整个状态。
const done = await graph.invoke(new Command({ resume: line }), config);

console.log("结果：", done);

/**
 * PS D:\AI_Agent_Project\langgraph-test> node .\src\graph-interrupt.mjs    
%%{init: {'flowchart': {'curve': 'linear'}}}%%
graph TD;
        __start__([<p>__start__</p>]):::first
        showTransfer(showTransfer)
        waitConfirm(waitConfirm)
        __end__([<p>__end__</p>]):::last
        __start__ --> showTransfer;
        showTransfer --> waitConfirm;
        waitConfirm --> __end__;
        classDef default fill:#f2f0ff,line-height:1.2;
        classDef first fill-opacity:0;
        classDef last fill:#bfb6fc;


待你确认： {
  hint: '终端里输入「确认」或备注后回车，图才会继续',
  actionSummary: '向张三转账 ¥100（模拟，不会真扣款）'
}
> 确认
结果： { actionSummary: '向张三转账 ¥100（模拟，不会真扣款）', userInput: '确认' }
 */