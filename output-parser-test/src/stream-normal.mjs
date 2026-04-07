import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';

/**
 * 流式输出测试，提示词没有任何格式化要求，直接输出文本内容
 */

const model = new ChatOpenAI({
    modelName: process.env.MODEL_NAME,
    apiKey: process.env.OPENAI_API_KEY,
    temperature: 0,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
});

const prompt = `详细介绍莫扎特的信息。`;

console.log("🌊 普通流式输出演示（无结构化）\n");

try {
    const stream = await model.stream(prompt);

    let fullContent = '';
    let chunkCount = 0;

    console.log("📡 接收流式数据:\n");

    for await (const chunk of stream) {
        chunkCount++;
        const content = chunk.content;
        fullContent += content;

        process.stdout.write(content); // 实时显示流式文本
    }

    console.log(`\n\n✅ 共接收 ${chunkCount} 个数据块\n`);
    console.log(`📝 完整内容长度: ${fullContent.length} 字符`);

} catch (error) {
    console.error("\n❌ 错误:", error.message);
}

/**
 * 
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\stream-normal.mjs
🌊 普通流式输出演示（无结构化）

📡 接收流式数据:
    
xxxxxxxxx省略xxxxxxxxx

 ✅ 共接收 687 个数据块

📝 完整内容长度: 4325 字符
 */