import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { PropsWithChildren } from 'react'
import { describe, expect, it } from 'vitest'

import { createHttpClient } from '@/api/http-client'
import { createUserManagementApi } from '@/features/user-management/user-management-api'
import type {
  CreateManagedUserRequestDto,
  ReplaceManagedUserAccessRequestDto,
} from '@/features/user-management/user-management-contracts'
import {
  userManagementKeys,
  useCreateManagedUser,
  useReplaceManagedUserAccess,
  useResetManagedUserPassword,
  useUpdateManagedUserStatus,
} from '@/features/user-management/user-management-queries'
import { mapManagedUserDetail } from '@/features/user-management/user-management-models'
import { server } from '@/test/server'


const apiBaseUrl = 'http://user-management-mutations.test'

function managedUserDetailDto(
  userId: string,
  status: 'active' | 'disabled' = 'active',
) {
  return {
    account_type: 'employee' as const,
    created_at: '2026-08-31T01:00:00Z',
    department_access: [
      {
        department_code: 'development',
        is_primary: true,
        permission_codes: ['knowledge:read'],
        role_codes: ['department_reader'],
      },
    ],
    direct_permission_codes: ['agent:tool:web_search'],
    display_name: 'Reader',
    effective_global_permission_codes: ['agent:tool:web_search'],
    email: 'reader@example.com',
    global_role_codes: [],
    last_login_at: null,
    status,
    updated_at: '2026-08-31T02:00:00Z',
    user_id: userId,
    username: 'reader',
  }
}

function createHarness() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  })
  const api = createUserManagementApi(
    createHttpClient({
      baseUrl: apiBaseUrl,
      getAccessToken: () => null,
      requestIdFactory: () => 'user-management-mutation-request',
    }),
  )
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return { api, queryClient, wrapper }
}

function seedFacts(
  queryClient: QueryClient,
  userId: string,
  status: 'active' | 'disabled' = 'active',
) {
  const detailKey = userManagementKeys.detail('admin-actor', userId)
  const listKey = userManagementKeys.list('admin-actor', {
    departmentCode: null,
    limit: 20,
    query: null,
    status: null,
  })
  queryClient.setQueryData(
    detailKey,
    mapManagedUserDetail(managedUserDetailDto(userId, status)),
  )
  queryClient.setQueryData(listKey, { pages: [], pageParams: [] })
  return { detailKey, listKey }
}

