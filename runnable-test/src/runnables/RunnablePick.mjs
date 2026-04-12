import 'dotenv/config';
import { RunnablePick, RunnableSequence } from "@langchain/core/runnables";

const inputData = {
  name: "TG",
  age: 90,
  city: "Amoy",
  country: "china",
  email: "test@example.com",
  phone: "+86-184645613545616",
};

const chain = RunnableSequence.from([
  (input) => ({
    ...input,
    fullInfo: `${input.name}，${input.age}岁，来自${input.city}`,
  }),
  new RunnablePick(["name", "fullInfo"]),
]);

const result = await chain.invoke(inputData);
console.log(result);

/**从对象里取一些属性出来，组成一个新的对象。上面这个例子里，输入是一个包含个人信息的对象，经过处理后，
 * 我们只取了 name 和 fullInfo 这两个属性，输出一个新的对象。
 * 
 * PS D:\AI_Agent_Project\runnable-test> node .\src\runnables\RunnablePick.mjs       
{ name: 'TG', fullInfo: 'TG，90岁，来自Amoy' }
 */