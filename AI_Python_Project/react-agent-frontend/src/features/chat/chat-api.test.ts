import { describe, expect, it, vi } from 'vitest'

import type { HttpClient } from '@/api/http-client'
import { createChatApi } from '@/features/chat/chat-api'
import type { RagChatRequestDto } from '@/features/chat/chat-contracts'


function streamFrom(text: string): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text))
      controller.close()
    },
  })
}

describe('Chat API', () => {
  it('uses only the structured Chat route and yields validated public events', async () => {
    const request: RagChatRequestDto = {
      allow_direct_web: false,
      allow_web_fallback: false,
      min_score: 0,
      mode: 'hybrid',
      query: '问题',
      session_id: 'session-1',
      top_k: 5,
    }
    const body = streamFrom(
      'event: answer_delta\n' +
        'data: {"contract_version":"1.0","request_id":"request-1","text":"回答"}\n\n' +
        'event: done\n' +
        'data: {"contract_version":"1.0","request_id":"request-1","status":"done"}\n\n',
    )
    const openEventStream = vi.fn().mockResolvedValue({
      body,
      headers: new Headers(),
      requestId: 'request-1',
      status: 200,
    })
    const httpClient: HttpClient = {
      openEventStream,
      request: vi.fn(),
    }
    const controller = new AbortController()

    const received = []
    for await (const event of createChatApi(httpClient).stream(
      request,
      'request-1',
      controller.signal,
    )) {
      received.push(event)
    }

    expect(openEventStream).toHaveBeenCalledOnce()
    expect(openEventStream).toHaveBeenCalledWith('/rag/chat/stream/events', {
      json: request,
      method: 'POST',
      requestId: 'request-1',
      signal: controller.signal,
    })
    expect(received).toMatchObject([
      { event: 'answer_delta', requestId: 'request-1', text: '回答' },
      { event: 'done', requestId: 'request-1', status: 'done' },
    ])
  })
})
