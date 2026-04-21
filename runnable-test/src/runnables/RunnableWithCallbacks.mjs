import "dotenv/config";
import { RunnableLambda, RunnableSequence } from "@langchain/core/runnables";

// 文本处理链：清洗 → 分词 → 统计
const clean = RunnableLambda.from((text) => {
  return text.trim().replace(/\s+/g, " ");
});

const tokenize = RunnableLambda.from((text) => {
  return text.split(" ");
});

const count = RunnableLambda.from((tokens) => {
  return { tokens, wordCount: tokens.length };
});

const chain = RunnableSequence.from([clean, tokenize, count]);

// 用 callbacks 观测每一步的输出，其中的三个函数是固定的回调接口，分别在每个节点开始、结束和出错时被调用。通过 chain.id 可以知道当前是哪个节点在执行。
//${chain.id} langchain_core,runnables,RunnableLambda
const callback = {
  handleChainStart(chain) {
    const step = chain?.id?.[chain.id.length - 1] ?? "unknown";
    console.log(`[START] ${step}`);
  },
  handleChainEnd(output) {
    console.log(`[END]   output=${JSON.stringify(output)}\n`);
  },
  handleChainError(err) {
    console.log(`[ERROR] ${err.message}\n`);
  },
};

const result = await chain.invoke("  hello   world   from   langchain  ", {
  callbacks: [callback],
});

console.log("结果:", result);


/**
 * PS D:\AI_Agent_Project\runnable-test> node .\src\runnables\RunnableWithCallbacks.mjs
[START] RunnableSequence
[START] RunnableLambda
[END]   output={"output":"hello world from langchain"}

[START] RunnableLambda
[END]   output={"output":["hello","world","from","langchain"]}

[START] RunnableLambda
[END]   output={"tokens":["hello","world","from","langchain"],"wordCount":4}

[END]   output={"tokens":["hello","world","from","langchain"],"wordCount":4}

结果: { tokens: [ 'hello', 'world', 'from', 'langchain' ], wordCount: 4 }
 */