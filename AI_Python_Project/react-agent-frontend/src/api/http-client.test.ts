import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/api-error'
import { createHttpClient } from '@/api/http-client'
import { isEventStreamMediaType, parseMediaType } from '@/api/media-type'

describe('media type parsing', () => {
  it('normalizes the media type and accepts legal event-stream parameters', () => {
    expect(parseMediaType(' Text/Event-Stream ; charset=utf-8 ')).toBe(
      'text/event-stream',
    )
    expect(isEventStreamMediaType('text/event-stream')).toBe(true)
    expect(
      isEventStreamMediaType('text/event-stream; charset=utf-8'),
    ).toBe(true)
    expect(isEventStreamMediaType('application/json')).toBe(false)
  })
})

describe('HttpClient', () => {
  it('adds the bearer token and stable request ID and parses JSON', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: {
          'Content-Type': 'application/json; charset=utf-8',
          'X-Request-ID': 'request-json',
        },
      }),
    )
    const client = createHttpClient({
      baseUrl: 'http://127.0.0.1:8000/',
      fetchImpl,
      getAccessToken: () => 'access-token',
    })

    const result = await client.request<{ ok: boolean }>('/auth/me', {
      requestId: 'request-json',
    })

    expect(result.data).toEqual({ ok: true })
    expect(result.requestId).toBe('request-json')
    const [url, init] = fetchImpl.mock.calls[0] ?? []
    expect(url).toBe('http://127.0.0.1:8000/auth/me')
    expect(new Headers(init?.headers).get('Authorization')).toBe(
      'Bearer access-token',
    )
    expect(new Headers(init?.headers).get('X-Request-ID')).toBe('request-json')
  })

  it('passes AbortSignal and supports JSON request bodies', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(null, {
        status: 204,
        headers: { 'X-Request-ID': 'request-empty' },
      }),
    )
    const controller = new AbortController()
    const client = createHttpClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetchImpl,
      getAccessToken: () => null,
    })

    const result = await client.request('/auth/logout', {
      authenticated: false,
      json: { all_sessions: false },
      method: 'POST',
      requestId: 'request-empty',
      responseType: 'empty',
      signal: controller.signal,
    })

    expect(result.data).toBeUndefined()
    const [, init] = fetchImpl.mock.calls[0] ?? []
    expect(init?.body).toBe('{"all_sessions":false}')
    expect(init?.signal).toBe(controller.signal)
    expect(new Headers(init?.headers).get('Content-Type')).toBe(
      'application/json',
    )
  })

  it('parses text/Markdown and Blob responses through explicit response types', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response('# Plan', {
          headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(new Uint8Array([1, 2, 3]), {
          headers: { 'Content-Type': 'application/octet-stream' },
        }),
      )
    const client = createHttpClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetchImpl,
      getAccessToken: () => null,
    })

    const markdown = await client.request<string>('/task/markdown', {
      responseType: 'text',
    })
    const file = await client.request<Blob>('/document/download', {
      responseType: 'blob',
    })

    expect(markdown.data).toBe('# Plan')
    expect(file.data).toBeInstanceOf(Blob)
    expect(file.data.size).toBe(3)
  })

  it('maps backend errors without retaining undeclared response fields', async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          code: 'CONVERSATION_CONFLICT',
          message: '会话状态冲突',
          error_category: 'user_error',
          request_id: 'request-conflict',
          trace_id: 'trace-conflict',
          secret: 'must-not-be-retained',
        }),
        {
          status: 409,
          headers: {
            'Content-Type': 'application/json',
            'X-Request-ID': 'request-conflict',
          },
        },
      ),
    )
    const client = createHttpClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetchImpl,
      getAccessToken: () => null,
    })

    const error = await client.request('/conversations').catch((reason) => reason)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      code: 'CONVERSATION_CONFLICT',
      requestId: 'request-conflict',
      status: 409,
      statusKind: 'conflict',
      traceId: 'trace-conflict',
    })
    expect(JSON.stringify(error)).not.toContain('must-not-be-retained')
  })

  it('maps network failures but preserves AbortError for cancellation', async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError('private network detail'))
      .mockRejectedValueOnce(new DOMException('aborted', 'AbortError'))
    const client = createHttpClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetchImpl,
      getAccessToken: () => null,
    })

    await expect(
      client.request('/auth/me', { requestId: 'request-network' }),
    ).rejects.toMatchObject({
      code: 'NETWORK_ERROR',
      requestId: 'request-network',
      statusKind: 'network',
    })
    await expect(client.request('/auth/me')).rejects.toMatchObject({
      name: 'AbortError',
    })
  })

  it('accepts parameterized event streams and rejects other successful media types', async () => {
    const requestId = 'request-stream'
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: done\ndata: {}\n\n'))
        controller.close()
      },
    })
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(stream, {
          headers: {
            'Content-Type': 'text/event-stream; charset=utf-8',
            'X-Request-ID': requestId,
          },
        }),
      )
      .mockResolvedValueOnce(
        new Response('{}', {
          headers: {
            'Content-Type': 'application/json',
            'X-Request-ID': requestId,
          },
        }),
      )
    const client = createHttpClient({
      baseUrl: 'http://127.0.0.1:8000',
      fetchImpl,
      getAccessToken: () => null,
    })

    const accepted = await client.openEventStream('/rag/chat/stream/events', {
      requestId,
    })
    expect(accepted.body).toBe(stream)

    await expect(
      client.openEventStream('/rag/chat/stream/events', { requestId }),
    ).rejects.toMatchObject({ code: 'UNEXPECTED_CONTENT_TYPE' })
  })
})
