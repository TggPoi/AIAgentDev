import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'

import { App } from '@/app/App'
import { AuthProvider } from '@/features/auth/AuthProvider'
import { createAuthTokenStore } from '@/features/auth/auth-tokens'
import { server } from '@/test/server'


const apiBaseUrl = 'http://user-management-ui.test'

function catalogDto() {
  return {
    account_types: [
      { code: 'employee', description: null, name: '员工', risk_level: null },
      {
        code: 'department_manager',
        description: null,
        name: '部门主管',
        risk_level: 'high',
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

function detailDto(
  userId: string,
  overrides: Partial<{
    account_type: 'admin' | 'department_manager' | 'employee'
    direct_permission_codes: string[]
  }> = {},
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
    status: 'active' as const,
    updated_at: '2026-08-31T02:00:00Z',
    user_id: userId,
    username: 'reader',
    ...overrides,
  }
}

function installAdminIdentity() {
  createAuthTokenStore(window.sessionStorage).setTokenPair({
    access_token: ['access', 'stored'].join('-'),
    expires_in: 300,
    refresh_token: ['refresh', 'stored'].join('-'),
    token_type: 'bearer',
  })
  server.use(
    http.post(`${apiBaseUrl}/auth/refresh`, () =>
      HttpResponse.json({
        access_token: ['access', 'rotated'].join('-'),
        expires_in: 300,
        refresh_token: ['refresh', 'rotated'].join('-'),
        token_type: 'bearer',
      }),
    ),
    http.get(`${apiBaseUrl}/auth/me`, () =>
      HttpResponse.json({
        account_type: 'admin',
        api_key_id: null,
        auth_source: 'jwt',
        department_codes: [],
        department_permission_codes: {},
        display_name: 'Admin',
        email: null,
        global_permission_codes: [],
        global_role_codes: ['admin'],
        is_authenticated: true,
        primary_department_code: null,
        token_id: null,
        user_id: 'admin-actor',
        username: 'admin',
      }),
    ),
    http.get(`${apiBaseUrl}/auth/capabilities`, () =>
      HttpResponse.json({
        can_manage_document_grants: false,
        can_manage_documents: true,
        can_manage_users: true,
        can_read_documents: true,
        can_use_nl2sql: false,
        can_use_web_search: true,
        user_management_scope: 'all',
      }),
    ),
    http.get(`${apiBaseUrl}/admin/access/catalog`, () =>
      HttpResponse.json(catalogDto()),
    ),
    http.get(`${apiBaseUrl}/admin/users`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    http.get(`${apiBaseUrl}/admin/users/user-reader`, () =>
      HttpResponse.json(detailDto('user-reader')),
    ),
  )
}

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="current-route">{location.pathname}</output>
}

function renderApp(initialEntry = '/admin/users') {
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: {
            mutations: { retry: false },
            queries: { retry: false },
          },
        })
      }
    >
      <AuthProvider baseUrl={apiBaseUrl} storage={window.sessionStorage}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <App />
          <LocationProbe />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

async function fillValidCreateForm() {
  const user = userEvent.setup()
  const dialog = await screen.findByRole('dialog', { name: '创建账号' })
  await user.type(within(dialog).getByLabelText('用户名'), 'reader')
  await user.type(
    within(dialog).getByLabelText('初始密码'),
    'form-local-password',
  )
  await user.type(within(dialog).getByLabelText('邮箱（可选）'), 'reader@example.com')
  await user.type(within(dialog).getByLabelText('展示名称（可选）'), 'Reader')
  await user.selectOptions(within(dialog).getByLabelText('账号类型'), 'employee')
  await user.click(within(dialog).getByLabelText('选择部门 研发部'))
  await user.click(within(dialog).getByLabelText('研发部：部门读者'))
  await user.click(within(dialog).getByLabelText('直接权限 联网搜索'))
  return { dialog, user }
}

describe('User Management create flow', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    installAdminIdentity()
  })

  it('submits only catalog-backed values and navigates to the created detail', async () => {
    let receivedBody: unknown
    server.use(
      http.post(`${apiBaseUrl}/admin/users`, async ({ request }) => {
        receivedBody = await request.json()
        return HttpResponse.json(detailDto('user-reader'), { status: 201 })
      }),
    )
    renderApp()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: '创建账号' }))
    const { dialog } = await fillValidCreateForm()
    expect(
      within(dialog).queryByRole('option', { name: '管理员' }),
    ).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: '确认创建' }))

    await waitFor(() => {
      expect(screen.getByLabelText('current-route')).toHaveTextContent(
        '/admin/users/user-reader',
      )
    })
    expect(receivedBody).toEqual({
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
      password: 'form-local-password',
      username: 'reader',
    })
    await user.click(screen.getByRole('link', { name: /返回用户列表/ }))
    await user.click(await screen.findByRole('button', { name: '创建账号' }))
    expect(
      within(
        await screen.findByRole('dialog', { name: '创建账号' }),
      ).getByLabelText('初始密码'),
    ).toHaveValue('')
  })

  it('locks submission, maps safe 422 fields and clears the password after failure', async () => {
    let releaseResponse: (() => void) | undefined
    const responseGate = new Promise<void>((resolve) => {
      releaseResponse = resolve
    })
    server.use(
      http.post(`${apiBaseUrl}/admin/users`, async () => {
        await responseGate
        return HttpResponse.json(
          {
            code: 'REQUEST_VALIDATION_ERROR',
            error_category: 'user_error',
            field_errors: [
              { code: 'invalid', field: 'username', message: '用户名不可用' },
              {
                code: 'invalid',
                field: 'department_access',
                message: '部门访问已变化',
              },
            ],
            message: 'must-not-be-rendered',
            request_id: 'create-validation-request',
            trace_id: null,
          },
          { status: 422 },
        )
      }),
    )
    renderApp()
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: '创建账号' }))
    const { dialog } = await fillValidCreateForm()
    const submit = within(dialog).getByRole('button', { name: '确认创建' })
    await user.click(submit)
    await waitFor(() => expect(submit).toBeDisabled())

    releaseResponse?.()
    expect(await within(dialog).findByText('用户名不可用')).toBeInTheDocument()
    expect(within(dialog).getByText('部门访问已变化')).toBeInTheDocument()
    expect(within(dialog).queryByText('must-not-be-rendered')).not.toBeInTheDocument()
    expect(within(dialog).getByLabelText('初始密码')).toHaveValue('')
    expect(submit).toBeEnabled()
  })
})

