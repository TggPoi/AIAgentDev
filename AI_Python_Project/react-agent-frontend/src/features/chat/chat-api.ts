import type { HttpClient } from '@/api/http-client'
import { parsePublicEvent, type PublicEvent } from '@/api/sse/public-events'
import { parseSseStream } from '@/api/sse/parser'
import type { RagChatRequestDto } from '@/features/chat/chat-contracts'


export interface ChatApi {
  stream(
    request: RagChatRequestDto,
    requestId: string,
    signal: AbortSignal,
  ): AsyncGenerator<PublicEvent>
}

export function createChatApi(httpClient: HttpClient): ChatApi {
  return {
    async *stream(request, requestId, signal) {
      const response = await httpClient.openEventStream(
        '/rag/chat/stream/events',
        {
          json: request,
          method: 'POST',
          requestId,
          signal,
        },
      )
      for await (const frame of parseSseStream(response.body)) {
        yield parsePublicEvent(frame, requestId)
      }
    },
  }
}
