import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'

import { App } from '@/app/App'
import { AuthProvider, useAuth } from '@/features/auth/AuthProvider'
import { createAuthTokenStore } from '@/features/auth/auth-tokens'
import { server } from '@/test/server'


const apiBaseUrl = 'http://auth-app.test'

function installRestoredIdentity(
  capabilities: Partial<{
    can_manage_document_grants: boolean
    can_manage_documents: boolean
    can_manage_users: boolean
    can_read_documents: boolean
    can_use_nl2sql: boolean
    can_use_web_search: boolean
    user_management_scope: 'all' | 'department' | 'none'
  }> = {},
) {
  createAuthTokenStore(window.sessionStorage).setTokenPair({
    access_token: ['access', 'stored'].join('-'),
    refresh_token: ['refresh', 'stored'].join('-'),
    token_type: 'bearer',
    expires_in: 300,
  })
  server.use(
    http.post(`${apiBaseUrl}/auth/refresh`, () =>
      HttpResponse.json({
        access_token: ['access', 'rotated'].join('-'),
        refresh_token: ['refresh', 'rotated'].join('-'),
        token_type: 'bearer',
        expires_in: 300,
      }),
    ),
    http.get(`${apiBaseUrl}/auth/me`, () =>
      HttpResponse.json({
        user_id: 'user-1',
        username: 'reader',
        account_type: 'employee',
        is_authenticated: true,
        auth_source: 'jwt',
        global_role_codes: [],
        global_permission_codes: [],
        department_permission_codes: {},
        department_codes: ['dept-a'],
        primary_department_code: 'dept-a',
        email: null,
        display_name: 'Reader',
        token_id: null,
        api_key_id: null,
      }),
    ),
    http.get(`${apiBaseUrl}/auth/capabilities`, () =>
      HttpResponse.json({
        can_manage_users: false,
        user_management_scope: 'none',
        can_manage_document_grants: false,
        can_use_web_search: false,
        can_use_nl2sql: false,
        can_read_documents: false,
        can_manage_documents: false,
        ...capabilities,
      }),
    ),
  )
}

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="current-route">{`${location.pathname}${location.search}`}</output>
}

function ReloadIdentityProbe() {
  const auth = useAuth()
  return (
    <button onClick={() => void auth.reloadIdentitySnapshot()} type="button">
      重新加载身份
    </button>
  )
}

