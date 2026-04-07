import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import { z } from 'zod';

/**
 * 使用withStructuredOutput 根据模型能力，底层自动选择 tool call 或 output parser 路线。
 */

const model = new ChatOpenAI({
    modelName: process.env.MODEL_NAME,
    apiKey: process.env.OPENAI_API_KEY,
    temperature: 0,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
    //modelKwargs：Holds any additional parameters that are valid to pass to openai.createCompletion that are not explicitly specified on this class.
    modelKwargs: {
        enable_thinking: false,// 关闭模型思考过程中的中间步骤输出，直接返回最终结果
        response_format: {// 直接告诉模型返回 JSON 对象格式，适用于支持 response_format 的模型，例如 qwen3.5-plus，但是Prompt必须包含json，否则会报错 400 BadRequestError: 400 <400> InternalError.Algo.InvalidParameter: 'messages' must contain the word 'json' in some form, to use 'response_format' of type 'json_object'.
            type: "json_object"
        }
    }
});

// 定义结构化输出的 schema
const scientistSchema = z.object({
    name: z.string().describe("科学家的全名"),
    birth_year: z.number().describe("出生年份"),
    nationality: z.string().describe("国籍"),
    fields: z.array(z.string()).describe("研究领域列表"),
});

// 使用 withStructuredOutput 方法 qwen3.5-plus模型不支持json mode，返回的json格式都是undefined，最好换个模型
const structuredModel = model.withStructuredOutput(scientistSchema,{method:'functionCalling'});

// 调用模型
const result = await model.invoke("请介绍一下爱因斯坦，并严格以 JSON 格式输出结果。");

console.log("结构化结果:", result);
// console.log("结构化结果:", JSON.stringify(result, null, 2));
// console.log(`\n姓名: ${result.name}`);
// console.log(`出生年份: ${result.birth_year}`);
// console.log(`国籍: ${result.nationality}`);
// console.log(`研究领域: ${result.fields.join(', ')}`);

/**
PS D:\AI_Agent_Project\output-parser-test> node .\src\apiTest-with-structured-output-copy.mjs
结构化结果: AIMessage {
  "id": "chatcmpl-a8cf6d27-38a0-9f8b-acad-4514dd14098e",
  "content": "{\n  \"name\": \"阿尔伯特·爱因斯坦\",\n  \"birth_date\": \"1879-03-14\",\n  \"death_date\": \"1955-04-18\",\n  \"nationality\": \"德国/瑞士/美国\",\n  \"profession\": \"理论物理学家\",\n  
\"major_contributions\": [\n    \"狭义相对论\",\n    \"广义相对论\",\n    \"光电效应解释\",\n    \"质能方程 (E=mc²)\"\n  ],\n  \"awards\": [\n    {\n      \"name\": \"诺贝尔物理学奖\",\n      \"year\": 
1921,\n      \"reason\": \"对理论物理学的贡献，特别是发现了光电效应定律\"\n    }\n  ],\n  \"brief_biography\": \"阿尔伯特·爱因斯坦是 20 世纪最伟大的科学家之一，以其相对论彻底改变了人类对时空、引力和宇宙
的理解。他出生于德国乌尔姆，后移居瑞士和美国。除了科学成就，他还是一位著名的和平主义者和社会活动家。\"\n}",
  "additional_kwargs": {},
  "response_metadata": {
    "tokenUsage": {
      "promptTokens": 27,
      "completionTokens": 236,
      "totalTokens": 263
    },
    "finish_reason": "stop",
    "model_provider": "openai",
    "model_name": "qwen3.5-plus"
  },
  "tool_calls": [],
  "invalid_tool_calls": [],
  "usage_metadata": {
    "output_tokens": 236,
    "input_tokens": 27,
    "total_tokens": 263,
    "input_token_details": {},
    "output_token_details": {}
  }
}
 */