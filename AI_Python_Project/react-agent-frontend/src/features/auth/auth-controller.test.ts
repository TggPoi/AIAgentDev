import { QueryClient } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createAuthController } from '@/features/auth/auth-controller'
import { createAuthTokenStore } from '@/features/auth/auth-tokens'
import { server } from '@/test/server'


const apiBaseUrl = 'http://auth.test'

function tokenPair(suffix: string) {
  return {
    access_token: ['access', suffix].join('-'),
    refresh_token: ['refresh', suffix].join('-'),
    token_type: 'bearer',
    expires_in: 300,
  }
}

function currentUser(displayName: string, userId = 'user-1') {
  return {
    user_id: userId,
    username: 'reader',
    account_type: 'employee' as const,
    is_authenticated: true,
    auth_source: 'jwt',
    global_role_codes: [],
    global_permission_codes: [],
    department_permission_codes: {},
    department_codes: ['research'],
    primary_department_code: 'research',
    email: 'reader@example.com',
    display_name: displayName,
    token_id: null,
    api_key_id: null,
  }
}

function capabilities(canUseWebSearch: boolean) {
  return {
    can_manage_users: false,
    user_management_scope: 'none' as const,
    can_manage_document_grants: false,
    can_use_web_search: canUseWebSearch,
    can_use_nl2sql: false,
    can_read_documents: true,
    can_manage_documents: false,
  }
}

