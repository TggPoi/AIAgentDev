import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { AuthProvider, useAuth } from '@/features/auth/AuthProvider'
import { ChangePasswordForm } from '@/features/auth/ChangePasswordForm'
import { createAuthTokenStore } from '@/features/auth/auth-tokens'
import { server } from '@/test/server'


const apiBaseUrl = 'http://change-password-form.test'

function AuthenticatedForm() {
  const auth = useAuth()
  return auth.snapshot !== null ? (
    <ChangePasswordForm />
  ) : (
    <p>{auth.status}</p>
  )
}

describe('ChangePasswordForm', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('shows safe field errors and clears both password inputs after failure', async () => {
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
      http.post(`${apiBaseUrl}/auth/change-password`, () =>
        HttpResponse.json(
          {
            code: 'REQUEST_VALIDATION_ERROR',
            message: '请求参数不合法',
            error_category: 'user_error',
            request_id: 'request-change-password',
            trace_id: null,
            field_errors: [
              {
                field: 'new_password',
                code: 'too_short',
                message: '输入长度过短',
              },
            ],
          },
          { status: 422 },
        ),
      ),
    )
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthProvider baseUrl={apiBaseUrl} storage={window.sessionStorage}>
          <AuthenticatedForm />
        </AuthProvider>
      </QueryClientProvider>,
    )

    const currentPassword = await screen.findByLabelText('当前密码')
    const newPassword = screen.getByLabelText('新密码')
    await user.type(currentPassword, 'current-value')
    await user.type(newPassword, 'new-value')
    await user.click(screen.getByRole('button', { name: '修改密码' }))

    expect(await screen.findByText('输入长度过短')).toBeInTheDocument()
    expect(currentPassword).toHaveValue('')
    expect(newPassword).toHaveValue('')
    expect(screen.getByText('请求参数不合法')).toBeInTheDocument()
    expect(screen.getByText(/request-change-password/)).toBeInTheDocument()
  })
})
