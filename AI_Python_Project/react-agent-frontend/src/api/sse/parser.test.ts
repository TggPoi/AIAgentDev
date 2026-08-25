import { describe, expect, it } from 'vitest'

import { parseSseStream, SseIncompleteFrameError } from '@/api/sse/parser'

function streamBytes(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk)
      }
      controller.close()
    },
  })
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const frames = []
  for await (const frame of parseSseStream(stream, () => 42)) {
    frames.push(frame)
  }
  return frames
}

describe('parseSseStream', () => {
  it('handles arbitrary UTF-8 byte boundaries, comments and multiline data', async () => {
    const bytes = new TextEncoder().encode(
      ': keepalive\r\nevent: answer_delta\r\ndata: {"text":"你\r\ndata: 好"}\r\n\r\n',
    )
    const chunks = Array.from(bytes, (byte) => new Uint8Array([byte]))

    await expect(collect(streamBytes(chunks))).resolves.toEqual([
      {
        data: '{"text":"你\n好"}',
        event: 'answer_delta',
        receivedAt: 42,
      },
    ])
  })

  it('parses multiple LF frames and defaults missing event to message', async () => {
    const content = 'data: first\n\nevent: done\ndata: {"status":"done"}\n\n'

    await expect(
      collect(streamBytes([new TextEncoder().encode(content)])),
    ).resolves.toEqual([
      { data: 'first', event: 'message', receivedAt: 42 },
      { data: '{"status":"done"}', event: 'done', receivedAt: 42 },
    ])
  })

  it('rejects an incomplete final frame instead of dispatching partial data', async () => {
    const stream = streamBytes([
      new TextEncoder().encode('event: answer_delta\ndata: {"text":"partial"}'),
    ])

    await expect(collect(stream)).rejects.toBeInstanceOf(SseIncompleteFrameError)
  })
})
