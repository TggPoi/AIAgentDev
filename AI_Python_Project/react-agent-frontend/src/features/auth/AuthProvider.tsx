import { useQueryClient } from '@tanstack/react-query'
import {
  createContext,
  type PropsWithChildren,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from 'react'

import type { HttpClient } from '@/api/http-client'
import {
  createAuthController,
  type AuthController,
  type AuthState,
} from '@/features/auth/auth-controller'
import type {
  ChangePasswordRequestDto,
  LoginRequestDto,
} from '@/features/auth/auth-contracts'
import type { ChangePasswordResult } from '@/features/auth/auth-models'


interface AuthProviderProps extends PropsWithChildren {
  baseUrl?: string
  fetchImpl?: typeof fetch
  storage?: Storage
}

export interface AuthContextValue extends AuthState {
  changePassword(request: ChangePasswordRequestDto): Promise<ChangePasswordResult>
  readonly httpClient: HttpClient
  login(request: LoginRequestDto): Promise<void>
  logout(): Promise<void>
  registerPrivateActivity(controller: AbortController): () => void
  reloadIdentitySnapshot(): Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({
  baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000',
  children,
  fetchImpl,
  storage = window.sessionStorage,
}: AuthProviderProps) {
  const queryClient = useQueryClient()
  const [controller] = useState<AuthController>(() =>
    createAuthController({
      baseUrl,
      fetchImpl,
      queryClient,
      storage,
    }),
  )
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getState,
    controller.getState,
  )

  useEffect(() => {
    void controller.initialize()
  }, [controller])

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      changePassword: controller.changePassword,
      httpClient: controller.httpClient,
      login: controller.login,
      logout: controller.logout,
      registerPrivateActivity: controller.registerPrivateActivity,
      reloadIdentitySnapshot: controller.reloadIdentitySnapshot,
    }),
    [controller, state],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (context === null) {
    throw new Error('useAuth must be used inside AuthProvider')
  }
  return context
}
