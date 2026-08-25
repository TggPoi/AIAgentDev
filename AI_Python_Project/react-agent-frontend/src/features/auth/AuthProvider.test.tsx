import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'

import { AuthProvider, useAuth } from '@/features/auth/AuthProvider'
import { createAuthTokenStore } from '@/features/auth/auth-tokens'
import { server } from '@/test/server'


const apiBaseUrl = 'http://auth-provider.test'

function AuthProbe() {
  const auth = useAuth()
  return (
    <p>
      {auth.status}:{auth.snapshot?.currentUser.displayName ?? 'none'}
    </p>
  )
}

describe('AuthProvider', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('publishes controller state changes through one authentication context', async () => {
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
          display_name: 'Provider Reader',
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

    render(
      <QueryClientProvider client={new QueryClient()}>
        <AuthProvider baseUrl={apiBaseUrl} storage={window.sessionStorage}>
          <AuthProbe />
        </AuthProvider>
      </QueryClientProvider>,
    )

    expect(screen.getByText('bootstrapping:none')).toBeInTheDocument()
    expect(
      await screen.findByText('authenticated:Provider Reader'),
    ).toBeInTheDocument()
  })
})
