import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { MemoryRouter } from 'react-router-dom'

import { App } from '@/app/App'
import { AuthProvider } from '@/features/auth/AuthProvider'
import { createAuthTokenStore } from '@/features/auth/auth-tokens'
import { server } from '@/test/server'


const apiBaseUrl = 'http://task-plan-app.test'

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
        user_id: 'user-task-plans',
        username: 'planner',
        account_type: 'employee',
        is_authenticated: true,
        auth_source: 'jwt',
        global_role_codes: [],
        global_permission_codes: [],
        department_permission_codes: {},
        department_codes: ['dept-a'],
        primary_department_code: 'dept-a',
        email: null,
        display_name: 'Planner',
        token_id: null,
        api_key_id: null,
      }),
    ),
    http.get(`${apiBaseUrl}/auth/capabilities`, () =>
      HttpResponse.json({
        can_manage_users: false,
        user_management_scope: 'none',
        can_manage_document_grants: false,
        can_use_web_search: true,
        can_use_nl2sql: false,
        can_read_documents: false,
        can_manage_documents: false,
      }),
    ),
  )
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
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('TaskPlan workspace', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    installIdentity()
  })

  it('loads filtered summaries and preserves server order', async () => {
    server.use(
      http.get(`${apiBaseUrl}/agent/task-plans`, ({ request }) => {
        const search = new URL(request.url).searchParams
        expect(search.get('status')).toBe('waiting_confirmation')
        expect(search.get('session_id')).toBe('session-a')
        return HttpResponse.json({
          items: [
            {
              task_plan_id: 'research-1',
              task_kind: 'question_decomposition',
              status: 'waiting_confirmation',
              session_id: 'session-a',
              summary: '研究公开方案',
              requires_confirmation: true,
              error_code: null,
              created_at: '2026-08-29T01:00:00Z',
              updated_at: '2026-08-29T02:00:00Z',
            },
            {
              task_plan_id: 'document-1',
              task_kind: 'knowledge_document_management',
              status: 'completed',
              session_id: 'session-a',
              summary: '生成公开报告',
              requires_confirmation: false,
              error_code: null,
              created_at: '2026-08-29T00:00:00Z',
              updated_at: '2026-08-29T03:00:00Z',
            },
          ],
          next_cursor: null,
        })
      }),
    )

    renderApp('/tasks?status=waiting_confirmation&session_id=session-a')

    expect(
      await screen.findByRole('heading', { level: 2, name: 'TaskPlan' }),
    ).toBeVisible()
    const links = await screen.findAllByRole('link', { name: /研究公开方案|生成公开报告/ })
    expect(links.map((link) => link.textContent)).toEqual([
      expect.stringContaining('研究公开方案'),
      expect.stringContaining('生成公开报告'),
    ])
  })

  it('renders research detail and sanitized review Markdown', async () => {
    server.use(
      http.get(`${apiBaseUrl}/agent/task-plans`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(`${apiBaseUrl}/agent/task-plans/research-1`, () =>
        HttpResponse.json({
          task_kind: 'question_decomposition',
          task_plan_id: 'research-1',
          schema_version: 2,
          status: 'waiting_confirmation',
          session_id: 'session-a',
          task_type: 'analysis',
          source_query: '比较公开方案',
          objective: '形成有证据的结论',
          requirements: [],
          sub_questions: [],
          final_synthesis_instruction: '仅使用有效证据',
          capability_snapshot: {
            available_source_types: ['knowledge_retrieval'],
            knowledge_retrieval_available: true,
            nl2sql_query_available: false,
            web_direct_allowed: false,
            web_fallback_allowed: false,
          },
          quality_review: {
            verdict: 'accepted',
            checks: {
              semantic_alignment: 'pass',
              requirement_coverage: 'pass',
              source_alignment: 'pass',
              dependency_quality: 'pass',
              executability: 'pass',
              completion_policy_alignment: 'pass',
            },
            revision_count: 0,
          },
          validation_issues: [],
          progress: { current_wave: 0, events: [], workers: {} },
          sub_question_results: [],
          evidence: [],
          requirement_evidence_statuses: [],
          final_output: null,
          error_code: null,
          error_message: null,
          created_at: '2026-08-29T01:00:00Z',
          updated_at: '2026-08-29T02:00:00Z',
        }),
      ),
      http.get(`${apiBaseUrl}/agent/task-plans/research-1/markdown`, () =>
        HttpResponse.text('# 审查计划\n\n<script>must-not-render</script>'),
      ),
    )

    const view = renderApp('/tasks/research-1')

    expect(await screen.findByRole('heading', { name: '形成有证据的结论' })).toBeVisible()
    expect(screen.getByText('等待确认')).toBeVisible()
    expect(await screen.findByRole('heading', { name: '审查计划' })).toBeVisible()
    expect(view.container.querySelector('script')).toBeNull()
  })
})
