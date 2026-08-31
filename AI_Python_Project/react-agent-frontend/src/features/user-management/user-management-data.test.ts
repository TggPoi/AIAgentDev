import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { createHttpClient } from '@/api/http-client'
import { createUserManagementApi } from '@/features/user-management/user-management-api'
import {
  mergeManagedUserPages,
  type ManagedUserSummary,
} from '@/features/user-management/user-management-models'
import { userManagementKeys } from '@/features/user-management/user-management-queries'
import { server } from '@/test/server'


const apiBaseUrl = 'http://user-management.test'

function createApi() {
  return createUserManagementApi(
    createHttpClient({
      baseUrl: apiBaseUrl,
      getAccessToken: () => null,
      requestIdFactory: () => 'user-management-request-id',
    }),
  )
}

function summaryDto(userId: string, username: string) {
  return {
    account_type: 'employee' as const,
    department_codes: ['development'],
    display_name: `${username} display`,
    email: `${username}@example.com`,
    primary_department_code: 'development',
    status: 'active' as const,
    updated_at: '2026-08-31T01:00:00Z',
    user_id: userId,
    username,
  }
}

function summary(userId: string, username: string): ManagedUserSummary {
  return {
    accountType: 'employee',
    departmentCodes: ['development'],
    displayName: `${username} display`,
    email: `${username}@example.com`,
    primaryDepartmentCode: 'development',
    status: 'active',
    updatedAt: '2026-08-31T01:00:00Z',
    userId,
    username,
  }
}

describe('user management private query keys', () => {
  it('isolates catalog, list filters and detail by authenticated user', () => {
    const params = {
      departmentCode: 'development',
      limit: 20,
      query: 'reader',
      status: 'active' as const,
    }

    expect(userManagementKeys.catalog('user-a')).not.toEqual(
      userManagementKeys.catalog('user-b'),
    )
    expect(userManagementKeys.list('user-a', params)).not.toEqual(
      userManagementKeys.list('user-b', params),
    )
    expect(userManagementKeys.detail('user-a', 'target')).not.toEqual(
      userManagementKeys.detail('user-b', 'target'),
    )
  })
})

describe('managed user keyset page merge', () => {
  it('preserves server order and keeps the first occurrence of each user', () => {
    expect(
      mergeManagedUserPages([
        {
          items: [summary('user-b', 'beta'), summary('user-a', 'alpha')],
          nextCursor: 'cursor-2',
        },
        {
          items: [
            summary('user-a', 'duplicate'),
            summary('user-c', 'gamma'),
          ],
          nextCursor: null,
        },
      ]).map((item) => item.userId),
    ).toEqual(['user-b', 'user-a', 'user-c'])
  })
})

describe('user management HTTP adapter', () => {
  it('maps only server-trimmed catalog fields', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/access/catalog`, () =>
        HttpResponse.json({
          account_types: [
            {
              code: 'employee',
              description: '普通员工',
              name: '员工',
              risk_level: null,
              unexpected: 'must-not-enter-domain-model',
            },
          ],
          department_roles: [
            {
              code: 'department_reader',
              description: null,
              name: '部门读者',
              risk_level: null,
            },
          ],
          departments: [
            {
              code: 'development',
              description: '研发部门',
              name: '研发部',
              risk_level: null,
            },
          ],
          direct_permissions: [
            {
              code: 'agent:tool:web_search',
              description: '允许联网搜索',
              name: '联网搜索',
              risk_level: 'medium',
            },
          ],
          private_scope: 'must-not-enter-domain-model',
        }),
      ),
    )

    await expect(createApi().getAccessCatalog()).resolves.toEqual({
      accountTypes: [
        {
          code: 'employee',
          description: '普通员工',
          name: '员工',
          riskLevel: null,
        },
      ],
      departmentRoles: [
        {
          code: 'department_reader',
          description: null,
          name: '部门读者',
          riskLevel: null,
        },
      ],
      departments: [
        {
          code: 'development',
          description: '研发部门',
          name: '研发部',
          riskLevel: null,
        },
      ],
      directPermissions: [
        {
          code: 'agent:tool:web_search',
          description: '允许联网搜索',
          name: '联网搜索',
          riskLevel: 'medium',
        },
      ],
    })
  })

  it('passes opaque cursors and non-empty filters, then maps the list page', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/users`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('cursor')).toBe('opaque+/=')
        expect(url.searchParams.get('limit')).toBe('20')
        expect(url.searchParams.get('query')).toBe('reader')
        expect(url.searchParams.get('status')).toBe('active')
        expect(url.searchParams.get('department_code')).toBe('development')
        return HttpResponse.json({
          items: [summaryDto('user-reader', 'reader')],
          next_cursor: 'cursor-2',
        })
      }),
    )

    await expect(
      createApi().listUsers({
        cursor: 'opaque+/=',
        departmentCode: 'development',
        limit: 20,
        query: 'reader',
        status: 'active',
      }),
    ).resolves.toEqual({
      items: [summary('user-reader', 'reader')],
      nextCursor: 'cursor-2',
    })
  })

  it('omits empty optional filters instead of inventing scope', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/users`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.has('cursor')).toBe(false)
        expect(url.searchParams.has('query')).toBe(false)
        expect(url.searchParams.has('status')).toBe(false)
        expect(url.searchParams.has('department_code')).toBe(false)
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
    )

    await createApi().listUsers({
      cursor: null,
      departmentCode: null,
      limit: 20,
      query: null,
      status: null,
    })
  })

  it('encodes user ids and maps detail without arbitrary fields', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/users/user%20id%3F%23`, () =>
        HttpResponse.json({
          account_type: 'employee',
          created_at: '2026-08-30T01:00:00Z',
          department_access: [
            {
              department_code: 'development',
              is_primary: true,
              permission_codes: ['knowledge:read'],
              role_codes: ['department_reader'],
              private_grants: ['must-not-enter-domain-model'],
            },
          ],
          direct_permission_codes: ['agent:tool:web_search'],
          display_name: 'Reader',
          effective_global_permission_codes: ['agent:tool:web_search'],
          email: 'reader@example.com',
          global_role_codes: [],
          last_login_at: null,
          status: 'active',
          updated_at: '2026-08-31T01:00:00Z',
          user_id: 'user id?#',
          username: 'reader',
          private_acl: 'must-not-enter-domain-model',
        }),
      ),
    )

    await expect(createApi().getUser('user id?#')).resolves.toEqual({
      accountType: 'employee',
      createdAt: '2026-08-30T01:00:00Z',
      departmentAccess: [
        {
          departmentCode: 'development',
          isPrimary: true,
          permissionCodes: ['knowledge:read'],
          roleCodes: ['department_reader'],
        },
      ],
      directPermissionCodes: ['agent:tool:web_search'],
      displayName: 'Reader',
      effectiveGlobalPermissionCodes: ['agent:tool:web_search'],
      email: 'reader@example.com',
      globalRoleCodes: [],
      lastLoginAt: null,
      status: 'active',
      updatedAt: '2026-08-31T01:00:00Z',
      userId: 'user id?#',
      username: 'reader',
    })
  })
})
