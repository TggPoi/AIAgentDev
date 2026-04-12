import 'dotenv/config';
import { RunnableLambda, RunnableSequence } from"@langchain/core/runnables";

const addOne = RunnableLambda.from((input) => {
    console.log(`输入: ${input}`);
    return input + 1;
});

const multiplyTwo = RunnableLambda.from((input) => {
    console.log(`输入: ${input}`);
    return input * 2;
});

//通过from让runnablelambda对象绑定一个函数，invoke时会调用这个函数，并传入参数
multiplyTwo.invoke(5).then(result => {
    console.log(`结果: ${result}`);
});

const chain = RunnableSequence.from([
    addOne,
    multiplyTwo,
    addOne
]);

const result = await chain.invoke(5);
console.log(result);