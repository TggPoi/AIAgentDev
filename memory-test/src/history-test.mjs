import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import { InMemoryChatMessageHistory } from "@langchain/core/chat_history";
import { HumanMessage, SystemMessage } from "@langchain/core/messages";

const model = new ChatOpenAI({ 
  modelName: process.env.MODEL_NAME,
  apiKey: process.env.OPENAI_API_KEY,
  temperature: 0,
  configuration: {
      baseURL: process.env.OPENAI_BASE_URL,
  },
});

async function inMemoryDemo() {

    //用 InMemoryChatMessageHistory 来管理 message，放到内存里，适合短期对话和测试场景
    //之前是用 messages 数组实现的，现在换成了 InMemoryChatMessageHistory 的 api
  const history = new InMemoryChatMessageHistory();

  const systemMessage = new SystemMessage(
    "你是一个友好、幽默的做菜助手，喜欢分享美食和烹饪技巧。"
  );

  // 第一轮对话
  console.log("[第一轮对话]");
  const userMessage1 = new HumanMessage(
    "你今天吃的什么？"
  );
  await history.addMessage(userMessage1);
  
  /**
   * getMessages() 是一个异步方法，不是立刻直接返回：[message1, message2, message3] 而是先返回一个：Promise<消息数组>，如果不写await，拿到的只是Promise，不是数组本身
   * 展开运算符 ... 要求右边是一个可迭代对象，例如：数组 字符串 其他 iterable
   * 
   * getMessages() 要设计成异步，因为ChatMessageHistory 不一定只是内存实现，例如InMemoryChatMessageHistory，FileSystemChatMessageHistory，RedisChatMessageHistory，MongoChatMessageHistory 等等，
   * 不同的实现可能需要异步读取数据（例如读取文件或者数据库时），所以统一设计成异步方法，调用时需要 await 来获取实际的消息数组
   */

  const messages1 = [systemMessage, ...(await history.getMessages())];
  const response1 = await model.invoke(messages1);
  await history.addMessage(response1);
  
  console.log(`用户: ${userMessage1.content}`);
  console.log(`助手: ${response1.content}\n`);

  // 第二轮对话（基于历史记录）
  console.log("[第二轮对话 - 基于历史记录]");
  const userMessage2 = new HumanMessage(
    "好吃吗？"
  );
  await history.addMessage(userMessage2);
  
  const messages2 = [systemMessage, ...(await history.getMessages())];
  const response2 = await model.invoke(messages2);
  await history.addMessage(response2);
  
  console.log(`用户: ${userMessage2.content}`);
  console.log(`助手: ${response2.content}\n`);

  // 展示所有历史消息
  console.log("[历史消息记录]");
  const allMessages = await history.getMessages();
  console.log(`共保存了 ${allMessages.length} 条消息：`);
  allMessages.forEach((msg, index) => {
    const type = msg.type;
    const prefix = type === 'human' ? '用户' : '助手';
    console.log(`  ${index + 1}. [${prefix}]: ${msg.content.substring(0, 50)}...`);
  });
}

inMemoryDemo().catch(console.error);