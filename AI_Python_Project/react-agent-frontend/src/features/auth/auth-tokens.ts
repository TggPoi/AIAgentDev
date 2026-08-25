import type { TokenPairDto } from '@/features/auth/auth-contracts'


const REFRESH_TOKEN_STORAGE_KEY = 'react-agent.auth.refresh-token'

export interface AuthTokenStore {
  clear(): void
  getAccessToken(): string | null
  getRefreshToken(): string | null
  setTokenPair(tokenPair: TokenPairDto): void
}

function readRefreshToken(storage: Storage): string | null {
  try {
    const value = storage.getItem(REFRESH_TOKEN_STORAGE_KEY)
    return value !== null && value.length > 0 ? value : null
  } catch {
    return null
  }
}

export function createAuthTokenStore(storage: Storage): AuthTokenStore {
  let accessToken: string | null = null
  let refreshToken = readRefreshToken(storage)

  return {
    clear() {
      accessToken = null
      refreshToken = null
      try {
        storage.removeItem(REFRESH_TOKEN_STORAGE_KEY)
      } catch {
        // Memory state is still cleared when tab storage is unavailable.
      }
    },

    getAccessToken() {
      return accessToken
    },

    getRefreshToken() {
      return refreshToken
    },

    setTokenPair(tokenPair) {
      accessToken = tokenPair.access_token
      refreshToken = tokenPair.refresh_token
      try {
        storage.setItem(REFRESH_TOKEN_STORAGE_KEY, tokenPair.refresh_token)
      } catch {
        // Keep the current-tab in-memory refresh value without exposing it.
      }
    },
  }
}
