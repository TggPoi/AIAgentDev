import { Inject, Injectable } from '@nestjs/common';
import { ChatOpenAI } from '@langchain/openai';
import { PromptTemplate } from '@langchain/core/prompts';
import type { Runnable } from '@langchain/core/runnables';
import { StringOutputParser } from '@langchain/core/output_parsers';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { AI_TTS_STREAM_EVENT, type AiTtsStreamEvent } from '../common/stream-events';

@Injectable()
export class AiService {
  private readonly chain: Runnable;

  constructor(
    @Inject('CHAT_MODEL') model: ChatOpenAI,
    private readonly eventEmitter: EventEmitter2,
  ) {
    const prompt = PromptTemplate.fromTemplate('请回答以下问题：\n\n{query}');
    this.chain = prompt.pipe(model).pipe(new StringOutputParser());
  }

  async *streamChain(query: string, ttsSessionId?: string): AsyncGenerator<string> {
    try {
      const stream = await this.chain.stream({ query });

      for await (const chunk of stream) {
        if (ttsSessionId) {
          // 在接收到 AI 生成的每个文本块时，发送一个 'chunk' 事件到 TTS 转发服务，包含会话 ID 和文本块内容，以便转发服务将这些文本块逐步发送给腾讯云 TTS 服务进行语音合成
          const event: AiTtsStreamEvent = {
            type: 'chunk',
            sessionId: ttsSessionId,
            chunk,
          };
          this.eventEmitter.emit(AI_TTS_STREAM_EVENT, event);
        }
        yield chunk;
      }

      if (ttsSessionId) {
        // 在 AI 流式处理完成后，发送一个 'end' 事件到 TTS 转发服务，通知它当前的 TTS 流式会话已经结束，可以进行清理和资源释放等后续处理
        const endEvent: AiTtsStreamEvent = { type: 'end', sessionId: ttsSessionId };
        this.eventEmitter.emit(AI_TTS_STREAM_EVENT, endEvent);
      }
    } catch (error) {
      if (ttsSessionId) {
        const errorEvent: AiTtsStreamEvent = {
          type: 'error',
          sessionId: ttsSessionId,
          error: error instanceof Error ? error.message : String(error),
        };
        this.eventEmitter.emit(AI_TTS_STREAM_EVENT, errorEvent);
      }
      throw error;
    }
  }
}