import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'

import { App } from '@/app/App'
import { AuthProvider } from '@/features/auth/AuthProvider'
import { createAuthTokenStore } from '@/features/auth/auth-tokens'
import { server } from '@/test/server'


const apiBaseUrl = 'http://conversation-app.test'

function conversation(sessionId: string, title: string, messageCount = 2) {
  return {
    session_id: sessionId,
    title,
    created_at: '2026-08-26T01:00:00Z',
    updated_at: '2026-08-26T02:00:00Z',
    message_count: messageCount,
    last_message_role: messageCount === 0 ? null : ('assistant' as const),
    last_message_preview: messageCount === 0 ? null : '最近回答',
  }
}

function message(messageId: string, sequenceNo: number, role: 'assistant' | 'user') {
  return {
    message_id: messageId,
    sequence_no: sequenceNo,
    role,
    content: role === 'user' ? '历史问题' : '历史回答',
    sources:
      role === 'assistant'
        ? [
            {
              id: 'source-1',
              source: 'elasticsearch',
              source_type: 'knowledge_document' as const,
              doc_id: 'doc-1',
              href: null,
              title: '来源标题',
              content_preview: '来源预览',
              score: 0.8,
              scores: { rrf_score: 0.8 },
            },
            {
              id: 'source-2',
              source: 'web',
              source_type: 'web' as const,
              doc_id: null,
              href: 'https://example.test/public-result',
              title: 'Web 公开来源',
              content_preview: '公开网页预览',
              score: 0.7,
              scores: {},
            },
            {
              id: 'source-3',
              source: 'web',
              source_type: 'web' as const,
              doc_id: null,
              href: 'javascript:alert(1)',
              title: '不安全来源',
              content_preview: '不安全链接只显示文本',
              score: 0.6,
              scores: {},
            },
          ]
        : [],
    agent_task_plan_id: role === 'assistant' ? 'task-1' : null,
    agent_task_status: role === 'assistant' ? 'waiting_confirmation' : null,
    terminal_status: 'completed' as const,
    created_at: `2026-08-26T03:00:0${sequenceNo}Z`,
  }
}

function installIdentity() {
  createAuthTokenStore(window.sessionStorage).setTokenPair({
    access_token: 'test-access',
    refresh_token: 'test-refresh',
    token_type: 'bearer',
    expires_in: 300,
  })
  server.use(
    http.post(`${apiBaseUrl}/auth/refresh`, () =>
      HttpResponse.json({
        access_token: 'rotated-access',
        refresh_token: 'rotated-refresh',
        token_type: 'bearer',
        expires_in: 300,
      }),
    ),
    http.get(`${apiBaseUrl}/auth/me`, () =>
      HttpResponse.json({
        user_id: 'user-conversations',
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
      }),
    ),
  )
}

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="current-route">{location.pathname}</output>
}

