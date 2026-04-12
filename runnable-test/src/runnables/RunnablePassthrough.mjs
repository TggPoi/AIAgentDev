import 'dotenv/config';
import { RunnablePassthrough, RunnableLambda, RunnableSequence, RunnableMap } from "@langchain/core/runnables";


/**
 * 先用 RunnableLambda 对输入做了转换，然后用 RunnableMap 并行处理。
 * orinal 用 RunnablePassthrough 拿到原始值
 * processed 部分用 RunnableLambda 处理。
 */

const chain2 = RunnableSequence.from([
    RunnableLambda.from((input) => ({ concept: input })),
    RunnableMap.from({
        original: new RunnablePassthrough(),
        processedObj: RunnableLambda.from((obj) => ({
            concept: input,
            upper: obj.concept.toUpperCase(),
            length: obj.concept.length,
        }))
    })
]);

/**
 * {
  concept: '神说要有光',
  original: { concept: '神说要有光' },
  processed: { concept: '神说要有光', upper: '神说要有光', length: 5 }
}
 */

//简化后的写法
//只保留函数、对象即可，LangChain 会把函数转为 RunnableLambda，把对象转为 RunnableMap
// const chain = RunnableSequence.from([
//     (input) => ({ concept: input }),
//     {
//         original: new RunnablePassthrough(),
//         processed: (obj) => ({
//             concept: input,
//             upper: obj.concept.toUpperCase(),
//             length: obj.concept.length,
//         })
//     }
// ]);


//如果是想保留原始属性，只是扩展一些属性，用 RunnablePassthrough.assign
//现在之前的属性也保留着，只是合并了新的属性，就像 Object.assign 一样。
const chain = RunnableSequence.from([
    (input) => ({ concept: input }),
    RunnablePassthrough.assign({
        original: new RunnablePassthrough(),
        processedObj: (obj) => ({
            concept: input,
            upper: obj.concept.toUpperCase(),
            length: obj.concept.length,
        })
    })
]);

const input = "Tggenius23333";
const result = await chain.invoke(input);
console.log(result);

/**
 * PS D:\AI_Agent_Project\runnable-test> node .\src\runnables\RunnablePassthrough.mjs
{
  concept: 'Tggenius23333',
  original: { concept: 'Tggenius23333' },
  processedObj: { concept: 'Tggenius23333', upper: 'TGGENIUS23333', length: 13 }
}
 */



/** RunnableMap和assign()的效果对比
 * RunnableMap 默认不会帮你保留原输入字段，而 assign() 会在保留原输入对象的前提下，再追加新字段。
 * 
 * 如果想“重新构造输出对象”，使用 RunnableMap。
    如果想“保留原输入，再加字段”，使用 assign()。
 */

// 直接用 RunnableMap 来处理输入，保留原始值并添加新的属性
const input2 = { concept: "hello" };

const runnableMap = RunnableMap.from({
  upper: (obj) => obj.concept.toUpperCase(),
  length: (obj) => obj.concept.length,
})

const resultMap = await runnableMap.invoke(input2);
console.log(resultMap); //{ upper: 'HELLO', length: 5 }