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

// 使用 zod 定义结构化输出格式
const schema = z.object({
    name: z.string().describe("姓名"),
    birth_year: z.number().describe("出生年份"),
    death_year: z.number().describe("去世年份"),
    nationality: z.string().describe("国籍"),
    occupation: z.string().describe("职业"),
    famous_works: z.array(z.string()).describe("著名作品列表"),
    biography: z.string().describe("简短传记")
});

const structuredModel = model.withStructuredOutput(schema);

const prompt = `详细介绍莫扎特的信息。`;

console.log("🌊 流式结构化输出演示（withStructuredOutput）\n");

try {
    const stream = await structuredModel.stream(prompt);

    let chunkCount = 0;
    let result = null;

    console.log("📡 接收流式数据:\n");

    for await (const chunk of stream) {
        chunkCount++;
        result = chunk;

        console.log(`[Chunk ${chunkCount}]`);
        console.log(JSON.stringify(chunk, null, 2));
    }

    console.log(`\n✅ 共接收 ${chunkCount} 个数据块\n`);

    if (result) {
        console.log("📊 最终结构化结果:\n");
        console.log(JSON.stringify(result, null, 2));

        console.log("\n📝 格式化输出:");
        console.log(`姓名: ${result.name}`);
        console.log(`出生年份: ${result.birth_year}`);
        console.log(`去世年份: ${result.death_year}`);
        console.log(`国籍: ${result.nationality}`);
        console.log(`职业: ${result.occupation}`);
        console.log(`著名作品: ${result.famous_works.join(', ')}`);
        console.log(`传记: ${result.biography}`);
    }

} catch (error) {
    console.error("\n❌ 错误:", error.message);
}

/**
 * 用了 withStructuredOutput 之后，它会在 json 生成完通过校验后再返回（底层是 tool calls）
 * 所以只有一个 chunk 包含完整 json，但是这样就不是流式了，而是直接把整个回答内容作为一个chunk返回了
 */

