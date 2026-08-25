import type { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/api-error'
import { createHttpClient, type HttpClient } from '@/api/http-client'
import { createAuthApi, type AuthApi } from '@/features/auth/auth-api'
import type {
  ChangePasswordRequestDto,
  LoginRequestDto,
} from '@/features/auth/auth-contracts'
import type {
  ChangePasswordResult,
  IdentitySnapshot,
} from '@/features/auth/auth-models'
import { createAuthTokenStore } from '@/features/auth/auth-tokens'


export type AuthStatus =
  | 'anonymous'
  | 'authenticated'
  | 'bootstrapping'
  | 'changingPassword'
  | 'loggingOut'
  | 'refreshing'
  | 'stale'

export interface AuthState {
  error: ApiError | null
  snapshot: IdentitySnapshot | null
  status: AuthStatus
}

export interface AuthController {
  changePassword(request: ChangePasswordRequestDto): Promise<ChangePasswordResult>
  getState(): AuthState
  readonly httpClient: HttpClient
  initialize(): Promise<void>
  login(request: LoginRequestDto): Promise<void>
  logout(): Promise<void>
  registerPrivateActivity(controller: AbortController): () => void
  reloadIdentitySnapshot(): Promise<void>
  subscribe(listener: () => void): () => void
}

interface AuthControllerOptions {
  baseUrl: string
  fetchImpl?: typeof fetch
  queryClient: QueryClient
  storage: Storage
}

export function createAuthController(
  options: AuthControllerOptions,
): AuthController {
  const tokenStore = createAuthTokenStore(options.storage)
  let state: AuthState = {
    error: null,
    snapshot: null,
    status: 'bootstrapping',
  }
  let generation = 0
  let initializationPromise: Promise<void> | null = null
  let authApi: AuthApi
  const listeners = new Set<() => void>()
  const privateActivities = new Set<AbortController>()

  const setState = (nextState: AuthState) => {
    state = nextState
    for (const listener of listeners) {
      listener()
    }
  }

  const clearPrivateState = () => {
    for (const controller of privateActivities) {
      controller.abort()
    }
    privateActivities.clear()
    options.queryClient.clear()
  }

  const clearAuthentication = () => {
    generation += 1
    tokenStore.clear()
    clearPrivateState()
    setState({ error: null, snapshot: null, status: 'anonymous' })
  }

  const refreshAccessToken = async () => {
    const refreshGeneration = generation
    const refreshToken = tokenStore.getRefreshToken()
    if (refreshToken === null) {
      clearAuthentication()
      throw new Error('No refresh token available')
    }
    if (state.snapshot !== null) {
      setState({ ...state, status: 'refreshing' })
    }
    try {
      const tokenPair = await authApi.refresh(refreshToken)
      if (refreshGeneration !== generation) {
        throw new Error('Authentication lifecycle changed during refresh')
      }
      tokenStore.setTokenPair(tokenPair)
      if (state.snapshot !== null) {
        setState({ ...state, status: 'authenticated' })
      }
    } catch (error) {
      if (refreshGeneration === generation) {
        clearAuthentication()
      }
      throw error
    }
  }

  const httpClient = createHttpClient({
    baseUrl: options.baseUrl,
    fetchImpl: options.fetchImpl,
    getAccessToken: tokenStore.getAccessToken,
    refreshAccessToken,
  })
  authApi = createAuthApi(httpClient)

  const reloadIdentitySnapshot = async () => {
    const capturedGeneration = ++generation
    const previousSnapshot = state.snapshot
    const expectedUserId = state.snapshot?.currentUser.userId ?? null
    try {
      const [currentUser, capabilities] = await Promise.all([
        authApi.getCurrentUser(),
        authApi.getCapabilities(),
      ])
      if (capturedGeneration !== generation) {
        return
      }
      if (expectedUserId !== null && currentUser.userId !== expectedUserId) {
        clearAuthentication()
        return
      }
      setState({
        error: null,
        snapshot: { capabilities, currentUser },
        status: 'authenticated',
      })
    } catch (error) {
      if (capturedGeneration === generation) {
        if (error instanceof ApiError && error.statusKind === 'authentication') {
          clearAuthentication()
        } else if (previousSnapshot !== null) {
          setState({
            error: error instanceof ApiError ? error : null,
            snapshot: previousSnapshot,
            status: 'stale',
          })
        } else {
          clearAuthentication()
        }
      }
      throw error
    }
  }

  const initialize = () => {
    if (initializationPromise !== null) {
      return initializationPromise
    }
    initializationPromise = (async () => {
      if (tokenStore.getRefreshToken() === null) {
        clearAuthentication()
        return
      }
      try {
        await refreshAccessToken()
        await reloadIdentitySnapshot()
      } catch {
        clearAuthentication()
      }
    })()
    return initializationPromise
  }

  const logout = async () => {
    const refreshToken = tokenStore.getRefreshToken()
    const logoutGeneration = ++generation
    setState({ ...state, status: 'loggingOut' })
    clearPrivateState()
    try {
      if (refreshToken !== null) {
        await authApi.logout(refreshToken)
      }
    } finally {
      if (logoutGeneration === generation) {
        tokenStore.clear()
        setState({ error: null, snapshot: null, status: 'anonymous' })
      }
    }
  }

  const changePassword = async (
    request: ChangePasswordRequestDto,
  ): Promise<ChangePasswordResult> => {
    const changeGeneration = ++generation
    const previousSnapshot = state.snapshot
    setState({ ...state, status: 'changingPassword' })
    try {
      const response = await authApi.changePassword(request)
      if (changeGeneration !== generation) {
        throw new Error('Authentication lifecycle changed during password update')
      }
      const result = {
        passwordChanged: response.password_changed,
        revokedRefreshTokenCount: response.revoked_refresh_token_count,
      }
      clearAuthentication()
      return result
    } catch (error) {
      if (changeGeneration === generation && previousSnapshot !== null) {
        setState({
          error: error instanceof ApiError ? error : null,
          snapshot: previousSnapshot,
          status: 'authenticated',
        })
      }
      throw error
    }
  }

  const login = async (request: LoginRequestDto) => {
    const loginGeneration = ++generation
    tokenStore.clear()
    clearPrivateState()
    setState({ error: null, snapshot: null, status: 'bootstrapping' })
    try {
      const tokenPair = await authApi.login(request)
      if (loginGeneration !== generation) {
        throw new Error('Authentication lifecycle changed during login')
      }
      tokenStore.setTokenPair(tokenPair)
      await reloadIdentitySnapshot()
    } catch (error) {
      if (loginGeneration === generation) {
        clearAuthentication()
      }
      throw error
    }
  }

  const registerPrivateActivity = (controller: AbortController) => {
    if (!controller.signal.aborted) {
      privateActivities.add(controller)
    }
    return () => {
      privateActivities.delete(controller)
    }
  }

  const subscribe = (listener: () => void) => {
    listeners.add(listener)
    return () => {
      listeners.delete(listener)
    }
  }

  return {
    changePassword,
    getState: () => state,
    httpClient,
    initialize,
    login,
    logout,
    registerPrivateActivity,
    reloadIdentitySnapshot,
    subscribe,
  }
}
