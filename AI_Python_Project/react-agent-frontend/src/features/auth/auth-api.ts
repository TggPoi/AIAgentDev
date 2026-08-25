import type { HttpClient } from '@/api/http-client'
import type {
  ChangePasswordRequestDto,
  ChangePasswordResponseDto,
  CurrentUserDto,
  LoginRequestDto,
  LogoutResponseDto,
  TokenPairDto,
  UserCapabilitiesDto,
} from '@/features/auth/auth-contracts'
import {
  mapCapabilities,
  mapCurrentUser,
  type Capabilities,
  type CurrentUser,
} from '@/features/auth/auth-models'


export interface AuthApi {
  changePassword(request: ChangePasswordRequestDto): Promise<ChangePasswordResponseDto>
  getCapabilities(): Promise<Capabilities>
  getCurrentUser(): Promise<CurrentUser>
  login(request: LoginRequestDto): Promise<TokenPairDto>
  logout(refreshToken: string): Promise<LogoutResponseDto>
  refresh(refreshToken: string): Promise<TokenPairDto>
}

export function createAuthApi(httpClient: HttpClient): AuthApi {
  return {
    async changePassword(request) {
      const response = await httpClient.request<ChangePasswordResponseDto>(
        '/auth/change-password',
        { json: request, method: 'POST' },
      )
      return response.data
    },

    async getCapabilities() {
      const response = await httpClient.request<UserCapabilitiesDto>(
        '/auth/capabilities',
      )
      return mapCapabilities(response.data)
    },

    async getCurrentUser() {
      const response = await httpClient.request<CurrentUserDto>('/auth/me')
      return mapCurrentUser(response.data)
    },

    async login(request) {
      const response = await httpClient.request<TokenPairDto>('/auth/login', {
        authenticated: false,
        json: request,
        method: 'POST',
        retryOnUnauthorized: false,
      })
      return response.data
    },

    async logout(refreshToken) {
      const response = await httpClient.request<LogoutResponseDto>('/auth/logout', {
        json: { refresh_token: refreshToken },
        method: 'POST',
        retryOnUnauthorized: false,
      })
      return response.data
    },

    async refresh(refreshToken) {
      const response = await httpClient.request<TokenPairDto>('/auth/refresh', {
        authenticated: false,
        json: { refresh_token: refreshToken },
        method: 'POST',
        retryOnUnauthorized: false,
      })
      return response.data
    },
  }
}
