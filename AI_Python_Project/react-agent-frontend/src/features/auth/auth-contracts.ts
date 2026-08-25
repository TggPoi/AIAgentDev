import type { components } from '@/api/generated/backend-schema'


export type ChangePasswordRequestDto =
  components['schemas']['ChangePasswordRequest']
export type ChangePasswordResponseDto =
  components['schemas']['ChangePasswordResponse']
export type CurrentUserDto = components['schemas']['CurrentUserResponse']
export type LoginRequestDto = components['schemas']['LoginRequest']
export type LogoutRequestDto = components['schemas']['LogoutRequest']
export type LogoutResponseDto = components['schemas']['LogoutResponse']
export type RefreshTokenRequestDto =
  components['schemas']['RefreshTokenRequest']
export type RequestValidationErrorResponseDto =
  components['schemas']['RequestValidationErrorResponse']
export type TokenPairDto = components['schemas']['TokenPairResponse']
export type UserCapabilitiesDto =
  components['schemas']['UserCapabilitiesResponse']
