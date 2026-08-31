import type { HttpClient } from '@/api/http-client'
import type {
  AccessCatalogResponseDto,
  ManagedUserDetailDto,
  ManagedUserListResponseDto,
} from '@/features/user-management/user-management-contracts'
import {
  mapAccessCatalog,
  mapManagedUserDetail,
  mapManagedUserPage,
  type AccessCatalog,
  type ManagedUserDetail,
  type ManagedUserPage,
  type UserStatus,
} from '@/features/user-management/user-management-models'


export interface ManagedUserListRequest {
  cursor: string | null
  departmentCode: string | null
  limit: number
  query: string | null
  signal?: AbortSignal
  status: UserStatus | null
}

export interface UserManagementApi {
  getAccessCatalog(signal?: AbortSignal): Promise<AccessCatalog>
  getUser(userId: string, signal?: AbortSignal): Promise<ManagedUserDetail>
  listUsers(request: ManagedUserListRequest): Promise<ManagedUserPage>
}

function userPath(userId: string): string {
  return `/admin/users/${encodeURIComponent(userId)}`
}

function listPath(request: ManagedUserListRequest): string {
  const search = new URLSearchParams()
  if (request.cursor !== null) search.set('cursor', request.cursor)
  search.set('limit', String(request.limit))
  if (request.query !== null) search.set('query', request.query)
  if (request.status !== null) search.set('status', request.status)
  if (request.departmentCode !== null) {
    search.set('department_code', request.departmentCode)
  }
  return `/admin/users?${search.toString()}`
}

export function createUserManagementApi(
  httpClient: HttpClient,
): UserManagementApi {
  return {
    async getAccessCatalog(signal) {
      const response = await httpClient.request<AccessCatalogResponseDto>(
        '/admin/access/catalog',
        { signal },
      )
      return mapAccessCatalog(response.data)
    },

    async getUser(userId, signal) {
      const response = await httpClient.request<ManagedUserDetailDto>(
        userPath(userId),
        { signal },
      )
      return mapManagedUserDetail(response.data)
    },

    async listUsers(request) {
      const response = await httpClient.request<ManagedUserListResponseDto>(
        listPath(request),
        { signal: request.signal },
      )
      return mapManagedUserPage(response.data)
    },
  }
}
