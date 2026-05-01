import { Controller, Get, Query, Sse } from '@nestjs/common';
import { from, map, Observable } from 'rxjs';
import { AiService } from './ai.service';
import { EventEmitter2 } from '@nestjs/event-emitter';
import { AI_TTS_STREAM_EVENT, type AiTtsStreamEvent } from '../common/stream-events';

@Controller('ai')
export class AiController {
  constructor(
    private readonly aiService: AiService,
    private readonly eventEmitter: EventEmitter2,
  ) {}

  @Sse('chat/stream')
  chatStream(
    @Query('query') query: string,
    @Query('ttsSessionId') ttsSessionId?: string,
  ): Observable<{ data: string }> {
    const sessionId = ttsSessionId?.trim();

    if (sessionId) {
      // 在开始 AI 流式处理之前，先发送一个 'start' 事件到 TTS 转发服务，通知它即将开始一个新的 TTS 流式会话，并提供会话 ID 和查询内容，以便转发服务做好准备接收后续的文本块并转发给腾讯云 TTS 服务
      const startEvent: AiTtsStreamEvent = { type: 'start', sessionId, query };
      this.eventEmitter.emit(AI_TTS_STREAM_EVENT, startEvent);
    }

    return from(this.aiService.streamChain(query, sessionId)).pipe(
      map((chunk) => ({ data: chunk })),
    );
  }
}