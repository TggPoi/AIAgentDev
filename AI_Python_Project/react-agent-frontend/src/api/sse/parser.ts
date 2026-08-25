export interface SseFrame {
  data: string
  event: string
  receivedAt: number
}

export class SseIncompleteFrameError extends Error {
  constructor() {
    super('SSE stream ended with an incomplete frame')
    this.name = 'SseIncompleteFrameError'
  }
}

export async function* parseSseStream(
  stream: ReadableStream<Uint8Array>,
  now: () => number = Date.now,
): AsyncGenerator<SseFrame> {
  const reader = stream.getReader()
  const decoder = new TextDecoder()
  const readyFrames: SseFrame[] = []
  let textBuffer = ''
  let eventName = ''
  let dataLines: string[] = []
  let frameTouched = false

  function resetFrame() {
    eventName = ''
    dataLines = []
    frameTouched = false
  }

  function processLine(line: string) {
    if (line.length === 0) {
      if (dataLines.length > 0) {
        readyFrames.push({
          data: dataLines.join('\n'),
          event: eventName || 'message',
          receivedAt: now(),
        })
      }
      resetFrame()
      return
    }

    if (line.startsWith(':')) {
      return
    }

    frameTouched = true
    const colonIndex = line.indexOf(':')
    const field = colonIndex === -1 ? line : line.slice(0, colonIndex)
    let value = colonIndex === -1 ? '' : line.slice(colonIndex + 1)
    if (value.startsWith(' ')) {
      value = value.slice(1)
    }

    if (field === 'event') {
      eventName = value
    } else if (field === 'data') {
      dataLines.push(value)
    }
  }

  function processAvailableLines(final: boolean) {
    let cursor = 0
    while (cursor < textBuffer.length) {
      let lineEnd = cursor
      while (
        lineEnd < textBuffer.length &&
        textBuffer[lineEnd] !== '\r' &&
        textBuffer[lineEnd] !== '\n'
      ) {
        lineEnd += 1
      }

      if (lineEnd === textBuffer.length) {
        break
      }
      if (
        textBuffer[lineEnd] === '\r' &&
        lineEnd + 1 === textBuffer.length &&
        !final
      ) {
        break
      }

      processLine(textBuffer.slice(cursor, lineEnd))
      cursor =
        textBuffer[lineEnd] === '\r' && textBuffer[lineEnd + 1] === '\n'
          ? lineEnd + 2
          : lineEnd + 1
    }
    textBuffer = textBuffer.slice(cursor)
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        break
      }
      textBuffer += decoder.decode(value, { stream: true })
      processAvailableLines(false)
      while (readyFrames.length > 0) {
        const frame = readyFrames.shift()
        if (frame !== undefined) {
          yield frame
        }
      }
    }

    textBuffer += decoder.decode()
    processAvailableLines(true)
    while (readyFrames.length > 0) {
      const frame = readyFrames.shift()
      if (frame !== undefined) {
        yield frame
      }
    }

    if (textBuffer.length > 0 || frameTouched || dataLines.length > 0) {
      throw new SseIncompleteFrameError()
    }
  } finally {
    reader.releaseLock()
  }
}
