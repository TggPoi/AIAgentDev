import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import { z } from 'zod';

const model = new ChatOpenAI({
    modelName: process.env.MODEL_NAME,
    apiKey: process.env.OPENAI_API_KEY,
    temperature: 0,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
});

// 定义结构化输出的 schema
const scientistSchema = z.object({
    name: z.string().describe("科学家的全名"),
    birth_year: z.number().describe("出生年份"),
    nationality: z.string().describe("国籍"),
    fields: z.array(z.string()).describe("研究领域列表"),
});

// 使用 withStructuredOutput 方法 qwen3.5-plus模型不支持json mode，返回的json格式都是undefined，最好换个模型
const structuredModel = model.withStructuredOutput(scientistSchema);

// 调用模型
const result = await structuredModel.invoke("请介绍一下爱因斯坦，并严格以 JSON 格式输出结果。");

console.log("结构化结果:", JSON.stringify(result, null, 2));
console.log(`\n姓名: ${result.name}`);
console.log(`出生年份: ${result.birth_year}`);
console.log(`国籍: ${result.nationality}`);
console.log(`研究领域: ${result.fields.join(', ')}`);

/** qwen-plus模型没问题 3.5的模型不支持
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\apiTest-with-structured-output.mjs
结构化结果: {
  "name": "Albert Einstein",
  "birth_year": 1879,
  "nationality": "German_Swiss_American",
  "fields": [
    "theoretical_physics",
    "relativity",
    "quantum_mechanics_foundations"
  ]
}

姓名: Albert Einstein
出生年份: 1879
国籍: German_Swiss_American
研究领域: theoretical_physics, relativity, quantum_mechanics_foundations
 */