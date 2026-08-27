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
            {
              id: 'source-4',
              source: 'web',
              source_type: 'web' as const,
              doc_id: null,
              href: 'https://user:password@example.test/private',
              title: '带凭据来源',
              content_preview: '凭据 URL 只显示文本',
              score: 0.5,
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

function installIdentity(canUseWebSearch = false) {
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
        can_use_web_search: canUseWebSearch,
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
    expect(screen.getByText('带凭据来源')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '带凭据来源' })).not.toBeInTheDocument()
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

  it('streams a Chat turn through the structured route and refetches persisted history', async () => {
    let listRequestCount = 0
    let messageRequestCount = 0
    let streamRequestCount = 0
    server.use(
      http.get(`${apiBaseUrl}/conversations`, () => {
        listRequestCount += 1
        return HttpResponse.json({
          items: [conversation('session-a', '会话 A', messageRequestCount > 0 ? 2 : 0)],
          next_cursor: null,
        })
      }),
      http.get(`${apiBaseUrl}/conversations/session-a/messages`, () => {
        messageRequestCount += 1
        return HttpResponse.json(
          messageRequestCount === 1
            ? { items: [], next_cursor: null }
            : {
                items: [
                  { ...message('message-3', 3, 'user'), content: '新的问题' },
                  {
                    ...message('message-4', 4, 'assistant'),
                    content: '**服务端持久化回答**',
                    sources: [],
                  },
                ],
                next_cursor: null,
              },
        )
      }),
      http.post(`${apiBaseUrl}/rag/chat/stream/events`, async ({ request }) => {
        streamRequestCount += 1
        const requestId = request.headers.get('X-Request-ID')
        expect(requestId).toBeTruthy()
        expect(await request.json()).toEqual({
          allow_direct_web: false,
          allow_web_fallback: false,
          min_score: 0,
          mode: 'hybrid',
          query: '新的问题',
          session_id: 'session-a',
          top_k: 5,
        })
        return new HttpResponse(
          'event: answer_delta\n' +
            `data: {"contract_version":"1.0","request_id":"${requestId}","text":"流式回答"}\n\n` +
            'event: done\n' +
            `data: {"contract_version":"1.0","request_id":"${requestId}","status":"done"}\n\n`,
          {
            headers: {
              'Content-Type': 'text/event-stream; charset=utf-8',
              'X-Request-ID': requestId ?? '',
            },
          },
        )
      }),
    )
    const user = userEvent.setup()

    renderApp('/chat/session-a')
    await screen.findByRole('heading', { name: '会话 A' })
    await user.type(screen.getByLabelText('问题'), '新的问题')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect((await screen.findByText('服务端持久化回答')).tagName).toBe('STRONG')
    expect(streamRequestCount).toBe(1)
    expect(messageRequestCount).toBeGreaterThan(1)
    expect(listRequestCount).toBeGreaterThan(1)
  })

  it('restores capable-user Web settings and sends both explicit request fields', async () => {
    installIdentity(true)
    let receivedBody: unknown
    server.use(
      http.get(`${apiBaseUrl}/conversations`, () =>
        HttpResponse.json({
          items: [conversation('session-a', '会话 A', 0)],
          next_cursor: null,
        }),
      ),
      http.get(`${apiBaseUrl}/conversations/session-a/messages`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.post(`${apiBaseUrl}/rag/chat/stream/events`, async ({ request }) => {
        receivedBody = await request.json()
        const requestId = request.headers.get('X-Request-ID')
        return new HttpResponse(
          'event: done\n' +
            `data: {"contract_version":"1.0","request_id":"${requestId}","status":"done"}\n\n`,
          {
            headers: {
              'Content-Type': 'text/event-stream',
              'X-Request-ID': requestId ?? '',
            },
          },
        )
      }),
    )
    const user = userEvent.setup()
    const firstRender = renderApp('/chat/session-a')

    await screen.findByRole('heading', { name: '会话 A' })
    await user.click(screen.getByLabelText('允许联网搜索'))
    await user.click(screen.getByLabelText('本地证据不足时允许 Web 补充'))
    firstRender.unmount()

    renderApp('/chat/session-a')
    expect(await screen.findByLabelText('允许联网搜索')).toBeChecked()
    expect(screen.getByLabelText('本地证据不足时允许 Web 补充')).toBeChecked()
    await user.type(screen.getByLabelText('问题'), '需要公开信息')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(await screen.findByText('状态：completed')).toBeInTheDocument()
    expect(receivedBody).toMatchObject({
      allow_direct_web: true,
      allow_web_fallback: true,
      query: '需要公开信息',
    })
  })

  it('maps a pre-stream 422 query error to the composer without exposing form detail', async () => {
    server.use(
      http.get(`${apiBaseUrl}/conversations`, () =>
        HttpResponse.json({
          items: [conversation('session-a', '会话 A', 0)],
          next_cursor: null,
        }),
      ),
      http.get(`${apiBaseUrl}/conversations/session-a/messages`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.post(`${apiBaseUrl}/rag/chat/stream/events`, () =>
        HttpResponse.json(
          {
            code: 'REQUEST_VALIDATION_ERROR',
            error_category: 'user_error',
            field_errors: [
              { code: 'invalid', field: 'query', message: '问题格式不合法' },
            ],
            message: '不应直接显示的表单详情',
            request_id: 'chat-validation-request',
            trace_id: null,
          },
          { status: 422 },
        ),
      ),
    )
    const user = userEvent.setup()

    renderApp('/chat/session-a')
    await screen.findByRole('heading', { name: '会话 A' })
    await user.type(screen.getByLabelText('问题'), '服务端拒绝')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(await screen.findByText('问题格式不合法')).toBeInTheDocument()
    expect(screen.getByLabelText('问题')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.queryByText('不应直接显示的表单详情')).not.toBeInTheDocument()
    expect(screen.getByText('状态：failed')).toBeInTheDocument()
  })

  it('renders safe structured events, sources, clarification and TaskPlan references', async () => {
    server.use(
      http.get(`${apiBaseUrl}/conversations`, () =>
        HttpResponse.json({
          items: [conversation('session-a', '会话 A', 0)],
          next_cursor: null,
        }),
      ),
      http.get(`${apiBaseUrl}/conversations/session-a/messages`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.post(`${apiBaseUrl}/rag/chat/stream/events`, ({ request }) => {
        const requestId = request.headers.get('X-Request-ID')
        const envelope = `"contract_version":"1.0","request_id":"${requestId}"`
        return new HttpResponse(
          'event: agent_route_selected\n' +
            `data: {${envelope},"intent":"research","confidence":0.9,"reason":"public","source":"router"}\n\n` +
            'event: guard_sanitized\n' +
            `data: {${envelope},"action":"sanitize","categories":["prompt"],"reason":"policy","risk_level":"low","text":"已净化"}\n\n` +
            'event: agent_route_clarification_required\n' +
            `data: {${envelope},"code":"NEED_SCOPE","confidence":0.4,"question":"请说明时间范围"}\n\n` +
            'event: agent_task_plan_created\n' +
            `data: {${envelope},"task_plan_id":"task-1","status":"pending"}\n\n` +
            'event: sources\n' +
            `data: {${envelope},"sources":[` +
            '{"id":"doc-source","source":"elasticsearch","source_type":"knowledge_document","doc_id":"doc-1","href":null,"title":"知识来源","content_preview":"文档预览","score":0.8,"source_revision":"rev-1","section_path":["章节"]},' +
            '{"id":"web-source","source":"web","source_type":"web","doc_id":null,"href":"https://example.test/result","title":"公开网页","content_preview":"**网页预览**","score":0.7,"source_revision":null,"section_path":[]},' +
            '{"id":"unsafe-source","source":"web","source_type":"web","doc_id":null,"href":"https://user:password@example.test/private","title":"不安全网页","content_preview":"只显示文本","score":0.6,"source_revision":null,"section_path":[]}' +
            ']}\n\n' +
            'event: future_private_event\n' +
            `data: {${envelope},"secret":"must-not-render"}\n\n` +
            'event: done\n' +
            `data: {${envelope},"status":"done","stale":true}\n\n`,
          {
            headers: {
              'Content-Type': 'text/event-stream',
              'X-Request-ID': requestId ?? '',
            },
          },
        )
      }),
    )
    const user = userEvent.setup()

    renderApp('/chat/session-a')
    await screen.findByRole('heading', { name: '会话 A' })
    await user.type(screen.getByLabelText('问题'), '复杂任务')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(await screen.findByText('请说明时间范围')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '查看 TaskPlan task-1' })).toHaveAttribute(
      'href',
      '/tasks/task-1',
    )
    expect(screen.getByRole('link', { name: '知识来源' })).toHaveAttribute(
      'href',
      '/documents/doc-1',
    )
    expect(screen.getByRole('link', { name: '公开网页' })).toHaveAttribute(
      'href',
      'https://example.test/result',
    )
    expect(screen.getByText('网页预览').tagName).toBe('STRONG')
    expect(screen.getByText('不安全网页')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: '不安全网页' })).not.toBeInTheDocument()
    expect(screen.getByText('当前前端版本暂不支持 future_private_event')).toBeInTheDocument()
    expect(screen.queryByText('must-not-render')).not.toBeInTheDocument()
    expect(screen.getByText('知识已在生成期间更新，可以重新提问。')).toBeInTheDocument()
  })

  it('disables duplicate sends, aborts browser reading and refetches after cancellation', async () => {
    let listRequestCount = 0
    let messageRequestCount = 0
    server.use(
      http.get(`${apiBaseUrl}/conversations`, () => {
        listRequestCount += 1
        return HttpResponse.json({
          items: [conversation('session-a', '会话 A', 0)],
          next_cursor: null,
        })
      }),
      http.get(`${apiBaseUrl}/conversations/session-a/messages`, () => {
        messageRequestCount += 1
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
      http.post(`${apiBaseUrl}/rag/chat/stream/events`, ({ request }) => {
        const requestId = request.headers.get('X-Request-ID')
        const body = new ReadableStream({
          start(controller) {
            controller.enqueue(
              new TextEncoder().encode(
                'event: answer_delta\n' +
                  `data: {"contract_version":"1.0","request_id":"${requestId}","text":"部分回答"}\n\n`,
              ),
            )
            request.signal.addEventListener('abort', () => {
              controller.error(new DOMException('Aborted', 'AbortError'))
            })
          },
        })
        return new HttpResponse(body, {
          headers: {
            'Content-Type': 'text/event-stream',
            'X-Request-ID': requestId ?? '',
          },
        })
      }),
    )
    const user = userEvent.setup()

    renderApp('/chat/session-a')
    await screen.findByRole('heading', { name: '会话 A' })
    await user.type(screen.getByLabelText('问题'), '可取消问题')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(await screen.findByText('部分回答')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '发送' })).toBeDisabled()
    await user.click(screen.getByRole('button', { name: '停止读取' }))

    expect(await screen.findByText('状态：cancelled')).toBeInTheDocument()
    expect(messageRequestCount).toBeGreaterThan(1)
    expect(listRequestCount).toBeGreaterThan(1)
  })

  it('marks terminal-free EOF interrupted, does not replay POST and refetches history', async () => {
    let streamRequestCount = 0
    let messageRequestCount = 0
    server.use(
      http.get(`${apiBaseUrl}/conversations`, () =>
        HttpResponse.json({
          items: [conversation('session-a', '会话 A', 0)],
          next_cursor: null,
        }),
      ),
      http.get(`${apiBaseUrl}/conversations/session-a/messages`, () => {
        messageRequestCount += 1
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
      http.post(`${apiBaseUrl}/rag/chat/stream/events`, ({ request }) => {
        streamRequestCount += 1
        const requestId = request.headers.get('X-Request-ID')
        return new HttpResponse(
          'event: answer_delta\n' +
            `data: {"contract_version":"1.0","request_id":"${requestId}","text":"未完成回答"}\n\n`,
          {
            headers: {
              'Content-Type': 'text/event-stream',
              'X-Request-ID': requestId ?? '',
            },
          },
        )
      }),
    )
    const user = userEvent.setup()

    renderApp('/chat/session-a')
    await screen.findByRole('heading', { name: '会话 A' })
    await user.type(screen.getByLabelText('问题'), '中断问题')
    await user.click(screen.getByRole('button', { name: '发送' }))

    expect(await screen.findByText('状态：interrupted')).toBeInTheDocument()
    expect(screen.getByText('未完成回答')).toBeInTheDocument()
    expect(streamRequestCount).toBe(1)
    expect(messageRequestCount).toBeGreaterThan(1)
  })
})
