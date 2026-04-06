import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';

// 初始化模型
const model = new ChatOpenAI({
    modelName: process.env.MODEL_NAME,
    apiKey: process.env.OPENAI_API_KEY,
    temperature: 0,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
});

// 简单的问题，要求 JSON 格式返回
const question = "请介绍一下爱因斯坦的信息。请以 JSON 格式返回，包含以下字段：name（姓名）、birth_year（出生年份）、nationality（国籍）、major_achievements（主要成就，数组）、famous_theory（著名理论）。";

try {
    console.log("🤔 正在调用大模型...\n");

    const response = await model.invoke(question);

    console.log("✅ 收到响应:\n");
    console.log(response.content);

    // 解析 JSON，但是如果回答中带有其他格式的语法 例如markdown 代码块，直接 JSON.parse 会失败
    const jsonResult = JSON.parse(response.content);
    console.log("\n📋 解析后的 JSON 对象:");
    console.log(jsonResult);

} catch (error) {
    console.error("❌ 错误:", error.message);
}


/**
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\normal.mjs
🤔 正在调用大模型...

✅ 收到响应:

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

📋 解析后的 JSON 对象:
{
  name: '阿尔伯特·爱因斯坦',
  birth_year: 1879,
  nationality: '德裔美国',
  major_achievements: [ '提出光电效应理论', '创立狭义相对论', '创立广义相对论', '推导出质能方程 E=mc²', '解释布朗运动' ],
  famous_theory: '相对论'
}
 */