function renderApp(initialEntry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider baseUrl={apiBaseUrl} storage={window.sessionStorage}>
        <MemoryRouter initialEntries={[initialEntry]}>
          <App />
          <LocationProbe />
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('Conversations workspace', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    installIdentity()
  })

  it('restores selected history and appends cursor pages without duplicates', async () => {
    server.use(
      http.get(`${apiBaseUrl}/conversations`, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor')
        return HttpResponse.json(
          cursor === null
            ? {
                items: [
                  conversation('session-a', '会话 A'),
                  conversation('session-b', '会话 B'),
                ],
                next_cursor: 'list-next',
              }
            : {
                items: [
                  conversation('session-b', '重复 B'),
                  conversation('session-c', '会话 C'),
                ],
                next_cursor: null,
              },
        )
      }),
      http.get(`${apiBaseUrl}/conversations/session-a/messages`, () =>
        HttpResponse.json({
          items: [message('message-1', 1, 'user'), message('message-2', 2, 'assistant')],
          next_cursor: null,
        }),
      ),
    )
    const user = userEvent.setup()

    renderApp('/chat/session-a')

    expect(await screen.findByRole('heading', { name: '会话 A' })).toBeInTheDocument()
    expect(screen.getByText('历史问题')).toBeInTheDocument()
    expect(screen.getByText('历史回答')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '来源标题' })).toHaveAttribute(
      'href',
      '/documents/doc-1',
    )
    expect(screen.getByRole('link', { name: 'Web 公开来源' })).toHaveAttribute(
      'href',
      'https://example.test/public-result',
    )
    expect(screen.getByText('不安全来源')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '不安全来源' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看 TaskPlan task-1' })).toHaveAttribute(
      'href',
      '/tasks/task-1',
    )

    await user.click(screen.getByRole('button', { name: '加载更多会话' }))
    const list = screen.getByRole('region', { name: '会话列表' })
    expect(within(list).getAllByRole('link').map((link) => link.textContent)).toEqual([
      '会话 A最近回答',
      '会话 B最近回答',
      '会话 C最近回答',
    ])
  })

  it('creates a conversation and navigates using the returned external session id', async () => {
    let listRequestCount = 0
    server.use(
      http.get(`${apiBaseUrl}/conversations`, () => {
        listRequestCount += 1
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
      http.post(`${apiBaseUrl}/conversations`, async ({ request }) => {
        expect(await request.json()).toEqual({ title: '新建标题' })
        return HttpResponse.json(conversation('session-new', '新建标题', 0), {
          status: 201,
        })
      }),
      http.get(`${apiBaseUrl}/conversations/session-new/messages`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
    )
    const user = userEvent.setup()

    renderApp('/chat')

    await user.click(await screen.findByRole('button', { name: '新建会话' }))
    const dialog = screen.getByRole('dialog', { name: '新建会话' })
    await user.type(within(dialog).getByLabelText('会话标题（可选）'), '新建标题')
    await user.click(within(dialog).getByRole('button', { name: '创建' }))

    expect(await screen.findByLabelText('current-route')).toHaveTextContent(
      '/chat/session-new',
    )
    expect(listRequestCount).toBeGreaterThan(1)
  })

  it('refetches server order after rename and maps a 422 title error to the field', async () => {
    let listRequestCount = 0
    let renameRequestCount = 0
    server.use(
      http.get(`${apiBaseUrl}/conversations`, () => {
        listRequestCount += 1
        return HttpResponse.json({
          items:
            listRequestCount === 1
              ? [conversation('session-a', '会话 A'), conversation('session-b', '会话 B')]
              : [conversation('session-b', '会话 B'), conversation('session-a', '已重命名')],
          next_cursor: null,
        })
      }),
      http.get(`${apiBaseUrl}/conversations/session-a/messages`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.patch(`${apiBaseUrl}/conversations/session-a`, () => {
        renameRequestCount += 1
        if (renameRequestCount === 1) {
          return HttpResponse.json(
            {
              code: 'REQUEST_VALIDATION_ERROR',
              message: '请求参数不合法',
              error_category: 'user_error',
              request_id: 'rename-request',
              trace_id: null,
              field_errors: [
                { field: 'title', code: 'invalid', message: '输入值不合法' },
              ],
            },
            { status: 422 },
          )
        }
        return HttpResponse.json(conversation('session-a', '已重命名'))
      }),
    )
    const user = userEvent.setup()

    renderApp('/chat/session-a')
    await screen.findByRole('heading', { name: '会话 A' })
    await user.click(screen.getByRole('button', { name: '重命名当前会话' }))
    let dialog = screen.getByRole('dialog', { name: '重命名会话' })
    const input = within(dialog).getByLabelText('新标题')
    await user.clear(input)
    await user.type(input, '已重命名')
    await user.click(within(dialog).getByRole('button', { name: '保存' }))
    expect(await within(dialog).findByText('输入值不合法')).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: '保存' }))
    expect(await screen.findByRole('heading', { name: '已重命名' })).toBeInTheDocument()
    const list = screen.getByRole('region', { name: '会话列表' })
    expect(within(list).getAllByRole('link').map((link) => link.textContent)).toEqual([
      '会话 B最近回答',
      '已重命名最近回答',
    ])
  })

  it('keeps the rename dialog open and shows a safe form-level failure', async () => {
    server.use(
      http.get(`${apiBaseUrl}/conversations`, () =>
        HttpResponse.json({
          items: [conversation('session-a', '会话 A')],
          next_cursor: null,
        }),
      ),
      http.get(`${apiBaseUrl}/conversations/session-a/messages`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.patch(`${apiBaseUrl}/conversations/session-a`, () =>
        HttpResponse.json(
          {
            code: 'CONVERSATION_UPDATE_FAILED',
            message: 'unsafe backend detail',
            error_category: 'server_error',
            request_id: 'rename-form-request',
            trace_id: null,
          },
          { status: 503 },
        ),
      ),
    )
    const user = userEvent.setup()

    renderApp('/chat/session-a')
    await screen.findByRole('heading', { name: '会话 A' })
    await user.click(screen.getByRole('button', { name: '重命名当前会话' }))
    const dialog = screen.getByRole('dialog', { name: '重命名会话' })
    await user.click(within(dialog).getByRole('button', { name: '保存' }))

    expect(
      await within(dialog).findByRole('heading', { name: '重命名会话失败' }),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('请求 ID：rename-form-request')).toBeInTheDocument()
    expect(within(dialog).queryByText('unsafe backend detail')).not.toBeInTheDocument()
  })

  it('requires delete confirmation and shows a safe unavailable state for hidden history', async () => {
    let deleted = false
    server.use(
      http.get(`${apiBaseUrl}/conversations`, () =>
        HttpResponse.json({
          items: deleted ? [] : [conversation('session-a', '会话 A')],
          next_cursor: null,
        }),
      ),
      http.get(`${apiBaseUrl}/conversations/session-a/messages`, () =>
        HttpResponse.json(
          {
            code: 'CONVERSATION_NOT_FOUND',
            message: 'not exposed',
            error_category: 'user_error',
            request_id: 'hidden-request',
            trace_id: null,
          },
          { status: 404 },
        ),
      ),
      http.delete(`${apiBaseUrl}/conversations/session-a`, () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const user = userEvent.setup()

    renderApp('/chat/session-a')

    expect(await screen.findByRole('heading', { name: '会话不可用' })).toBeInTheDocument()
    expect(screen.queryByText('not exposed')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '删除当前会话' }))
    const dialog = screen.getByRole('dialog', { name: '删除会话' })
    await user.click(within(dialog).getByRole('button', { name: '确认删除' }))

    expect(await screen.findByLabelText('current-route')).toHaveTextContent('/chat')
    expect(screen.queryByText('会话 A')).not.toBeInTheDocument()
  })
})
