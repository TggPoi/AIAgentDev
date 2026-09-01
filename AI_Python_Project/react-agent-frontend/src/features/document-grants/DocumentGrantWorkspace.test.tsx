import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'

import { createHttpClient } from '@/api/http-client'
import { createDocumentGrantApi } from '@/features/document-grants/document-grant-api'
import { DocumentGrantWorkspace } from '@/features/document-grants/DocumentGrantWorkspace'
import { server } from '@/test/server'


const apiBaseUrl = 'http://document-grant-workspace.test'

function grantDto(
  grantId: string,
  documentId: string,
  status: 'active' | 'revoked' = 'active',
) {
  return {
    document_department_code: 'development',
    document_id: documentId,
    grant_id: grantId,
    granted_at: '2026-09-01T01:00:00Z',
    granted_by_user_id: 'manager-1',
    grantee: {
      display_name: 'Reader',
      primary_department_code: 'operations',
      user_id: 'reader-1',
      username: 'reader',
    },
    repository_path: `docs/${documentId}.md`,
    revoked_at: status === 'revoked' ? '2026-09-01T02:00:00Z' : null,
    revoked_by_user_id: status === 'revoked' ? 'manager-2' : null,
    status,
  }
}

function renderWorkspace(initialEntry = '/admin/document-grants') {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const api = createDocumentGrantApi(
    createHttpClient({
      baseUrl: apiBaseUrl,
      getAccessToken: () => null,
      requestIdFactory: () => 'document-grant-workspace-request',
    }),
  )
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <DocumentGrantWorkspace api={api} userBoundary="manager-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('DocumentGrantWorkspace read-only list', () => {
  it('loads an opaque next page and retains revoked audit facts', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor')
        return cursor === null
          ? HttpResponse.json({
              items: [grantDto('grant-1', 'doc-1')],
              next_cursor: 'opaque+/=',
            })
          : HttpResponse.json({
              items: [grantDto('grant-2', 'doc-2', 'revoked')],
              next_cursor: null,
            })
      }),
    )
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(
      await screen.findByRole('button', { name: '加载更多授权' }),
    )

    const list = await screen.findByRole('list', { name: '文档授权列表' })
    await waitFor(() =>
      expect(within(list).getAllByRole('listitem')).toHaveLength(2),
    )
    expect(list).toHaveTextContent('docs/doc-2.md')
    expect(list).toHaveTextContent('已撤销')
    expect(list).toHaveTextContent('撤销人：manager-2')
    expect(list).toHaveTextContent('撤销时间：2026-09-01T02:00:00Z')
  })

  it('maps safe field errors without rendering the backend top-level message', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json(
          {
            code: 'REQUEST_VALIDATION_ERROR',
            error_category: 'request_validation',
            field_errors: [
              {
                code: 'invalid',
                field: 'target_account',
                message: '请输入精确目标账号',
              },
            ],
            message: 'raw-top-level-marker',
            request_id: 'grant-validation-request',
            trace_id: null,
          },
          { status: 422 },
        ),
      ),
    )
    renderWorkspace('/admin/document-grants?target_account=reader')

    expect(await screen.findByText('请输入精确目标账号')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '目标账号' })).toHaveAttribute(
      'aria-invalid',
      'true',
    )
    expect(screen.queryByText('raw-top-level-marker')).not.toBeInTheDocument()
  })

  it('shows a fixed safe error state and an empty result state', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json(
          {
            code: 'GRANT_LIST_FAILED',
            message: 'raw-server-marker',
            request_id: 'grant-list-request',
          },
          { status: 500 },
        ),
      ),
    )
    const first = renderWorkspace()

    expect(
      await screen.findByRole('region', { name: '文档授权列表加载失败' }),
    ).toHaveTextContent('GRANT_LIST_FAILED')
    expect(screen.queryByText('raw-server-marker')).not.toBeInTheDocument()

    first.unmount()
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
    )
    renderWorkspace()

    expect(
      await screen.findByRole('region', { name: '暂无授权记录' }),
    ).toBeInTheDocument()
  })
})
