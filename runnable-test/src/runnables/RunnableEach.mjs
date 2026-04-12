import 'dotenv/config';
import { RunnableEach, RunnableLambda, RunnableSequence } from "@langchain/core/runnables";

const toUpperCase = RunnableLambda.from((input) => input.toUpperCase());
const addGreeting = RunnableLambda.from((input) => `你好，${input}！`);

const processItem = RunnableSequence.from([
  toUpperCase,
  addGreeting,
]);

// 使用 RunnableEach 对数组中的每个元素应用这个链
const chain = new RunnableEach({
  bound: processItem,
});

const input = ["alice", "bob", "carol"];
const result = await chain.invoke(input);

console.log('✅ RunnableEach - 数组元素处理:');
console.log('输入:', input);
console.log('输出:', result);

/** 对输入的数组的每个元素应用这个 chain，最终得到一个新的数组，每个元素都被转换成大写并添加了问候语。
 * 
 * PS D:\AI_Agent_Project\runnable-test> node .\src\runnables\RunnableEach.mjs       
✅ RunnableEach - 数组元素处理:
输入: [ 'alice', 'bob', 'carol' ]
输出: [ '你好，ALICE！', '你好，BOB！', '你好，CAROL！' ]
 */