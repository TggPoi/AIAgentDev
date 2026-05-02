import { BadRequestException, Body, Controller, Get, Post, Query, Res, Sse } from '@nestjs/common';
import type { Response } from 'express';
import { AiService } from './ai.service';
import { pipeUIMessageStreamToResponse, UIMessage } from 'ai';

@Controller('ai')
export class AiController {
  constructor(private readonly aiService: AiService) {}

  /**
    本地测试：
    curl -N -sS -X POST 'http://localhost:3000/ai/chat' \
      -H 'Content-Type: application/json' \
      -d '{"messages":[{"id":"1","role":"user","parts":[{"type":"text","text":"北京今天的天气"}]}]}'
   */
  @Post('chat')
  async postChat(
    @Body() body: { messages?: UIMessage[] },
    @Res({ passthrough: false }) res: Response,//passthrough：这个接口的响应由你手动控制，不再让 Nest 自动把返回值序列化成 JSON
  ): Promise<void> {

    if (!body?.messages || !Array.isArray(body.messages)) {

      throw new BadRequestException('Invalid JSON');
      
    }

    //ai sdk 转换好的就是 SSE 的流，我们不需要自己再做处理，直接把它传给 response 就可以了
    const stream = await this.aiService.stream(body.messages);

    //pipeUIMessageStreamToResponse 负责“把协议流写到 HTTP 响应里”，它会根据协议自动设置正确的 SSE 头、格式化数据等
    //类似return from(stream).pipe(map(...))的写法，只不过这里已经由AI SDK帮我们封装好了，我们直接调用就行了
    pipeUIMessageStreamToResponse({ response: res, stream });
  }
}