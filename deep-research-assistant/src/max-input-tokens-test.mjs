// 加载 .env 中的模型连接配置。
import "dotenv/config";
// ChatOpenAI：创建用于验证 profile.maxInputTokens 的模型实例。
import { ChatOpenAI } from "@langchain/openai";

// model：测试用聊天模型，用于验证上下文压缩触发阈值可以被覆盖。
const model = new ChatOpenAI({
    model: process.env.OPENAI_MODEL,
    apiKey: process.env.OPENAI_API_KEY,
    temperature: 0,
    configuration: { 
      baseURL: process.env.OPENAI_BASE_URL
    }
});

console.log(model.profile.maxInputTokens);

// profile getter：返回覆盖后的输入上限；读取 model.profile 时调用。
//改下这个值，就可以实现对上下文压缩触发阈值的修改：
Object.defineProperty(model, "profile", {
  get: () => ({ maxInputTokens: 1_024 }),
});

console.log(model.profile.maxInputTokens);
