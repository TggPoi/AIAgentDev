import { Inject, Injectable } from '@nestjs/common';
import { ChatOpenAI } from '@langchain/openai';
import { AIMessage, AIMessageChunk, createAgent, HumanMessage, SystemMessage, ToolMessage } from 'langchain';
import { UIMessage } from 'ai';
import { toBaseMessages, toUIMessageStream } from '@ai-sdk/langchain';

@Injectable()
export class AiService {
  private readonly agent: ReturnType<typeof createAgent>;

  constructor(
    @Inject('WEB_SEARCH_TOOL') private readonly webSearchTool: any,
    @Inject('SEND_MAIL_TOOL') private readonly sendMailTool: any,
    @Inject('CHAT_MODEL') model: ChatOpenAI
  ) {
    this.agent = createAgent({
        model,
        tools: [this.webSearchTool, this.sendMailTool],
        systemPrompt:
          '你是 AI 助手，需要最新信息、事实核查或联网信息时，请使用 web_search 工具搜索后再作答。发送邮件用 send_mail 工具',
      });
  }

  async stream(messages: UIMessage[]) {
    /**
     * 前端传来：
        [
          {
            "id": "1",
            "role": "user",
            "parts": [
              {
                "type": "text",
                "text": "北京今天的天气"
              }
            ]
          }
        ]

        toBaseMessages 后，变成 LangChain 能处理的消息，概念上类似：

        [
          new HumanMessage("北京今天的天气")
        ]

        这样 createAgent() 才能继续调用模型。
     */
    const lcMessages = await toBaseMessages(messages);

    /**
     * 
      | streamMode | 作用                                   |
      | ---------- | -------------------------------------------- |
      | `messages` | 流式输出消息相关内容，例如 AIMessageChunk、tool call chunk |
      | `values`   | 输出 Agent 执行状态相关的值，方便适配器还原完整 UI 流             |

     */
    const lgStream = await this.agent.stream(
      { messages: lcMessages },
      //让 Agent 在流式执行时，产出可被适配器转换的消息流 / 状态流
      //这里的目的是让 toUIMessageStream 有足够的信息把 LangChain 的流转换成 AI SDK 的 Data Stream Protocol。
      {
        streamMode: ['messages', 'values'],
        recursionLimit: 30,// 限制循环次数，避免 Agent 无限调用工具导致内存泄漏
      },
    );

    /**
     * 把 LangChain 里的：
        AI 文本 chunk
        tool call chunk
        tool result

        转换成 AI SDK Data Stream Protocol 能表达的：

        text-start
        text-delta
        text-end
        tool-input-start
        tool-input-delta
        tool-input-available
        tool-output-available

        通过 @ai-sdk/langchain 把 stream 转为基于 Data Stream Protocol 的 SSE 流。
        
        toUIMessageStream = LangChain 流 -> AGUI 协议流 的转换器
     */
    return toUIMessageStream(lgStream as AsyncIterable<AIMessageChunk>);
  }
}