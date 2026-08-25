import { describe, expect, it } from 'vitest'

import { validateLoginReturnPath } from '@/features/auth/return-path'


describe('validateLoginReturnPath', () => {
  const origin = 'https://frontend.example'

  it('keeps only a parsed internal pathname, search, and hash', () => {
    expect(validateLoginReturnPath('/documents/doc-1?tab=text#section', origin)).toBe(
      '/documents/doc-1?tab=text#section',
    )
  })

  it.each([
    undefined,
    null,
    '',
    'chat',
    'https://evil.example/path',
    'javascript:alert(1)',
    '//evil.example/path',
    '///evil.example/path',
    '/\\evil.example/path',
    '/%5C%5Cevil.example/path',
    '/%E0%A4%A',
  ])('falls back for an unsafe return path: %s', (candidate) => {
    expect(validateLoginReturnPath(candidate, origin)).toBe('/chat')
  })
})
