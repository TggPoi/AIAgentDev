import 'dotenv/config';
import { RunnableBranch, RunnableLambda } from "@langchain/core/runnables";

// 创建条件判断函数
const isPositive = RunnableLambda.from((input) => input > 0);
const isNegative = RunnableLambda.from((input) => input < 0);
const isEven = RunnableLambda.from((input) => input % 2 === 0);

// 创建分支处理函数
const handlePositive = RunnableLambda.from((input) => `正数: ${input} + 10 = ${input + 10}`);
const handleNegative = RunnableLambda.from((input) => `负数: ${input} - 10 = ${input - 10}`);
const handleEven = RunnableLambda.from((input) => `偶数: ${input} * 2 = ${input * 2}`);
const handleDefault = RunnableLambda.from((input) => `默认: ${input}`);

// 创建 RunnableBranch
//这里分别对正数、负数、偶数等做不同处理，也就是 if else 的逻辑。最后一个 handleDefault 是兜底的，如果前面条件都不满足，就执行它。
const branch = RunnableBranch.from([
    [isPositive, handlePositive],
    [isNegative, handleNegative],
    [isEven, handleEven],
    handleDefault
]);

// 测试不同的输入
const testCases = [5, -3, 4, 0];

for (const testCase of testCases) {
    const result = await branch.invoke(testCase);
    console.log(`输入: ${testCase} => ${result}`);
}

/**
 * PS D:\AI_Agent_Project\runnable-test> node .\src\runnables\RunnableBranch.mjs
输入: 5 => 正数: 5 + 10 = 15
输入: -3 => 负数: -3 - 10 = -13
输入: 4 => 正数: 4 + 10 = 14
输入: 0 => 偶数: 0 * 2 = 0
 */