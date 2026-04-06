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
    death_year: z.number().optional().describe("去世年份，如果还在世则不填"),
    nationality: z.string().describe("国籍"),
    fields: z.array(z.string()).describe("研究领域列表"),
    achievements: z.array(z.string()).describe("主要成就"),
    biography: z.string().describe("简短传记")
});

// 绑定工具到模型
const modelWithTool = model.bindTools([
    {
        name: "extract_scientist_info",
        description: "提取和结构化科学家的详细信息",
        schema: scientistSchema
    }
]);

console.log("🌊 流式 Tool Calls 演示 - 直接打印原始 tool_calls_chunk\n");

try {
    // 开启流式输出
    const stream = await modelWithTool.stream("详细介绍牛顿的生平和成就");

    console.log("📡 实时输出流式 tool_calls_chunk:\n");

    let chunkIndex = 0;

    for await (const chunk of stream) {
        chunkIndex++;

        //打印tool的详细信息，但是可以看到并没有调用tool，因为参数还不完整，没有 tool_calls 信息
        //console.log(chunk);

        // 直接打印每个 chunk 的 tool_calls 信息
        if (chunk.tool_call_chunks && chunk.tool_call_chunks.length > 0) {
            process.stdout.write(chunk.tool_call_chunks[0].args || '');
        }
    }

    console.log("\n\n✅ 流式输出完成");

} catch (error) {
    console.error("\n❌ 错误:", error.message);
    console.error(error);
}



/**
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\stream-tool-calls-raw.mjs          
🌊 流式 Tool Calls 演示 - 直接打印原始 tool_calls_chunk

📡 实时输出流式 tool_calls_chunk:

{"name": "艾萨克·牛顿", "birth_year": 1643, "death_year": 1727, "nationality": "英国", "fields": ["物理学", "数学", "天文学", "自然哲学"], "achievements": ["提出万有引力定律", "建立经典力学体系（《自然
哲学的数学原理》）", "发明微积分（与莱布尼茨各自独立发展）", "发现光的色散现象并发展反射式望远镜", "提出运动三定律"], "biography": "艾萨克·牛顿（1643–1727）是英国物理学家、数学家、天文学家和自然哲学家，
被广泛认为是科学革命的关键人物。他出生于英格兰林肯郡伍尔索普，早年在剑桥大学三一学院学习并任教。牛顿在1687年出版的《自然哲学的数学原理》中系统阐述了运动定律和万有引力定律，奠定了经典力学的基础。他在光学
领域亦贡献卓著，通过棱镜实验证明白光由多种颜色组成，并设计了首台实用反射式望远镜。晚年任英国皇家铸币局局长，并被封为爵士。"}

✅ 流式输出完成
 */