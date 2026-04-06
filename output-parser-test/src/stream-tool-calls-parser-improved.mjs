import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import { JsonOutputToolsParser } from '@langchain/core/output_parsers/openai_tools';
import { z } from 'zod';

// 1. 初始化模型
const model = new ChatOpenAI({
  modelName: process.env.MODEL_NAME,
  apiKey: process.env.OPENAI_API_KEY,
  temperature: 0,
  configuration: {
    baseURL: process.env.OPENAI_BASE_URL,
  },
});

// 2. 定义一个更容易理解的 tool schema
// 目标：模型生成参数时，只要 city/date/unit 这三个字段齐了，程序就能立刻调用 tool
const weatherSchema = z.object({
  city: z.string().describe('城市名称，例如北京、上海'),
  date: z.string().describe('日期，例如今天、明天'),
  unit: z.enum(['celsius', 'fahrenheit']).describe('温度单位'),
});

// 3. 绑定“工具”给模型
// 注意：这里不需要真的把工具实现绑定进去执行，先让模型按这个 schema 生成 tool call 参数
const modelWithTool = model.bindTools([
  {
    name: 'get_weather',
    description: '查询指定城市和日期的天气信息',
    schema: weatherSchema,
  },
]);

// 4. 用 JsonOutputToolsParser 把流式 tool_call_chunks 尽量拼成结构化对象
const parser = new JsonOutputToolsParser();
const chain = modelWithTool.pipe(parser);

// 5. 一个本地假工具：只做演示
async function getWeatherTool(args) {
  const mockDb = {
    北京: { celsius: '6°C', fahrenheit: '42.8°F', condition: '晴', humidity: '35%' },
    上海: { celsius: '12°C', fahrenheit: '53.6°F', condition: '多云', humidity: '60%' },
    广州: { celsius: '18°C', fahrenheit: '64.4°F', condition: '小雨', humidity: '78%' },
  };

  const cityData = mockDb[args.city] ?? {
    celsius: '20°C',
    fahrenheit: '68°F',
    condition: '未知',
    humidity: '50%',
  };

  return {
    city: args.city,
    date: args.date,
    unit: args.unit,
    temperature: args.unit === 'fahrenheit' ? cityData.fahrenheit : cityData.celsius,
    condition: cityData.condition,
    humidity: cityData.humidity,
    source: '本地演示数据',
  };
}

// 6. 判断“现在的参数是否已经足够完整，可以调用 tool”
// 这里故意写得很直白，便于理解
function isReadyToCallTool(args) {
  if (!args) return false;
  if (typeof args.city !== 'string' || args.city.trim() === '') return false;
  if (typeof args.date !== 'string' || args.date.trim() === '') return false;
  if (args.unit !== 'celsius' && args.unit !== 'fahrenheit') return false;
  return true;
}

async function main() {
  try {
    console.log('🌊 流式 Tool Calls + 提前调用 Tool 演示\n');

    const prompt = `
请帮我调用工具查询“北京今天的天气”，并使用工具参数返回。
请确保工具参数里包含：
- city
- date
- unit

其中 unit 必须是 "celsius" 或 "fahrenheit"。
`;

    const stream = await chain.stream(prompt);

    let chunkIndex = 0;
    let toolCalled = false; // 保证只调用一次
    let latestArgs = null;

    console.log('📡 开始接收流式结构化参数:\n');

    for await (const chunk of stream) {
      chunkIndex++;

      if (!Array.isArray(chunk) || chunk.length === 0) {
        continue;
      }

      const toolCall = chunk[0];
      const args = toolCall.args || {};
      latestArgs = args;

      console.log(`[Chunk ${chunkIndex}] 当前参数进度:`);
      console.log(JSON.stringify(args, null, 2));
      console.log('');

      // 一旦参数够完整，而且还没调用过，就立刻调用本地 tool
      if (!toolCalled && isReadyToCallTool(args)) {
        toolCalled = true;

        console.log('🟢 参数已足够完整，立刻调用本地 tool');
        console.log('📥 触发调用的参数:');
        console.log(JSON.stringify(args, null, 2));
        console.log('');

        const toolResult = await getWeatherTool(args);

        console.log('🛠️ Tool 返回结果:');
        console.log(JSON.stringify(toolResult, null, 2));
        console.log('');
      }
    }

    console.log('✅ 流式输出结束\n');

    console.log('📌 最终拼出来的参数对象:');
    console.log(JSON.stringify(latestArgs, null, 2));
  } catch (error) {
    console.error('❌ 错误:', error.message);
    console.error(error);
  }
}

main();


/**
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\stream-tool-calls-parser-improved.mjs
🌊 流式 Tool Calls + 提前调用 Tool 演示

📡 开始接收流式结构化参数:

[Chunk 1] 当前参数进度:
{}

[Chunk 2] 当前参数进度:
{
  "city": ""
}

[Chunk 3] 当前参数进度:
{
  "city": "北京",
  "date": ""
}

[Chunk 4] 当前参数进度:
{
  "city": "北京",
  "date": "今天",
  "unit": ""
}

[Chunk 5] 当前参数进度:
{
  "city": "北京",
  "date": "今天",
  "unit": "celsius"
}

🟢 参数已足够完整，立刻调用本地 tool
📥 触发调用的参数:
{
  "city": "北京",
  "date": "今天",
  "unit": "celsius"
}

🛠️ Tool 返回结果:
{
  "city": "北京",
  "date": "今天",
  "unit": "celsius",
  "temperature": "6°C",
  "condition": "晴",
  "humidity": "35%",
  "source": "本地演示数据"
}

✅ 流式输出结束

📌 最终拼出来的参数对象:
{
  "city": "北京",
  "date": "今天",
  "unit": "celsius"
}
 */