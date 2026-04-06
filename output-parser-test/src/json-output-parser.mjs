import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import { JsonOutputParser } from '@langchain/core/output_parsers';

// 初始化模型
const model = new ChatOpenAI({
    modelName: process.env.MODEL_NAME,
    apiKey: process.env.OPENAI_API_KEY,
    temperature: 0,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
});

//如果遇到模型返回的内容是markdown语法的json字符串 例如 ```json ... ``` 直接 JSON.parse 会失败，这时候可以使用 JsonOutputParser 来解析，其中已经包含了这种情况的处理
const parser = new JsonOutputParser();

//getFormatInstructions比较简单，不会给模型提供提示词
const question = `请介绍一下爱因斯坦的信息。请以 JSON 格式返回，包含以下字段：name（姓名）、birth_year（出生年份）、nationality（国籍）、major_achievements（主要成就，数组）、famous_theory（著名理论）。

${parser.getFormatInstructions()}`;

console.log('question:',question)
try {
    console.log("🤔 正在调用大模型（使用 JsonOutputParser）...\n");

    const response = await model.invoke(question);

    console.log("📤 模型原始响应:\n");
    console.log(response.content);

    const result = await parser.parse(response.content);

    console.log("✅ JsonOutputParser 自动解析的结果:\n");
    console.log(result);
    console.log(`姓名: ${result.name}`);
    console.log(`出生年份: ${result.birth_year}`);
    console.log(`国籍: ${result.nationality}`);
    console.log(`著名理论: ${result.famous_theory}`);
    console.log(`主要成就:`, result.major_achievements);

} catch (error) {
    console.error("❌ 错误:", error.message);
}


/**
 * 
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\json-output-parser.mjs
question: 请介绍一下爱因斯坦的信息。请以 JSON 格式返回，包含以下字段：name（姓名）、birth_year（出生年份）、nationality（国籍）、major_achievements（主要成就，数组）、famous_theory（著名理论）。


🤔 正在调用大模型（使用 JsonOutputParser）...

📤 模型原始响应:

{
  "name": "阿尔伯特·爱因斯坦",
  "birth_year": 1879,
  "nationality": "德裔美国",
  "major_achievements": [
    "提出光电效应理论",
    "创立狭义相对论",
    "创立广义相对论",
    "推导出质能方程 E=mc²",
    "解释布朗运动"
  ],
  "famous_theory": "相对论"
}
✅ JsonOutputParser 自动解析的结果:

{
  name: '阿尔伯特·爱因斯坦',
  birth_year: 1879,
  nationality: '德裔美国',
  major_achievements: [ '提出光电效应理论', '创立狭义相对论', '创立广义相对论', '推导出质能方程 E=mc²', '解释布朗运动' ],
  famous_theory: '相对论'
}
姓名: 阿尔伯特·爱因斯坦
出生年份: 1879
国籍: 德裔美国
著名理论: 相对论
主要成就: [ '提出光电效应理论', '创立狭义相对论', '创立广义相对论', '推导出质能方程 E=mc²', '解释布朗运动' ]
 */