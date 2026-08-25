const MEDIA_TYPE_PATTERN = /^[!#$%&'*+.^_`|~0-9a-z-]+\/[!#$%&'*+.^_`|~0-9a-z-]+$/i

export function parseMediaType(contentType: string | null): string | null {
  if (contentType === null) {
    return null
  }

  const [rawMediaType] = contentType.split(';', 1)
  const mediaType = rawMediaType?.trim().toLowerCase() ?? ''

  return MEDIA_TYPE_PATTERN.test(mediaType) ? mediaType : null
}

export function isJsonMediaType(contentType: string | null): boolean {
  const mediaType = parseMediaType(contentType)
  return mediaType === 'application/json' || mediaType?.endsWith('+json') === true
}

export function isTextMediaType(contentType: string | null): boolean {
  return parseMediaType(contentType)?.startsWith('text/') === true
}

export function isEventStreamMediaType(contentType: string | null): boolean {
  return parseMediaType(contentType) === 'text/event-stream'
}