function renderApp(initialEntry: string, includeReloadProbe = false) {
  server.use(
    http.get(`${apiBaseUrl}/conversations`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  )
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider baseUrl={apiBaseUrl} storage={window.sessionStorage}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <App />
          <LocationProbe />
          {includeReloadProbe ? <ReloadIdentityProbe /> : null}
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('App authentication entry', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('shows login for an anonymous visit to a protected route', async () => {
    renderApp('/settings/security')

    expect(
      await screen.findByRole('heading', { name: '登录工作台' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('修改当前密码')).not.toBeInTheDocument()
  })

  it('does not flash protected content while a restored identity is unresolved', async () => {
    createAuthTokenStore(window.sessionStorage).setTokenPair({
      access_token: ['access', 'stored'].join('-'),
      refresh_token: ['refresh', 'stored'].join('-'),
      token_type: 'bearer',
      expires_in: 300,
    })
    let releaseIdentity: (() => void) | undefined
    const identityGate = new Promise<void>((resolve) => {
      releaseIdentity = resolve
    })
    server.use(
      http.post(`${apiBaseUrl}/auth/refresh`, () =>
        HttpResponse.json({
          access_token: ['access', 'rotated'].join('-'),
          refresh_token: ['refresh', 'rotated'].join('-'),
          token_type: 'bearer',
          expires_in: 300,
        }),
      ),
      http.get(`${apiBaseUrl}/auth/me`, async () => {
        await identityGate
        return HttpResponse.json({
          user_id: 'user-1',
          username: 'reader',
          account_type: 'employee',
          is_authenticated: true,
          auth_source: 'jwt',
          global_role_codes: [],
          global_permission_codes: [],
          department_permission_codes: {},
          department_codes: [],
          primary_department_code: null,
          email: null,
          display_name: 'Reader',
          token_id: null,
          api_key_id: null,
        })
      }),
      http.get(`${apiBaseUrl}/auth/capabilities`, async () => {
        await identityGate
        return HttpResponse.json({
          can_manage_users: false,
          user_management_scope: 'none',
          can_manage_document_grants: false,
          can_use_web_search: false,
          can_use_nl2sql: false,
          can_read_documents: true,
          can_manage_documents: false,
        })
      }),
    )

    renderApp('/settings/security')

    expect(
      screen.getByRole('heading', { name: '正在恢复身份' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('修改当前密码')).not.toBeInTheDocument()

    releaseIdentity?.()
    expect(await screen.findByText('修改当前密码')).toBeInTheDocument()
  })

  it('falls back to chat after login when returnTo is an external URL', async () => {
    server.use(
      http.post(`${apiBaseUrl}/auth/login`, () =>
        HttpResponse.json({
          access_token: ['access', 'login'].join('-'),
          refresh_token: ['refresh', 'login'].join('-'),
          token_type: 'bearer',
          expires_in: 300,
        }),
      ),
      http.get(`${apiBaseUrl}/auth/me`, () =>
        HttpResponse.json({
          user_id: 'user-1',
          username: 'reader',
          account_type: 'employee',
          is_authenticated: true,
          auth_source: 'jwt',
          global_role_codes: [],
          global_permission_codes: [],
          department_permission_codes: {},
          department_codes: [],
          primary_department_code: null,
          email: null,
          display_name: 'Reader',
          token_id: null,
          api_key_id: null,
        }),
      ),
      http.get(`${apiBaseUrl}/auth/capabilities`, () =>
        HttpResponse.json({
          can_manage_users: false,
          user_management_scope: 'none',
          can_manage_document_grants: false,
          can_use_web_search: false,
          can_use_nl2sql: false,
          can_read_documents: true,
          can_manage_documents: false,
        }),
      ),
    )
    const user = userEvent.setup()
    renderApp('/login?returnTo=https%3A%2F%2Fevil.example%2Fsteal')
    await screen.findByRole('heading', { name: '登录工作台' })
    await user.type(screen.getByLabelText('用户名或邮箱'), 'reader')
    await user.type(screen.getByLabelText('密码'), 'submitted-value')
    await user.click(screen.getByRole('button', { name: '登录' }))

    await waitFor(() =>
      expect(screen.getByLabelText('current-route')).toHaveTextContent('/chat'),
    )
    expect(
      await screen.findByRole('heading', { name: '新对话' }),
    ).toBeInTheDocument()
  })

  it('derives shell navigation and user identity from the authentication snapshot', async () => {
    installRestoredIdentity({ can_read_documents: true })

    renderApp('/chat')

    expect(
      await screen.findByRole('heading', { name: '新对话' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '对话' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'TaskPlan' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '知识文档' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '账号安全' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '用户管理' })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: '跨部门授权' }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('Reader')).toBeInTheDocument()
    expect(screen.getByText('dept-a')).toBeInTheDocument()
  })

  it('redirects a capability-denied direct visit to chat with a safe notice', async () => {
    installRestoredIdentity()

    renderApp('/admin/users')

    await waitFor(() =>
      expect(screen.getByLabelText('current-route')).toHaveTextContent('/chat'),
    )
    expect(
      screen.getByRole('status', {
        name: '当前账号没有访问该页面的能力，已返回安全入口。',
      }),
    ).toBeInTheDocument()
  })

  it('recomputes navigation and leaves a route immediately after capability loss', async () => {
    installRestoredIdentity({
      can_manage_document_grants: true,
      can_manage_users: true,
      can_read_documents: true,
      user_management_scope: 'all',
    })
    server.use(
      http.get(`${apiBaseUrl}/admin/access/catalog`, () =>
        HttpResponse.json({
          account_types: [],
          department_roles: [],
          departments: [],
          direct_permissions: [],
        }),
      ),
      http.get(`${apiBaseUrl}/admin/users`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
    )
    const user = userEvent.setup()

    renderApp('/admin/users', true)

    expect(
      await screen.findByRole('region', { name: '用户管理' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '跨部门授权' })).toBeInTheDocument()

    server.use(
      http.get(`${apiBaseUrl}/auth/capabilities`, () =>
        HttpResponse.json({
          can_manage_users: false,
          user_management_scope: 'none',
          can_manage_document_grants: false,
          can_use_web_search: false,
          can_use_nl2sql: false,
          can_read_documents: true,
          can_manage_documents: false,
        }),
      ),
    )
    await user.click(screen.getByRole('button', { name: '重新加载身份' }))

    await waitFor(() =>
      expect(screen.getByLabelText('current-route')).toHaveTextContent('/chat'),
    )
    expect(screen.queryByRole('link', { name: '用户管理' })).not.toBeInTheDocument()
    expect(
      screen.queryByRole('link', { name: '跨部门授权' }),
    ).not.toBeInTheDocument()
  })

  it('closes the compact navigation on Escape and returns focus to its trigger', async () => {
    installRestoredIdentity({ can_manage_users: true })
    const user = userEvent.setup()

    renderApp('/chat')

    await screen.findByRole('heading', { name: '新对话' })
    const trigger = document.querySelector<HTMLButtonElement>(
      'button[aria-label="打开导航"]',
    )
    if (trigger === null) throw new Error('Compact navigation trigger missing')
    fireEvent.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    const dialog = screen.getByRole('dialog', { name: '主导航' })
    expect(dialog).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: '关闭导航' })).toHaveFocus()

    await user.keyboard('{Escape}')

    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('dialog', { name: '主导航' })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})