describe('User Management mutation transport and convergence', () => {
  it('creates with the complete generated request and seeds detail before invalidating lists', async () => {
    const request: CreateManagedUserRequestDto = {
      account_type: 'employee',
      department_access: [
        {
          department_code: 'development',
          is_primary: true,
          role_codes: ['department_reader'],
        },
      ],
      direct_permission_codes: ['agent:tool:web_search'],
      display_name: 'Reader',
      email: 'reader@example.com',
      password: 'one-time-password',
      username: 'reader',
    }
    let receivedBody: unknown
    server.use(
      http.post(`${apiBaseUrl}/admin/users`, async ({ request: httpRequest }) => {
        receivedBody = await httpRequest.json()
        return HttpResponse.json(managedUserDetailDto('user-reader'), {
          status: 201,
        })
      }),
    )
    const { api, queryClient, wrapper } = createHarness()
    const listKey = userManagementKeys.list('admin-actor', {
      departmentCode: null,
      limit: 20,
      query: null,
      status: null,
    })
    queryClient.setQueryData(listKey, { pages: [], pageParams: [] })
    const { result } = renderHook(
      () => useCreateManagedUser(api, 'admin-actor'),
      { wrapper },
    )

    const created = await result.current.mutateAsync(request)

    expect(receivedBody).toEqual(request)
    expect(created.userId).toBe('user-reader')
    expect(
      queryClient.getQueryData(
        userManagementKeys.detail('admin-actor', 'user-reader'),
      ),
    ).toMatchObject({ userId: 'user-reader', username: 'reader' })
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true)
  })

  it('puts an encoded target access snapshot and replaces the cached detail', async () => {
    const request: ReplaceManagedUserAccessRequestDto = {
      account_type: 'employee',
      department_access: [
        {
          department_code: 'development',
          is_primary: true,
          role_codes: ['department_reader'],
        },
      ],
      direct_permission_codes: [],
    }
    let receivedBody: unknown
    server.use(
      http.put(
        `${apiBaseUrl}/admin/users/user%2Freader/access`,
        async ({ request: httpRequest }) => {
          receivedBody = await httpRequest.json()
          return HttpResponse.json(managedUserDetailDto('user/reader'))
        },
      ),
    )
    const { api, queryClient, wrapper } = createHarness()
    const { detailKey, listKey } = seedFacts(queryClient, 'user/reader')
    const { result } = renderHook(
      () =>
        useReplaceManagedUserAccess(api, 'admin-actor', 'user/reader'),
      { wrapper },
    )

    await result.current.mutateAsync(request)

    expect(receivedBody).toEqual(request)
    expect(queryClient.getQueryData(detailKey)).toMatchObject({
      directPermissionCodes: ['agent:tool:web_search'],
      userId: 'user/reader',
    })
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true)
  })

  it('does not optimistically change status and converges from the PATCH response', async () => {
    let releaseResponse: (() => void) | undefined
    const responseGate = new Promise<void>((resolve) => {
      releaseResponse = resolve
    })
    let receivedBody: unknown
    server.use(
      http.patch(
        `${apiBaseUrl}/admin/users/user-reader/status`,
        async ({ request: httpRequest }) => {
          receivedBody = await httpRequest.json()
          await responseGate
          return HttpResponse.json({
            revoked_api_key_count: 2,
            revoked_refresh_token_count: 3,
            user: managedUserDetailDto('user-reader', 'disabled'),
          })
        },
      ),
    )
    const { api, queryClient, wrapper } = createHarness()
    const { detailKey, listKey } = seedFacts(queryClient, 'user-reader')
    const { result } = renderHook(
      () => useUpdateManagedUserStatus(api, 'admin-actor', 'user-reader'),
      { wrapper },
    )

    const mutation = result.current.mutateAsync({ status: 'disabled' })
    await waitFor(() => expect(result.current.isPending).toBe(true))
    expect(queryClient.getQueryData(detailKey)).toMatchObject({
      status: 'active',
    })

    releaseResponse?.()
    const response = await mutation

    expect(receivedBody).toEqual({ status: 'disabled' })
    expect(response).toMatchObject({
      revokedApiKeyCount: 2,
      revokedRefreshTokenCount: 3,
      user: { status: 'disabled' },
    })
    expect(queryClient.getQueryData(detailKey)).toMatchObject({
      status: 'disabled',
    })
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true)
  })

  it('posts a reset password request and invalidates server facts without caching the password', async () => {
    let receivedBody: unknown
    server.use(
      http.post(
        `${apiBaseUrl}/admin/users/user-reader/reset-password`,
        async ({ request: httpRequest }) => {
          receivedBody = await httpRequest.json()
          return HttpResponse.json({
            password_reset: true,
            revoked_api_key_count: 4,
            revoked_refresh_token_count: 5,
          })
        },
      ),
    )
    const { api, queryClient, wrapper } = createHarness()
    const { detailKey, listKey } = seedFacts(queryClient, 'user-reader')
    const { result } = renderHook(
      () => useResetManagedUserPassword(api, 'admin-actor', 'user-reader'),
      { wrapper },
    )

    const response = await result.current.mutateAsync({
      new_password: 'replacement-password',
    })

    expect(receivedBody).toEqual({ new_password: 'replacement-password' })
    expect(response).toEqual({
      passwordReset: true,
      revokedApiKeyCount: 4,
      revokedRefreshTokenCount: 5,
    })
    expect(queryClient.getQueryData(detailKey)).not.toHaveProperty(
      'new_password',
    )
    expect(queryClient.getQueryState(detailKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true)
  })

  it('keeps the old server snapshot and refreshes detail/list after a 409', async () => {
    server.use(
      http.put(`${apiBaseUrl}/admin/users/user-reader/access`, () =>
        HttpResponse.json(
          {
            code: 'LAST_ADMIN_CONFLICT',
            error_category: 'conflict',
            message: '必须保留至少一个管理员',
            request_id: 'access-conflict-request',
            trace_id: null,
          },
          { status: 409 },
        ),
      ),
    )
    const { api, queryClient, wrapper } = createHarness()
    const { detailKey, listKey } = seedFacts(queryClient, 'user-reader')
    const oldDetail = queryClient.getQueryData(detailKey)
    const { result } = renderHook(
      () =>
        useReplaceManagedUserAccess(api, 'admin-actor', 'user-reader'),
      { wrapper },
    )

    await expect(
      result.current.mutateAsync({
        account_type: 'employee',
        department_access: [
          {
            department_code: 'development',
            is_primary: true,
            role_codes: [],
          },
        ],
        direct_permission_codes: [],
      }),
    ).rejects.toMatchObject({ status: 409 })

    expect(queryClient.getQueryData(detailKey)).toBe(oldDetail)
    expect(queryClient.getQueryState(detailKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true)
  })
})
