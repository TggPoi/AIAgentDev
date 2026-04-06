import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import { StructuredOutputParser } from '@langchain/core/output_parsers';
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

const parser = StructuredOutputParser.fromZodSchema(schema);

const prompt = `详细介绍莫扎特的信息。\n\n${parser.getFormatInstructions()}`;

console.log("🌊 流式结构化输出演示\n");

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

    // 解析完整内容为结构化数据
    const result = await parser.parse(fullContent);

    console.log("📊 解析后的结构化结果:\n");
    console.log(JSON.stringify(result, null, 2));

    console.log("\n📝 格式化输出:");
    console.log(`姓名: ${result.name}`);
    console.log(`出生年份: ${result.birth_year}`);
    console.log(`去世年份: ${result.death_year}`);
    console.log(`国籍: ${result.nationality}`);
    console.log(`职业: ${result.occupation}`);
    console.log(`著名作品: ${result.famous_works.join(', ')}`);
    console.log(`传记: ${result.biography}`);

} catch (error) {
    console.error("\n❌ 错误:", error.message);
}


/** 对比stream-with-structured-output可以看到回答的内容是边打印边生成的，这才是真正的流式生成，而不是像stream-with-structured-output那样等整个内容生成完才返回一个chunk，虽然它也叫流式输出，但其实并没有真正的流式输出，而是把整个内容作为一个chunk返回了，这样就失去了流式输出的意义了。
 * 
 * 所以流式的情况下，用 output parser 还是更适合的。
 * 
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\stream-structured-output-parser.mjs
🌊 流式结构化输出演示

📡 接收流式数据:

```json
{      
  "name": "沃尔夫冈·阿马德乌斯·莫扎特",
  "birth_year": 1756,
  "death_year": 1791,
  "nationality": "奥地利",
  "occupation": "作曲家、钢琴家、小提琴家",
  "famous_works": ["《G小调第四十交响曲》", "《C大调第四十一交响曲“朱庇特”》", "歌剧《费加罗的婚礼》", "歌剧《唐璜》", "歌剧《魔笛》", "《A大调单簧管协奏曲》", "《安魂曲》（未完成）"],
  "biography": "沃尔夫冈·阿马德乌斯·莫扎特（1756年1月27日－1791年12月5日）是奥地利古典主义时期最具代表性的作曲家之一，被誉为音乐神童。他自幼展现出非凡的音乐天赋，六岁起便随父亲在欧洲各地巡演并开始创作。
莫扎特一生创作了逾600部作品，涵盖交响曲、协奏曲、室内乐、歌剧、宗教音乐等多种体裁，其音乐以旋律优美、结构精巧、情感真挚而著称。尽管生活困顿、健康恶化，他仍于短暂的一生中持续高产，对后世音乐发展影响深远
。35岁时因病早逝，葬于维也纳普通市民墓地，身后留下未完成的《安魂曲》成为音乐史上永恒的传奇。"
}
```

✅ 共接收 80 个数据块

📊 解析后的结构化结果:

{
  "name": "沃尔夫冈·阿马德乌斯·莫扎特",
  "birth_year": 1756,
  "death_year": 1791,
  "nationality": "奥地利",
  "occupation": "作曲家、钢琴家、小提琴家",
  "famous_works": [
    "《G小调第四十交响曲》",
    "《C大调第四十一交响曲“朱庇特”》",
    "歌剧《费加罗的婚礼》",
    "歌剧《唐璜》",
    "歌剧《魔笛》",
    "《A大调单簧管协奏曲》",
    "《安魂曲》（未完成）"
  ],
  "biography": "沃尔夫冈·阿马德乌斯·莫扎特（1756年1月27日－1791年12月5日）是奥地利古典主义时期最具代表性的作曲家之一，被誉为音乐神童。他自幼展现出非凡的音乐天赋，六岁起便随父亲在欧洲各地巡演并开始创作。
莫扎特一生创作了逾600部作品，涵盖交响曲、协奏曲、室内乐、歌剧、宗教音乐等多种体裁，其音乐以旋律优美、结构精巧、情感真挚而著称。尽管生活困顿、健康恶化，他仍于短暂的一生中持续高产，对后世音乐发展影响深远 
。35岁时因病早逝，葬于维也纳普通市民墓地，身后留下未完成的《安魂曲》成为音乐史上永恒的传奇。"
}

📝 格式化输出:
姓名: 沃尔夫冈·阿马德乌斯·莫扎特
出生年份: 1756
去世年份: 1791
国籍: 奥地利
职业: 作曲家、钢琴家、小提琴家
著名作品: 《G小调第四十交响曲》, 《C大调第四十一交响曲“朱庇特”》, 歌剧《费加罗的婚礼》, 歌剧《唐璜》, 歌剧《魔笛》, 《A大调单簧管协奏曲》, 《安魂曲》（未完成）
传记: 沃尔夫冈·阿马德乌斯·莫扎特（1756年1月27日－1791年12月5日）是奥地利古典主义时期最具代表性的作曲家之一，被誉为音乐神童。他自幼展现出非凡的音乐天赋，六岁起便随父亲在欧洲各地巡演并开始创作。莫扎特一生
创作了逾600部作品，涵盖交响曲、协奏曲、室内乐、歌剧、宗教音乐等多种体裁，其音乐以旋律优美、结构精巧、情感真挚而著称。尽管生活困顿、健康恶化，他仍于短暂的一生中持续高产，对后世音乐发展影响深远。35岁时因 
病早逝，葬于维也纳普通市民墓地，身后留下未完成的《安魂曲》成为音乐史上永恒的传奇。
 */