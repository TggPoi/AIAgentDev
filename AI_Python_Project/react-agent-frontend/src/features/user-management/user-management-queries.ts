import {
  type InfiniteData,
  type QueryClient,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { ApiError } from '@/api/api-error'
import type { UserManagementApi } from '@/features/user-management/user-management-api'
import type {
  CreateManagedUserRequestDto,
  ReplaceManagedUserAccessRequestDto,
  ResetManagedUserPasswordRequestDto,
  UpdateManagedUserStatusRequestDto,
} from '@/features/user-management/user-management-contracts'
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

function invalidateManagedUserList(
  queryClient: QueryClient,
  userBoundary: string,
) {
  return queryClient.invalidateQueries({
    queryKey: userManagementKeys.listRoot(userBoundary),
  })
}

function refreshManagedUserFacts(
  queryClient: QueryClient,
  userBoundary: string,
  userId: string,
) {
  return Promise.all([
    queryClient.invalidateQueries({
      queryKey: userManagementKeys.detail(userBoundary, userId),
    }),
    invalidateManagedUserList(queryClient, userBoundary),
  ])
}

function refreshOnConflict(refreshFacts: () => Promise<unknown[]>) {
  return (error: Error) =>
    error instanceof ApiError && error.status === 409
      ? refreshFacts()
      : undefined
}

export function useCreateManagedUser(
  api: UserManagementApi,
  userBoundary: string,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (request: CreateManagedUserRequestDto) =>
      api.createUser(request),
    onError: (error) =>
      error instanceof ApiError && error.status === 409
        ? invalidateManagedUserList(queryClient, userBoundary)
        : undefined,
    onSuccess: async (user) => {
      queryClient.setQueryData(
        userManagementKeys.detail(userBoundary, user.userId),
        user,
      )
      await invalidateManagedUserList(queryClient, userBoundary)
    },
  })
}

export function useReplaceManagedUserAccess(
  api: UserManagementApi,
  userBoundary: string,
  userId: string,
) {
  const queryClient = useQueryClient()
  const refreshFacts = () =>
    refreshManagedUserFacts(queryClient, userBoundary, userId)
  return useMutation({
    mutationFn: (request: ReplaceManagedUserAccessRequestDto) =>
      api.replaceUserAccess(userId, request),
    onError: refreshOnConflict(refreshFacts),
    onSuccess: async (user) => {
      queryClient.setQueryData(
        userManagementKeys.detail(userBoundary, userId),
        user,
      )
      await invalidateManagedUserList(queryClient, userBoundary)
    },
  })
}

export function useUpdateManagedUserStatus(
  api: UserManagementApi,
  userBoundary: string,
  userId: string,
) {
  const queryClient = useQueryClient()
  const refreshFacts = () =>
    refreshManagedUserFacts(queryClient, userBoundary, userId)
  return useMutation({
    mutationFn: (request: UpdateManagedUserStatusRequestDto) =>
      api.updateUserStatus(userId, request),
    onError: refreshOnConflict(refreshFacts),
    onSuccess: async (result) => {
      queryClient.setQueryData(
        userManagementKeys.detail(userBoundary, userId),
        result.user,
      )
      await invalidateManagedUserList(queryClient, userBoundary)
    },
  })
}

export function useResetManagedUserPassword(
  api: UserManagementApi,
  userBoundary: string,
  userId: string,
) {
  const queryClient = useQueryClient()
  const refreshFacts = () =>
    refreshManagedUserFacts(queryClient, userBoundary, userId)
  return useMutation({
    mutationFn: (request: ResetManagedUserPasswordRequestDto) =>
      api.resetUserPassword(userId, request),
    onError: refreshOnConflict(refreshFacts),
    onSuccess: refreshFacts,
  })
}
