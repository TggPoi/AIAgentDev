import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'

import { createHttpClient } from '@/api/http-client'
import { createUserManagementApi } from '@/features/user-management/user-management-api'
import { UserManagementWorkspace } from '@/features/user-management/UserManagementWorkspace'
import { server } from '@/test/server'


const apiBaseUrl = 'http://user-management-workspace.test'

function createApi() {
  return createUserManagementApi(
    createHttpClient({
      baseUrl: apiBaseUrl,
      getAccessToken: () => null,
      requestIdFactory: () => 'user-management-workspace-request',
    }),
  )
}

function LocationProbe() {
  const location = useLocation()
  return (
    <output aria-label="current-route">
      {`${location.pathname}${location.search}`}
    </output>
  )
}

function renderWorkspace(initialEntry: string, userId: string | null = null) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <UserManagementWorkspace
          api={createApi()}
          currentUserId="admin-actor"
          reloadIdentitySnapshot={async () => undefined}
          userBoundary="admin-actor"
          userId={userId}
        />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function catalogDto() {
  return {
    account_types: [
      { code: 'admin', description: null, name: '管理员', risk_level: null },
      {
        code: 'employee',
        description: null,
        name: '员工',
        risk_level: null,
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
        description: null,
        name: '研发部',
        risk_level: null,
      },
    ],
    direct_permissions: [
      {
        code: 'agent:tool:web_search',
        description: null,
        name: '联网搜索',
        risk_level: 'medium',
      },
    ],
  }
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

describe('UserManagementWorkspace list', () => {
  it('uses server-trimmed catalog filters and appends opaque cursor pages', async () => {
    const requests: URL[] = []
    server.use(
      http.get(`${apiBaseUrl}/admin/access/catalog`, () =>
        HttpResponse.json(catalogDto()),
      ),
      http.get(`${apiBaseUrl}/admin/users`, ({ request }) => {
        const url = new URL(request.url)
        requests.push(url)
        return HttpResponse.json(
          url.searchParams.get('cursor') === null
            ? {
                items: [summaryDto('user-reader', 'reader')],
                next_cursor: 'opaque+/=',
              }
            : {
                items: [summaryDto('user-writer', 'writer')],
                next_cursor: null,
              },
        )
      }),
    )
    const user = userEvent.setup()
    renderWorkspace('/admin/users')

    const list = await screen.findByRole('list', { name: '用户列表' })
    expect(within(list).getByText('reader')).toBeInTheDocument()
    expect(within(list).getByText('主部门：研发部')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('关键词'), {
      target: { value: 'reader' },
    })
    await user.selectOptions(screen.getByLabelText('账号状态'), 'active')
    await user.selectOptions(screen.getByLabelText('部门'), 'development')

    await waitFor(() => {
      expect(screen.getByLabelText('current-route')).toHaveTextContent(
        '/admin/users?query=reader&status=active&department_code=development',
      )
    })
    await waitFor(() => {
      expect(
        requests.some(
          (url) =>
            url.searchParams.get('query') === 'reader' &&
            url.searchParams.get('status') === 'active' &&
            url.searchParams.get('department_code') === 'development',
        ),
      ).toBe(true)
    })

    await user.click(screen.getByRole('button', { name: '加载更多用户' }))
    expect(await screen.findByText('writer')).toBeInTheDocument()
    expect(requests.at(-1)?.searchParams.get('cursor')).toBe('opaque+/=')
  })

  it('maps approved 422 fields without rendering the form-level message', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/access/catalog`, () =>
        HttpResponse.json(catalogDto()),
      ),
      http.get(`${apiBaseUrl}/admin/users`, () =>
        HttpResponse.json(
          {
            code: 'REQUEST_VALIDATION_ERROR',
            error_category: 'user_error',
            field_errors: [
              { field: 'query', code: 'too_long', message: '关键词过长' },
            ],
            message: 'must-not-be-rendered',
            request_id: 'request-filter-error',
            trace_id: null,
          },
          { status: 422 },
        ),
      ),
    )

    renderWorkspace('/admin/users?query=too-long')

    expect(await screen.findByText('关键词过长')).toBeInTheDocument()
    expect(screen.getByLabelText('关键词')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.queryByText('must-not-be-rendered')).not.toBeInTheDocument()
  })
})

describe('UserManagementWorkspace detail', () => {
  it('renders account, department, role and permission facts from the server', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/access/catalog`, () =>
        HttpResponse.json(catalogDto()),
      ),
      http.get(`${apiBaseUrl}/admin/users/user-reader`, () =>
        HttpResponse.json({
          account_type: 'employee',
          created_at: '2026-08-30T01:00:00Z',
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
          effective_global_permission_codes: [
            'agent:tool:web_search',
            'conversation:read',
          ],
          email: 'reader@example.com',
          global_role_codes: [],
          last_login_at: null,
          status: 'active',
          updated_at: '2026-08-31T01:00:00Z',
          user_id: 'user-reader',
          username: 'reader',
        }),
      ),
    )

    renderWorkspace('/admin/users/user-reader', 'user-reader')

    expect(
      await screen.findByRole('heading', { name: 'reader' }),
    ).toBeInTheDocument()
    expect(screen.getByText('员工')).toBeInTheDocument()
    expect(screen.getByText('研发部（主部门）')).toBeInTheDocument()
    expect(screen.getByText('部门读者')).toBeInTheDocument()
    expect(screen.getAllByText('联网搜索')).toHaveLength(2)
    expect(screen.getByText('conversation:read')).toBeInTheDocument()
  })

  it.each([
    [403, 'MANAGED_USER_SCOPE_FORBIDDEN'],
    [404, 'MANAGED_USER_NOT_FOUND'],
  ])('returns a safe unavailable state for %s', async (status, code) => {
    server.use(
      http.get(`${apiBaseUrl}/admin/access/catalog`, () =>
        HttpResponse.json(catalogDto()),
      ),
      http.get(`${apiBaseUrl}/admin/users/user-hidden`, () =>
        HttpResponse.json(
          {
            code,
            error_category: 'user_error',
            message: 'must-not-be-rendered',
            request_id: 'request-hidden-user',
            trace_id: null,
          },
          { status },
        ),
      ),
    )

    renderWorkspace('/admin/users/user-hidden', 'user-hidden')

    expect(await screen.findByText('用户不可用')).toBeInTheDocument()
    expect(screen.getByText(new RegExp(code))).toBeInTheDocument()
    expect(screen.queryByText('must-not-be-rendered')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回用户列表' })).toHaveAttribute(
      'href',
      '/admin/users',
    )
  })
})
