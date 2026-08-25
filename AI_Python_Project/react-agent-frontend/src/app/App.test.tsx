import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'

import { App } from '@/app/App'
import { AuthProvider } from '@/features/auth/AuthProvider'
import { createAuthTokenStore } from '@/features/auth/auth-tokens'
import { server } from '@/test/server'


const apiBaseUrl = 'http://auth-app.test'

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="current-route">{`${location.pathname}${location.search}`}</output>
}

function renderApp(initialEntry: string) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <AuthProvider baseUrl={apiBaseUrl} storage={window.sessionStorage}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <App />
          <LocationProbe />
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

    expect(await screen.findByLabelText('current-route')).toHaveTextContent('/chat')
    expect(
      await screen.findByRole('heading', { name: '欢迎，Reader' }),
    ).toBeInTheDocument()
  })
})
