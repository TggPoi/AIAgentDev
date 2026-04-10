import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import chalk from 'chalk';
import { z } from 'zod';
import { zodToJsonSchema } from "zod-to-json-schema";
import { HumanMessage, SystemMessage } from '@langchain/core/messages';

const scientistSchema = z.object({
    name: z.string().describe("科学家的全名"),
    birth_year: z.number().describe("出生年份"),
    field: z.string().describe("主要研究领域"),
    achievements: z.array(z.string()).describe("主要成就列表")
}).strict();

// 将 Zod 转换为原生的 JSON Schema 格式
const nativeJsonSchema = zodToJsonSchema(scientistSchema);

const model = new ChatOpenAI({
    modelName: "qwen-max",
    temperature: 0,
    apiKey: process.env.OPENAI_API_KEY,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
    modelKwargs: { // 通过 modelKwargs 传入原生参数
        response_format: {
            type: "json_schema",
            json_schema: {
                name: "scientist_info",
                strict: true,
                schema: nativeJsonSchema // 这里的 nativeJsonSchema 就是转换后的对象
            }
        }
    }
});

async function testNativeJsonSchema() {
    console.log(chalk.bgMagenta("🧪 测试原生 JSON Schema 模式...\n"));

    const res = await model.invoke([
        new SystemMessage("你是一个信息提取助手，请直接返回 JSON 数据。"),
        new HumanMessage("介绍一下杨振宁")
    ]);

    console.log(chalk.green("\n✅ 收到响应 (纯净 JSON):"));
    console.log(res.content); 

    const data = JSON.parse(res.content);
    console.log(chalk.cyan("\n📋 解析后的对象:"));
    console.log(data);
}

testNativeJsonSchema().catch(console.error);


/**
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\output-control-test\structured-json-schema.mjs
🧪 测试原生 JSON Schema 模式...


✅ 收到响应 (纯净 JSON):
{
  "name": "杨振宁",
  "birth_date": "1922年10月1日",
  "birth_place": "安徽省合肥市",
  "nationality": "美国（后恢复中国国籍）",
  "occupation": "物理学家",
  "education": "西南联合大学、芝加哥大学",
  "notable_awards": ["1957年诺贝尔物理学奖"],
  "contribution": "宇称不守恒理论的提出者之一，对粒子物理学和统计力学有重要贡献",
  "additional_info": "杨振宁教授是20世纪最重要的物理学家之一，他与中国科学院有着长期的合作关系，并为中国科学教育事业做出了巨大贡献。"
}

📋 解析后的对象:
{
  name: '杨振宁',
  birth_date: '1922年10月1日',
  birth_place: '安徽省合肥市',
  nationality: '美国（后恢复中国国籍）',
  occupation: '物理学家',
  education: '西南联合大学、芝加哥大学',
  notable_awards: [ '1957年诺贝尔物理学奖' ],
  contribution: '宇称不守恒理论的提出者之一，对粒子物理学和统计力学有重要贡献',
  additional_info: '杨振宁教授是20世纪最重要的物理学家之一，他与中国科学院有着长期的合作关系，并为中国科学教育事业做出了巨大贡献。'
}
 */