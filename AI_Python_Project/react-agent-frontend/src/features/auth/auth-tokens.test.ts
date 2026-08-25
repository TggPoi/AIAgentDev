import { beforeEach, describe, expect, it } from 'vitest'

import { createAuthTokenStore } from '@/features/auth/auth-tokens'


describe('AuthTokenStore', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    window.localStorage.clear()
  })

  it('keeps access in memory and restores only the tab-scoped refresh token', () => {
    const accessValue = ['access', 'one'].join('-')
    const refreshValue = ['refresh', 'one'].join('-')
    const store = createAuthTokenStore(window.sessionStorage)

    store.setTokenPair({
      access_token: accessValue,
      refresh_token: refreshValue,
      token_type: 'bearer',
      expires_in: 300,
    })

    expect(store.getAccessToken()).toBe(accessValue)
    expect(store.getRefreshToken()).toBe(refreshValue)
    expect(window.sessionStorage.length).toBe(1)
    expect(window.sessionStorage.key(0)).not.toContain('access')
    expect(window.localStorage.length).toBe(0)

    const restored = createAuthTokenStore(window.sessionStorage)
    expect(restored.getAccessToken()).toBeNull()
    expect(restored.getRefreshToken()).toBe(refreshValue)
  })

  it('replaces rotated credentials and clears both memory and session storage', () => {
    const store = createAuthTokenStore(window.sessionStorage)
    store.setTokenPair({
      access_token: ['access', 'old'].join('-'),
      refresh_token: ['refresh', 'old'].join('-'),
      token_type: 'bearer',
      expires_in: 300,
    })
    store.setTokenPair({
      access_token: ['access', 'new'].join('-'),
      refresh_token: ['refresh', 'new'].join('-'),
      token_type: 'bearer',
      expires_in: 300,
    })

    expect(store.getAccessToken()).toBe(['access', 'new'].join('-'))
    expect(store.getRefreshToken()).toBe(['refresh', 'new'].join('-'))

    store.clear()
    expect(store.getAccessToken()).toBeNull()
    expect(store.getRefreshToken()).toBeNull()
    expect(window.sessionStorage.length).toBe(0)
  })
})
