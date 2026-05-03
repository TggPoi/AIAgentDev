import {
  Annotation,
  END,
  MemorySaver,
  START,
  StateGraph,
} from "@langchain/langgraph";

const StateAnnotation = Annotation.Root({
  visitCount: Annotation({
    reducer: (_prev, next) => next,
    default: () => 0,
  }),
  message: Annotation({
    reducer: (_prev, next) => next,
    default: () => "",
  }),
});

/** 每跑一轮图，给「当前会话」访问次数 +1 */
function recordVisit(state) {
  const visitCount = state.visitCount + 1;
  const message =
    visitCount === 1
      ? "这是你在本会话里第 1 次进入。"
      : `这是你在本会话里第 ${visitCount} 次进入`;
  return { visitCount, message };
}

const graph = new StateGraph(StateAnnotation)
  .addNode("recordVisit", recordVisit)
  .addEdge(START, "recordVisit")
  .addEdge("recordVisit", END);

  //用MemorySaver把State保存到内存里，这样同一个会话的多次调用就能访问和修改同一个状态，实现了简单的「记忆」功能。
  //还可以保存到 sqlite、redis 等，分别用 SqliteSave、RedisSaver 等 api，甚至可以自定义 Saver 来保存到其他地方，比如文件系统、云存储等。
const checkpointer = new MemorySaver();
const app = graph.compile({ checkpointer });

//模拟两个用户（线程）调用这个图，看看状态是如何在同一个用户的多次调用中被保存和更新的。
const user1 = { configurable: { thread_id: "用户-小张" } };
const user2 = { configurable: { thread_id: "用户-小李" } };

//同一个用户（线程）多次调用，visitCount 会递增，message 也会更新；不同用户（线程）调用，visitCount 从 0 开始，互不影响。
const res1 = await app.invoke({}, user1);
const res2 = await app.invoke({}, user1);
const res3 = await app.invoke({}, user1);
const res4  = await app.invoke({}, user2);

console.log(res1)
console.log(res2);
console.log(res3);
console.log(res4);

/**
 * PS D:\AI_Agent_Project\langgraph-test> node .\src\checkpointer-memory.mjs
{ visitCount: 1, message: '这是你在本会话里第 1 次进入。' }
{ visitCount: 2, message: '这是你在本会话里第 2 次进入' }
{ visitCount: 3, message: '这是你在本会话里第 3 次进入' }
{ visitCount: 1, message: '这是你在本会话里第 1 次进入。' }
 */