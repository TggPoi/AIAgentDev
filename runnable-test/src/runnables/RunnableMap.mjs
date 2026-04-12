import 'dotenv/config';
import { RunnableMap, RunnableLambda } from "@langchain/core/runnables";
import { PromptTemplate } from "@langchain/core/prompts";

const addOne = RunnableLambda.from((input) => input.num + 1);
const multiplyTwo = RunnableLambda.from((input) => input.num * 2);
const square = RunnableLambda.from((input) => input.num * input.num);

const greetTemplate = PromptTemplate.fromTemplate("你好，{name}！");
const weatherTemplate = PromptTemplate.fromTemplate("今天天气{weather}。");

// 创建 RunnableMap，并行执行多个 runnable
const runnableMap = RunnableMap.from({
    // 数学运算
    add: addOne,
    multiply: multiplyTwo,
    square: square,
    
    // prompt 格式化
    greeting: greetTemplate,
    weather: weatherTemplate,
});

// 测试输入
const input = {
    name: "神光",
    weather: "多云",
    num: 5,
};

// 执行 RunnableMap
const result = await runnableMap.invoke(input);
console.log(result);

const runnableMap2 = RunnableMap.from({
    a:{name: "tgg"},
    b:{ProvinceName: "fj"},
});

console.log(runnableMap2);

/**
 * PS D:\AI_Agent_Project\runnable-test> node .\src\runnables\RunnableMap.mjs   
{
  add: 6,
  multiply: 10,
  square: 25,
  greeting: StringPromptValue {
    lc_serializable: true,
    lc_kwargs: { value: '你好，神光！' },
    lc_namespace: [ 'langchain_core', 'prompt_values' ],
    value: '你好，神光！'
  },
  weather: StringPromptValue {
    lc_serializable: true,
    lc_kwargs: { value: '今天天气多云。' },
    lc_namespace: [ 'langchain_core', 'prompt_values' ],
    value: '今天天气多云。'
  }
}
 */