describe('AuthController', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
  })

  it('rotates a restored refresh token and atomically publishes the bootstrap snapshot', async () => {
    createAuthTokenStore(window.sessionStorage).setTokenPair(tokenPair('stored'))
    let releaseMe: (() => void) | undefined
    let releaseCapabilities: (() => void) | undefined
    const meGate = new Promise<void>((resolve) => {
      releaseMe = resolve
    })
    const capabilitiesGate = new Promise<void>((resolve) => {
      releaseCapabilities = resolve
    })
    const meStarted = vi.fn()
    const capabilitiesStarted = vi.fn()
    const observedAuthorization: string[] = []

    server.use(
      http.post(`${apiBaseUrl}/auth/refresh`, async ({ request }) => {
        expect(await request.json()).toEqual({
          refresh_token: ['refresh', 'stored'].join('-'),
        })
        return HttpResponse.json(tokenPair('rotated'))
      }),
      http.get(`${apiBaseUrl}/auth/me`, async () => {
        meStarted()
        await meGate
        return HttpResponse.json(currentUser('Atomic Reader'))
      }),
      http.get(`${apiBaseUrl}/auth/capabilities`, async () => {
        capabilitiesStarted()
        await capabilitiesGate
        return HttpResponse.json(capabilities(true))
      }),
      http.get(`${apiBaseUrl}/protected-probe`, ({ request }) => {
        observedAuthorization.push(request.headers.get('Authorization') ?? '')
        return HttpResponse.json({ ok: true })
      }),
    )
    const controller = createAuthController({
      baseUrl: apiBaseUrl,
      queryClient: new QueryClient(),
      storage: window.sessionStorage,
    })

    const initialization = controller.initialize()
    await vi.waitFor(() => {
      expect(meStarted).toHaveBeenCalledOnce()
      expect(capabilitiesStarted).toHaveBeenCalledOnce()
    })
    expect(controller.getState()).toMatchObject({
      snapshot: null,
      status: 'bootstrapping',
    })

    releaseMe?.()
    await Promise.resolve()
    expect(controller.getState().snapshot).toBeNull()
    releaseCapabilities?.()
    await initialization

    expect(controller.getState()).toMatchObject({
      status: 'authenticated',
      snapshot: {
        currentUser: { displayName: 'Atomic Reader', userId: 'user-1' },
        capabilities: { canUseWebSearch: true },
      },
    })
    await controller.httpClient.request('/protected-probe')
    expect(observedAuthorization).toEqual([
      `Bearer ${['access', 'rotated'].join('-')}`,
    ])
  })

  it('keeps reload B when the older reload A finishes last', async () => {
    createAuthTokenStore(window.sessionStorage).setTokenPair(tokenPair('stored'))
    let meCall = 0
    let capabilitiesCall = 0
    let releaseMeA: (() => void) | undefined
    let releaseCapabilitiesA: (() => void) | undefined
    const meAGate = new Promise<void>((resolve) => {
      releaseMeA = resolve
    })
    const capabilitiesAGate = new Promise<void>((resolve) => {
      releaseCapabilitiesA = resolve
    })

    server.use(
      http.post(`${apiBaseUrl}/auth/refresh`, () =>
        HttpResponse.json(tokenPair('rotated')),
      ),
      http.get(`${apiBaseUrl}/auth/me`, async () => {
        meCall += 1
        if (meCall === 2) {
          await meAGate
        }
        const name = meCall === 1 ? 'Initial' : meCall === 2 ? 'Reload A' : 'Reload B'
        return HttpResponse.json(currentUser(name))
      }),
      http.get(`${apiBaseUrl}/auth/capabilities`, async () => {
        capabilitiesCall += 1
        if (capabilitiesCall === 2) {
          await capabilitiesAGate
        }
        return HttpResponse.json(capabilities(capabilitiesCall === 3))
      }),
    )
    const controller = createAuthController({
      baseUrl: apiBaseUrl,
      queryClient: new QueryClient(),
      storage: window.sessionStorage,
    })
    await controller.initialize()

    const reloadA = controller.reloadIdentitySnapshot()
    await vi.waitFor(() => {
      expect(meCall).toBe(2)
      expect(capabilitiesCall).toBe(2)
    })
    await controller.reloadIdentitySnapshot()
    expect(controller.getState()).toMatchObject({
      snapshot: {
        currentUser: { displayName: 'Reload B' },
        capabilities: { canUseWebSearch: true },
      },
    })

    releaseMeA?.()
    releaseCapabilitiesA?.()
    await reloadA
    expect(controller.getState()).toMatchObject({
      snapshot: {
        currentUser: { displayName: 'Reload B' },
        capabilities: { canUseWebSearch: true },
      },
    })
  })

  it('invalidates an older reload and private state as soon as logout starts', async () => {
    createAuthTokenStore(window.sessionStorage).setTokenPair(tokenPair('stored'))
    const queryClient = new QueryClient()
    let meCall = 0
    let capabilitiesCall = 0
    let releaseOldMe: (() => void) | undefined
    let releaseOldCapabilities: (() => void) | undefined
    let releaseLogout: (() => void) | undefined
    const oldMeGate = new Promise<void>((resolve) => {
      releaseOldMe = resolve
    })
    const oldCapabilitiesGate = new Promise<void>((resolve) => {
      releaseOldCapabilities = resolve
    })
    const logoutGate = new Promise<void>((resolve) => {
      releaseLogout = resolve
    })
    const logoutStarted = vi.fn()

    server.use(
      http.post(`${apiBaseUrl}/auth/refresh`, () =>
        HttpResponse.json(tokenPair('rotated')),
      ),
      http.get(`${apiBaseUrl}/auth/me`, async () => {
        meCall += 1
        if (meCall === 2) {
          await oldMeGate
        }
        return HttpResponse.json(currentUser(meCall === 1 ? 'Initial' : 'Old'))
      }),
      http.get(`${apiBaseUrl}/auth/capabilities`, async () => {
        capabilitiesCall += 1
        if (capabilitiesCall === 2) {
          await oldCapabilitiesGate
        }
        return HttpResponse.json(capabilities(false))
      }),
      http.post(`${apiBaseUrl}/auth/logout`, async ({ request }) => {
        logoutStarted()
        expect(await request.json()).toEqual({
          refresh_token: ['refresh', 'rotated'].join('-'),
        })
        await logoutGate
        return HttpResponse.json({ logged_out: true })
      }),
    )
    const controller = createAuthController({
      baseUrl: apiBaseUrl,
      queryClient,
      storage: window.sessionStorage,
    })
    await controller.initialize()
    queryClient.setQueryData(['user-1', 'private'], { value: 'private' })
    const activity = new AbortController()
    controller.registerPrivateActivity(activity)

    const oldReload = controller.reloadIdentitySnapshot()
    await vi.waitFor(() => {
      expect(meCall).toBe(2)
      expect(capabilitiesCall).toBe(2)
    })
    const logout = controller.logout()
    await vi.waitFor(() => expect(logoutStarted).toHaveBeenCalledOnce())
    expect(controller.getState().status).toBe('loggingOut')
    expect(activity.signal.aborted).toBe(true)
    expect(queryClient.getQueryData(['user-1', 'private'])).toBeUndefined()

    releaseOldMe?.()
    releaseOldCapabilities?.()
    await oldReload
    expect(controller.getState().status).toBe('loggingOut')

    releaseLogout?.()
    await logout
    expect(controller.getState()).toMatchObject({
      snapshot: null,
      status: 'anonymous',
    })
    expect(window.sessionStorage.length).toBe(0)
  })

  it('clears authentication, private cache, and activities when refresh fails', async () => {
    createAuthTokenStore(window.sessionStorage).setTokenPair(tokenPair('stored'))
    const queryClient = new QueryClient()
    let refreshCall = 0
    let releaseFailedRefresh: (() => void) | undefined
    const failedRefreshGate = new Promise<void>((resolve) => {
      releaseFailedRefresh = resolve
    })
    const failedRefreshStarted = vi.fn()

    server.use(
      http.post(`${apiBaseUrl}/auth/refresh`, async () => {
        refreshCall += 1
        if (refreshCall === 1) {
          return HttpResponse.json(tokenPair('rotated'))
        }
        failedRefreshStarted()
        await failedRefreshGate
        return HttpResponse.json(
          { code: 'AUTHENTICATION_FAILED', message: '身份认证已失效' },
          { status: 401 },
        )
      }),
      http.get(`${apiBaseUrl}/auth/me`, () =>
        HttpResponse.json(currentUser('Initial')),
      ),
      http.get(`${apiBaseUrl}/auth/capabilities`, () =>
        HttpResponse.json(capabilities(false)),
      ),
      http.get(`${apiBaseUrl}/protected-probe`, () =>
        HttpResponse.json(
          { code: 'AUTHENTICATION_FAILED', message: '身份认证已失效' },
          { status: 401 },
        ),
      ),
    )
    const controller = createAuthController({
      baseUrl: apiBaseUrl,
      queryClient,
      storage: window.sessionStorage,
    })
    await controller.initialize()
    queryClient.setQueryData(['user-1', 'private'], { value: 'private' })
    const activity = new AbortController()
    controller.registerPrivateActivity(activity)

    const request = controller.httpClient
      .request('/protected-probe')
      .catch((error: unknown) => error)
    await vi.waitFor(() => expect(failedRefreshStarted).toHaveBeenCalledOnce())
    expect(controller.getState().status).toBe('refreshing')

    releaseFailedRefresh?.()
    await expect(request).resolves.toMatchObject({ status: 401 })
    expect(controller.getState()).toMatchObject({
      snapshot: null,
      status: 'anonymous',
    })
    expect(activity.signal.aborted).toBe(true)
    expect(queryClient.getQueryData(['user-1', 'private'])).toBeUndefined()
    expect(window.sessionStorage.length).toBe(0)
  })

  it('rejects an unexpected identity change and clears the previous private boundary', async () => {
    createAuthTokenStore(window.sessionStorage).setTokenPair(tokenPair('stored'))
    const queryClient = new QueryClient()
    let meCall = 0
    server.use(
      http.post(`${apiBaseUrl}/auth/refresh`, () =>
        HttpResponse.json(tokenPair('rotated')),
      ),
      http.get(`${apiBaseUrl}/auth/me`, () => {
        meCall += 1
        return HttpResponse.json(
          meCall === 1
            ? currentUser('User One')
            : currentUser('Unexpected User', 'user-2'),
        )
      }),
      http.get(`${apiBaseUrl}/auth/capabilities`, () =>
        HttpResponse.json(capabilities(false)),
      ),
    )
    const controller = createAuthController({
      baseUrl: apiBaseUrl,
      queryClient,
      storage: window.sessionStorage,
    })
    await controller.initialize()
    queryClient.setQueryData(['user-1', 'private'], { value: 'private' })
    const activity = new AbortController()
    controller.registerPrivateActivity(activity)

    await controller.reloadIdentitySnapshot()

    expect(controller.getState()).toMatchObject({
      snapshot: null,
      status: 'anonymous',
    })
    expect(activity.signal.aborted).toBe(true)
    expect(queryClient.getQueryData(['user-1', 'private'])).toBeUndefined()
    expect(window.sessionStorage.length).toBe(0)
  })

  it('retains the previous complete snapshot as stale on a transient reload failure', async () => {
    createAuthTokenStore(window.sessionStorage).setTokenPair(tokenPair('stored'))
    let meCall = 0
    server.use(
      http.post(`${apiBaseUrl}/auth/refresh`, () =>
        HttpResponse.json(tokenPair('rotated')),
      ),
      http.get(`${apiBaseUrl}/auth/me`, () => {
        meCall += 1
        if (meCall === 2) {
          return HttpResponse.json(
            { code: 'UPSTREAM_UNAVAILABLE', message: '身份服务暂时不可用' },
            { status: 503 },
          )
        }
        return HttpResponse.json(currentUser('Stable Snapshot'))
      }),
      http.get(`${apiBaseUrl}/auth/capabilities`, () =>
        HttpResponse.json(capabilities(false)),
      ),
    )
    const controller = createAuthController({
      baseUrl: apiBaseUrl,
      queryClient: new QueryClient(),
      storage: window.sessionStorage,
    })
    await controller.initialize()

    await expect(controller.reloadIdentitySnapshot()).rejects.toMatchObject({
      code: 'UPSTREAM_UNAVAILABLE',
      status: 503,
    })
    expect(controller.getState()).toMatchObject({
      error: { code: 'UPSTREAM_UNAVAILABLE', status: 503 },
      snapshot: { currentUser: { displayName: 'Stable Snapshot' } },
      status: 'stale',
    })
  })

  it('logs in and publishes identity without copying bootstrap data into Query Cache', async () => {
    const queryClient = new QueryClient()
    server.use(
      http.post(`${apiBaseUrl}/auth/login`, async ({ request }) => {
        expect(await request.json()).toEqual({
          username_or_email: 'reader@example.com',
          password: 'not-logged-or-persisted',
        })
        return HttpResponse.json(tokenPair('login'))
      }),
      http.get(`${apiBaseUrl}/auth/me`, () =>
        HttpResponse.json(currentUser('Logged In Reader')),
      ),
      http.get(`${apiBaseUrl}/auth/capabilities`, () =>
        HttpResponse.json(capabilities(true)),
      ),
    )
    const controller = createAuthController({
      baseUrl: apiBaseUrl,
      queryClient,
      storage: window.sessionStorage,
    })
    await controller.initialize()
    expect(controller.getState().status).toBe('anonymous')

    await controller.login({
      username_or_email: 'reader@example.com',
      password: 'not-logged-or-persisted',
    })

    expect(controller.getState()).toMatchObject({
      snapshot: { currentUser: { displayName: 'Logged In Reader' } },
      status: 'authenticated',
    })
    expect(queryClient.getQueryCache().getAll()).toHaveLength(0)
    expect(window.sessionStorage.length).toBe(1)
  })

  it('clears the local session after a successful password change', async () => {
    createAuthTokenStore(window.sessionStorage).setTokenPair(tokenPair('stored'))
    const queryClient = new QueryClient()
    let releasePasswordChange: (() => void) | undefined
    const passwordChangeGate = new Promise<void>((resolve) => {
      releasePasswordChange = resolve
    })
    const passwordChangeStarted = vi.fn()
    server.use(
      http.post(`${apiBaseUrl}/auth/refresh`, () =>
        HttpResponse.json(tokenPair('rotated')),
      ),
      http.get(`${apiBaseUrl}/auth/me`, () =>
        HttpResponse.json(currentUser('Password Owner')),
      ),
      http.get(`${apiBaseUrl}/auth/capabilities`, () =>
        HttpResponse.json(capabilities(false)),
      ),
      http.post(`${apiBaseUrl}/auth/change-password`, async ({ request }) => {
        passwordChangeStarted()
        expect(await request.json()).toEqual({
          current_password: 'current-value',
          new_password: 'new-value',
        })
        await passwordChangeGate
        return HttpResponse.json({
          password_changed: true,
          revoked_refresh_token_count: 2,
        })
      }),
    )
    const controller = createAuthController({
      baseUrl: apiBaseUrl,
      queryClient,
      storage: window.sessionStorage,
    })
    await controller.initialize()
    queryClient.setQueryData(['user-1', 'private'], { value: 'private' })
    const activity = new AbortController()
    controller.registerPrivateActivity(activity)

    const change = controller.changePassword({
      current_password: 'current-value',
      new_password: 'new-value',
    })
    await vi.waitFor(() => expect(passwordChangeStarted).toHaveBeenCalledOnce())
    expect(controller.getState().status).toBe('changingPassword')
    releasePasswordChange?.()

    await expect(change).resolves.toEqual({
      passwordChanged: true,
      revokedRefreshTokenCount: 2,
    })
    expect(controller.getState()).toMatchObject({
      snapshot: null,
      status: 'anonymous',
    })
    expect(activity.signal.aborted).toBe(true)
    expect(queryClient.getQueryData(['user-1', 'private'])).toBeUndefined()
    expect(window.sessionStorage.length).toBe(0)
  })
})
