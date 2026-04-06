import 'dotenv/config';
import { ChatOpenAI } from '@langchain/openai';
import { z } from 'zod';
import { AIMessage, HumanMessage, SystemMessage, ToolMessage } from '@langchain/core/messages';

// 1. 初始化模型
const model = new ChatOpenAI({
  modelName: process.env.MODEL_NAME,
  apiKey: process.env.OPENAI_API_KEY,
  temperature: 0,
  configuration: {
    baseURL: process.env.OPENAI_BASE_URL,
  },
});

// 2. 定义 tool schema
const weatherSchema = z.object({
  city: z.string().describe('城市名称，例如北京、上海、广州'),
  date: z.string().describe('日期，例如今天、明天'),
  unit: z.enum(['celsius', 'fahrenheit']).describe('温度单位'),
});

// 3. 绑定 tool schema 给模型
const modelWithTool = model.bindTools([
  {
    name: 'get_weather',
    description: '查询指定城市和日期的天气信息',
    schema: weatherSchema,
  },
]);

// 4. 本地 tool 实现（演示版）
async function getWeatherTool(args) {
  const mockDb = {
    北京: { celsius: '6°C', fahrenheit: '42.8°F', condition: '晴', humidity: '35%' },
    上海: { celsius: '12°C', fahrenheit: '53.6°F', condition: '多云', humidity: '60%' },
    广州: { celsius: '18°C', fahrenheit: '64.4°F', condition: '小雨', humidity: '78%' },
  };

  // 如果数据库里没有这个城市，就返回 ?? 右边的默认值，反之返回左边的 mockDb[args.city]
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

// 5. 尝试把流式 args 片段拼成完整 JSON
function tryParseJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

async function main() {
  const userQuestion = '请帮我查询北京今天的天气，并根据查询结果用中文简洁回答我。';

  const systemMessage = new SystemMessage(
    '你是一个天气助手。遇到天气查询问题时，优先调用工具。拿到工具结果后，再用自然语言回答用户。'
  );
  const humanMessage = new HumanMessage(userQuestion);

  try {
    console.log('🌊 第一步：让模型流式生成 tool call 参数\n');

    const stream = await modelWithTool.stream([systemMessage, humanMessage]);

    let toolCallId = null;
    let toolName = null;
    let argsBuffer = '';
    let parsedArgs = null;

    for await (const chunk of stream) {
      // 有些 chunk 可能没有 tool_call_chunks，直接跳过
      if (!chunk.tool_call_chunks || chunk.tool_call_chunks.length === 0) {
        continue;
      }

      const tc = chunk.tool_call_chunks[0];

      // id / name 可能分多次出现，拿到就记住
      if (tc.id) toolCallId = tc.id;
      if (tc.name) toolName = tc.name;

      // args 是字符串碎片，持续拼接
      if (typeof tc.args === 'string' && tc.args.length > 0) {
        argsBuffer += tc.args;

        console.log('📡 收到新的 args 片段:');
        console.log(tc.args);
        console.log('');
        console.log('🧩 当前累计的 argsBuffer:');
        console.log(argsBuffer);
        console.log('='.repeat(80));
      }

      // 每次拼接后都尝试 parse，看是否已经成为完整 JSON
      const maybeArgs = tryParseJson(argsBuffer);
      if (maybeArgs) {
        parsedArgs = maybeArgs;
      }
    }

    if (!toolName) {
      throw new Error('模型没有生成 tool name，无法继续。');
    }

    if (!parsedArgs) {
      throw new Error('流式参数最终没有拼成合法 JSON，无法调用 tool。');
    }

    if (!toolCallId) {
      // 某些兼容环境下可能不给 id，这里兜底
      toolCallId = 'tool_call_fallback_001';
    }

    console.log('\n✅ 第二步：参数已完整，执行本地 tool\n');
    console.log('最终 tool name:', toolName);
    console.log('最终 tool args:');
    console.log(JSON.stringify(parsedArgs, null, 2));
    console.log('');

    // 6. 执行本地 tool
    let toolResult;
    if (toolName === 'get_weather') {
      toolResult = await getWeatherTool(parsedArgs);
    } else {
      throw new Error(`未知工具: ${toolName}`);
    }

    console.log('🛠️ Tool 返回结果:');
    console.log(JSON.stringify(toolResult, null, 2));
    console.log('');

    // 7. 构造“模型刚刚发起工具调用”的 AIMessage
    const assistantToolCallMessage = new AIMessage({
      content: '',
      tool_calls: [
        {
          id: toolCallId,
          name: toolName,
          args: parsedArgs,
        },
      ],
    });

    // 8. 构造 ToolMessage，把工具执行结果回传给模型
    const toolMessage = new ToolMessage({
      tool_call_id: toolCallId,
      content: JSON.stringify(toolResult, null, 2),
    });

    console.log('🤖 第三步：把 ToolMessage 回传给模型，生成最终回答\n');

    const finalResponse = await model.invoke([
      systemMessage,
      humanMessage,
      assistantToolCallMessage,
      toolMessage,
    ]);

    console.log('✅ 最终自然语言回答:\n');
    console.log(finalResponse.content);
  } catch (error) {
    console.error('❌ 错误:', error.message);
    console.error(error);
  }
}

main();

/**
 * PS D:\AI_Agent_Project\output-parser-test> node .\src\stream-tool-calls-final-answer.mjs 
🌊 第一步：让模型流式生成 tool call 参数

📡 收到新的 args 片段:
{"city": "

🧩 当前累计的 argsBuffer:
{"city": "
================================================================================
📡 收到新的 args 片段:
北京", "date": "

🧩 当前累计的 argsBuffer:
{"city": "北京", "date": "
================================================================================
📡 收到新的 args 片段:
今天", "unit": "

🧩 当前累计的 argsBuffer:
{"city": "北京", "date": "今天", "unit": "
================================================================================
📡 收到新的 args 片段:
celsius"}

🧩 当前累计的 argsBuffer:
{"city": "北京", "date": "今天", "unit": "celsius"}
================================================================================

✅ 第二步：参数已完整，执行本地 tool

最终 tool name: get_weather
最终 tool args:
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

🤖 第三步：把 ToolMessage 回传给模型，生成最终回答

✅ 最终自然语言回答:

北京今天天气晴，气温6°C，湿度35%。
 */