/** 相比stream-normal.mjs，这里我们使用了 withStructuredOutput 来定义了一个结构化的输出格式（使用 zod 定义了一个 schema），模型会根据这个 schema 来生成符合结构化要求的输出，
 * 并且接收到的内容都是自己需要的内容，而不是包含了一堆没用的冗余信息，输出内容的长度相比普通流式输出会大大减少，且更容易解析和使用。
 * 
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\stream-with-structured-output.mjs
🌊 流式结构化输出演示（withStructuredOutput）

📡 接收流式数据:

[Chunk 1]
{
  "name": "Wolfgang Amadeus Mozart",
  "birth_year": 1756,
  "death_year": 1791,
  "nationality": "奥地利（生于萨尔茨堡，当时属神圣罗马帝国）",
  "occupation": "作曲家、钢琴家、小提琴家、指挥家",
  "famous_works": [
    "《G小调第40号交响曲》（K.550）——古典悲剧性与抒情性的巅峰融合",
    "《C大调第41号‘朱庇特’交响曲》（K.551）——复调技艺与主调结构的集大成之作",
    "歌剧《费加罗的婚礼》（K.492）——社会批判与人性光辉并存的喜歌剧典范",
    "歌剧《唐璜》（K.527）——道德寓言与音乐戏剧张力的划时代杰作",
    "歌剧《魔笛》（K.620）——德语歌唱剧巅峰，融合共济会象征、启蒙思想与民间童话",
    "《A大调单簧管协奏曲》（K.622）——单簧管文献中最具诗意与哲思的不朽之作",
    "《安魂曲》（K.626）——未完成的临终绝唱，充满神秘性与崇高感，由弟子苏斯迈尔续完"
  ],
  "biography": "沃尔夫冈·阿马德乌斯·莫扎特（Wolfgang Amadeus Mozart，1756年1月27日－1791年12月5日）是奥地利作曲家、钢琴家、小提琴家，欧洲古典主义音乐最杰出的代表人物之一。他出生于神圣罗马帝国萨尔茨堡（ 
今奥地利萨尔茨堡市），3岁显露惊人音乐天赋，5岁作曲，6岁随父巡演欧洲宫廷，被誉为‘神童’（Wunderkind）。一生虽仅35载，却创作了逾600部作品（Köchel目录编号K.1–K.626），涵盖交响曲、协奏曲、歌剧、室内乐、宗教 
音乐、艺术歌曲等几乎所有当时主流体裁，且几乎部部精妙，兼具技术深度、情感真挚与形式完美。"
}

✅ 共接收 1 个数据块

📊 最终结构化结果:

{
  "name": "Wolfgang Amadeus Mozart",
  "birth_year": 1756,
  "death_year": 1791,
  "nationality": "奥地利（生于萨尔茨堡，当时属神圣罗马帝国）",
  "occupation": "作曲家、钢琴家、小提琴家、指挥家",
  "famous_works": [
    "《G小调第40号交响曲》（K.550）——古典悲剧性与抒情性的巅峰融合",
    "《C大调第41号‘朱庇特’交响曲》（K.551）——复调技艺与主调结构的集大成之作",
    "歌剧《费加罗的婚礼》（K.492）——社会批判与人性光辉并存的喜歌剧典范",
    "歌剧《唐璜》（K.527）——道德寓言与音乐戏剧张力的划时代杰作",
    "歌剧《魔笛》（K.620）——德语歌唱剧巅峰，融合共济会象征、启蒙思想与民间童话",
    "《A大调单簧管协奏曲》（K.622）——单簧管文献中最具诗意与哲思的不朽之作",
    "《安魂曲》（K.626）——未完成的临终绝唱，充满神秘性与崇高感，由弟子苏斯迈尔续完"
  ],
  "biography": "沃尔夫冈·阿马德乌斯·莫扎特（Wolfgang Amadeus Mozart，1756年1月27日－1791年12月5日）是奥地利作曲家、钢琴家、小提琴家，欧洲古典主义音乐最杰出的代表人物之一。他出生于神圣罗马帝国萨尔茨堡（ 
今奥地利萨尔茨堡市），3岁显露惊人音乐天赋，5岁作曲，6岁随父巡演欧洲宫廷，被誉为‘神童’（Wunderkind）。一生虽仅35载，却创作了逾600部作品（Köchel目录编号K.1–K.626），涵盖交响曲、协奏曲、歌剧、室内乐、宗教 
音乐、艺术歌曲等几乎所有当时主流体裁，且几乎部部精妙，兼具技术深度、情感真挚与形式完美。"
}

📝 格式化输出:
姓名: Wolfgang Amadeus Mozart
出生年份: 1756
去世年份: 1791
国籍: 奥地利（生于萨尔茨堡，当时属神圣罗马帝国）
职业: 作曲家、钢琴家、小提琴家、指挥家
著名作品: 《G小调第40号交响曲》（K.550）——古典悲剧性与抒情性的巅峰融合, 《C大调第41号‘朱庇特’交响曲》（K.551）——复调技艺与主调结构的集大成之作, 歌剧《费加罗的婚礼》（K.492）——社会批判与人性光辉并存的喜 
歌剧典范, 歌剧《唐璜》（K.527）——道德寓言与音乐戏剧张力的划时代杰作, 歌剧《魔笛》（K.620）——德语歌唱剧巅峰，融合共济会象征、启蒙思想与民间童话, 《A大调单簧管协奏曲》（K.622）——单簧管文献中最具诗意与哲思
的不朽之作, 《安魂曲》（K.626）——未完成的临终绝唱，充满神秘性与崇高感，由弟子苏斯迈尔续完
传记: 沃尔夫冈·阿马德乌斯·莫扎特（Wolfgang Amadeus Mozart，1756年1月27日－1791年12月5日）是奥地利作曲家、钢琴家、小提琴家，欧洲古典主义音乐最杰出的代表人物之一。他出生于神圣罗马帝国萨尔茨堡（今奥地利萨 
尔茨堡市），3岁显露惊人音乐天赋，5岁作曲，6岁随父巡演欧洲宫廷，被誉为‘神童’（Wunderkind）。一生虽仅35载，却创作了逾600部作品（Köchel目录编号K.1–K.626），涵盖交响曲、协奏曲、歌剧、室内乐、宗教音乐、艺术 
歌曲等几乎所有当时主流体裁，且几乎部部精妙，兼具技术深度、情感真挚与形式完美。
 */