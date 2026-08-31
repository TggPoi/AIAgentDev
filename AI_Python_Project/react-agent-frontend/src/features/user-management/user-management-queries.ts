import {
  type InfiniteData,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query'

import type { UserManagementApi } from '@/features/user-management/user-management-api'
import type {
  AccessCatalog,
  ManagedUserDetail,
  ManagedUserPage,
  UserStatus,
} from '@/features/user-management/user-management-models'


export interface ManagedUserListFilters {
  departmentCode: string | null
  query: string | null
  status: UserStatus | null
}

export interface ManagedUserListKeyParams extends ManagedUserListFilters {
  limit: number
}

export const MANAGED_USER_LIST_LIMIT = 20

export const userManagementKeys = {
  catalog: (userBoundary: string) =>
    [userBoundary, 'user-access-catalog'] as const,
  detail: (userBoundary: string, userId: string) =>
    [userBoundary, 'managed-user-detail', userId] as const,
  detailRoot: (userBoundary: string) =>
    [userBoundary, 'managed-user-detail'] as const,
  list: (userBoundary: string, params: ManagedUserListKeyParams) =>
    [...userManagementKeys.listRoot(userBoundary), params] as const,
  listRoot: (userBoundary: string) =>
    [userBoundary, 'managed-users'] as const,
}

export function useAccessCatalog(
  api: UserManagementApi,
  userBoundary: string,
) {
  return useQuery<AccessCatalog, Error>({
    queryFn: ({ signal }) => api.getAccessCatalog(signal),
    queryKey: userManagementKeys.catalog(userBoundary),
  })
}

export function useManagedUserList(
  api: UserManagementApi,
  userBoundary: string,
  filters: ManagedUserListFilters,
) {
  const params = { ...filters, limit: MANAGED_USER_LIST_LIMIT }
  return useInfiniteQuery<
    ManagedUserPage,
    Error,
    InfiniteData<ManagedUserPage>,
    ReturnType<typeof userManagementKeys.list>,
    string | null
  >({
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api.listUsers({
        cursor: pageParam,
        ...filters,
        limit: MANAGED_USER_LIST_LIMIT,
        signal,
      }),
    queryKey: userManagementKeys.list(userBoundary, params),
  })
}

export function useManagedUserDetail(
  api: UserManagementApi,
  userBoundary: string,
  userId: string | null,
) {
  return useQuery<ManagedUserDetail, Error>({
    enabled: userId !== null,
    queryFn: ({ signal }) => api.getUser(userId ?? '', signal),
    queryKey: userManagementKeys.detail(
      userBoundary,
      userId ?? '__no-managed-user__',
    ),
  })
}
