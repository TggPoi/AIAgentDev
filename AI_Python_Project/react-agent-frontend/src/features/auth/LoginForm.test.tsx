import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AuthProvider } from '@/features/auth/AuthProvider'
import { LoginForm } from '@/features/auth/LoginForm'
import { server } from '@/test/server'


const apiBaseUrl = 'http://login-form.test'

describe('LoginForm', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('maps safe 422 field errors, retains the account, and clears the password', async () => {
    const hiddenInput = ['must', 'not', 'render'].join('-')
    server.use(
      http.post(`${apiBaseUrl}/auth/login`, () =>
        HttpResponse.json(
          {
            code: 'REQUEST_VALIDATION_ERROR',
            message: '请求参数不合法',
            error_category: 'user_error',
            request_id: 'request-login-validation',
            trace_id: null,
            field_errors: [
              {
                field: 'password',
                code: 'too_short',
                message: '输入长度过短',
                input: hiddenInput,
              },
            ],
          },
          { status: 422 },
        ),
      ),
    )
    const onAuthenticated = vi.fn()
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthProvider baseUrl={apiBaseUrl} storage={window.sessionStorage}>
          <LoginForm onAuthenticated={onAuthenticated} />
        </AuthProvider>
      </QueryClientProvider>,
    )

    const account = screen.getByLabelText('用户名或邮箱')
    const password = screen.getByLabelText('密码')
    await user.type(account, 'reader@example.com')
    await user.type(password, hiddenInput)
    await user.click(screen.getByRole('button', { name: '登录' }))

    expect(await screen.findByText('输入长度过短')).toBeInTheDocument()
    expect(account).toHaveValue('reader@example.com')
    expect(password).toHaveValue('')
    expect(screen.getByText('请求参数不合法')).toBeInTheDocument()
    expect(screen.queryByText(hiddenInput)).not.toBeInTheDocument()
    expect(onAuthenticated).not.toHaveBeenCalled()
  })
})