describe('User Management access editor', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    installAdminIdentity()
  })

  it('requires a second account-type confirmation and puts the complete snapshot', async () => {
    let receivedBody: unknown
    let releaseResponse: (() => void) | undefined
    const responseGate = new Promise<void>((resolve) => {
      releaseResponse = resolve
    })
    server.use(
      http.put(
        `${apiBaseUrl}/admin/users/user-reader/access`,
        async ({ request }) => {
          receivedBody = await request.json()
          await responseGate
          return HttpResponse.json(
            detailDto('user-reader', {
              account_type: 'department_manager',
              direct_permission_codes: [],
            }),
          )
        },
      ),
    )
    renderApp('/admin/users/user-reader')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: '编辑访问' }))
    const dialog = await screen.findByRole('dialog', { name: '编辑用户访问' })
    expect(within(dialog).getByLabelText('选择部门 研发部')).toBeChecked()
    expect(within(dialog).getByLabelText('研发部：部门读者')).toBeChecked()
    await user.selectOptions(
      within(dialog).getByLabelText('账号类型'),
      'department_manager',
    )
    await user.click(within(dialog).getByLabelText('直接权限 联网搜索'))
    await user.click(within(dialog).getByRole('button', { name: '保存访问' }))

    expect(receivedBody).toBeUndefined()
    const confirm = within(dialog).getByRole('button', {
      name: '确认账号类型变更并保存',
    })
    await user.click(confirm)
    await waitFor(() => expect(confirm).toBeDisabled())
    expect(receivedBody).toEqual({
      account_type: 'department_manager',
      department_access: [
        {
          department_code: 'development',
          is_primary: true,
          role_codes: ['department_reader'],
        },
      ],
      direct_permission_codes: [],
    })

    releaseResponse?.()
    expect(
      await screen.findByRole('heading', { name: 'reader' }),
    ).toBeInTheDocument()
    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', { name: '编辑用户访问' }),
      ).not.toBeInTheDocument()
    })
    expect(screen.getByText('部门主管')).toBeInTheDocument()
  })

  it('maps safe access 422 fields without rendering the raw message', async () => {
    server.use(
      http.put(`${apiBaseUrl}/admin/users/user-reader/access`, () =>
        HttpResponse.json(
          {
            code: 'MANAGED_USER_ACCESS_INVALID',
            error_category: 'user_error',
            field_errors: [
              {
                code: 'invalid',
                field: 'direct_permission_codes',
                message: '直接权限已变化',
              },
            ],
            message: 'must-not-be-rendered',
            request_id: 'access-validation-request',
            trace_id: null,
          },
          { status: 422 },
        ),
      ),
    )
    renderApp('/admin/users/user-reader')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: '编辑访问' }))
    const dialog = await screen.findByRole('dialog', { name: '编辑用户访问' })
    await user.click(within(dialog).getByLabelText('直接权限 联网搜索'))
    await user.click(within(dialog).getByRole('button', { name: '保存访问' }))

    expect(await within(dialog).findByText('直接权限已变化')).toBeInTheDocument()
    expect(within(dialog).queryByText('must-not-be-rendered')).not.toBeInTheDocument()
  })

  it('keeps the server detail and refetches it after a 409 conflict', async () => {
    let detailRequests = 0
    server.use(
      http.get(`${apiBaseUrl}/admin/users/user-reader`, () => {
        detailRequests += 1
        return HttpResponse.json(detailDto('user-reader'))
      }),
      http.put(`${apiBaseUrl}/admin/users/user-reader/access`, () =>
        HttpResponse.json(
          {
            code: 'LAST_ADMIN_CONFLICT',
            error_category: 'conflict',
            message: 'must-not-be-rendered',
            request_id: 'access-conflict-request',
            trace_id: null,
          },
          { status: 409 },
        ),
      ),
    )
    renderApp('/admin/users/user-reader')
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: '编辑访问' }))
    const dialog = await screen.findByRole('dialog', { name: '编辑用户访问' })
    await user.click(within(dialog).getByLabelText('直接权限 联网搜索'))
    await user.click(within(dialog).getByRole('button', { name: '保存访问' }))

    expect(await within(dialog).findByText('保存访问失败')).toBeInTheDocument()
    expect(within(dialog).getByText(/LAST_ADMIN_CONFLICT/)).toBeInTheDocument()
    expect(within(dialog).queryByText('must-not-be-rendered')).not.toBeInTheDocument()
    await waitFor(() => expect(detailRequests).toBeGreaterThan(1))
    expect(screen.getAllByText('联网搜索').length).toBeGreaterThan(0)
  })
})
