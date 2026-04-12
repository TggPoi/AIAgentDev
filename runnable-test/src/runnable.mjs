import 'dotenv/config';
import { StructuredOutputParser } from "@langchain/core/output_parsers";
import { PromptTemplate } from "@langchain/core/prompts";
import { ChatOpenAI } from "@langchain/openai";
import { RunnableSequence } from "@langchain/core/runnables";
import { z } from "zod";

const model = new ChatOpenAI({
    modelName: process.env.MODEL_NAME,
    apiKey: process.env.OPENAI_API_KEY,
    temperature: 0,
    configuration: {
        baseURL: process.env.OPENAI_BASE_URL,
    },
});

// 定义输出结构 schema
const schema = z.object({
    translation: z.string().describe("翻译后的英文文本"),
    keywords: z.array(z.string()).length(3).describe("3个关键词")
});

const outputParser = StructuredOutputParser.fromZodSchema(schema);

const promptTemplate = PromptTemplate.fromTemplate(
    '将以下文本翻译成英文，然后总结为3个关键词。\n\n文本：{text}\n\n{format_instructions}'
);

//pipe 的源码里，也是返回 RunnableSequence，下面这两个写法是等价的，Runnable更简洁
// const chain = promptTemplate
//     .pipe(model)
//     .pipe(outputParser);

const chain = RunnableSequence.from([
    promptTemplate,
    model,
    outputParser
]);

const input = { 
    text: 'LangChain 是一个强大的 AI 应用开发框架',
    format_instructions: outputParser.getFormatInstructions()
};

const result = await chain.invoke(input);

console.log('✅ 最终结果:');
console.log(result);

/**
 * PS D:\AI_Agent_Project\runnable-test> node .\src\runnable.mjs
✅ 最终结果:
{
  translation: 'LangChain is a powerful AI application development framework.',
  keywords: [ 'LangChain', 'AI', 'Framework' ]
}
 */