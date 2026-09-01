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

function renderWorkspace(
  initialEntry = '/admin/document-grants',
  canFilterGrantableDepartment = false,
) {
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
        <DocumentGrantWorkspace
          api={api}
          canFilterGrantableDepartment={canFilterGrantableDepartment}
          userBoundary="manager-1"
        />
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

describe('DocumentGrantWorkspace create flow', () => {
  it('selects only server catalog documents, reviews the snapshot, and shows counts', async () => {
    let receivedBody: unknown
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(
        `${apiBaseUrl}/admin/document-access/grantable-documents`,
        ({ request }) => {
          const url = new URL(request.url)
          const query = url.searchParams.get('query')
          const departmentCode = url.searchParams.get('department_code')
          if (query !== 'runbook' || departmentCode !== 'development') {
            return HttpResponse.json({ items: [], next_cursor: null })
          }
          expect(query).toBe('runbook')
          expect(departmentCode).toBe('development')
          return HttpResponse.json({
            items: [
              {
                doc_id: 'doc-1',
                document_department_code: 'development',
                document_type: 'markdown',
                repository_path: 'docs/doc-1.md',
                title: 'Runbook',
              },
            ],
            next_cursor: null,
          })
        },
      ),
      http.post(
        `${apiBaseUrl}/admin/document-access/grants`,
        async ({ request }) => {
          receivedBody = await request.json()
          return HttpResponse.json({
            created_count: 1,
            existing_count: 0,
            items: [grantDto('grant-1', 'doc-1')],
          })
        },
      ),
    )
    const user = userEvent.setup()
    renderWorkspace('/admin/document-grants', true)

    await user.click(screen.getByRole('button', { name: '创建授权' }))
    const dialog = screen.getByRole('dialog', { name: '创建文档授权' })
    expect(
      within(dialog).queryByRole('textbox', { name: '文档 ID' }),
    ).not.toBeInTheDocument()
    await user.type(
      within(dialog).getByRole('textbox', { name: '精确目标账号' }),
      'Reader@Example.com',
    )
    await user.type(
      within(dialog).getByRole('textbox', { name: '筛选可授权文档' }),
      'runbook',
    )
    await user.type(
      within(dialog).getByRole('textbox', { name: '筛选文档部门' }),
      'development',
    )
    await user.click(await within(dialog).findByRole('checkbox', { name: /Runbook/ }))
    await user.click(within(dialog).getByRole('button', { name: '审查授权' }))

    expect(receivedBody).toBeUndefined()
    expect(within(dialog).getByText(/目标账号：/)).toHaveTextContent(
      '目标账号：reader@example.com',
    )
    expect(within(dialog).getByText('docs/doc-1.md')).toBeInTheDocument()
    await user.click(
      within(dialog).getByRole('button', { name: '确认创建授权' }),
    )

    await waitFor(() =>
      expect(receivedBody).toEqual({
        document_ids: ['doc-1'],
        target_account: 'reader@example.com',
      }),
    )
    expect(
      await screen.findByRole('status', { name: '文档授权创建结果' }),
    ).toHaveTextContent('新建 1 条，已存在 0 条')
    expect(
      screen.queryByRole('dialog', { name: '创建文档授权' }),
    ).not.toBeInTheDocument()
  })

  it('keeps manager selections across opaque catalog pages without a department filter', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(
        `${apiBaseUrl}/admin/document-access/grantable-documents`,
        ({ request }) => {
          const url = new URL(request.url)
          expect(url.searchParams.has('department_code')).toBe(false)
          const cursor = url.searchParams.get('cursor')
          return cursor === null
            ? HttpResponse.json({
                items: [
                  {
                    doc_id: 'doc-page-1',
                    document_department_code: 'development',
                    document_type: 'markdown',
                    repository_path: 'docs/page-1.md',
                    title: 'First page document',
                  },
                ],
                next_cursor: 'opaque+/=',
              })
            : HttpResponse.json({
                items: [
                  {
                    doc_id: 'doc-page-2',
                    document_department_code: 'development',
                    document_type: 'markdown',
                    repository_path: 'docs/page-2.md',
                    title: 'Second page document',
                  },
                ],
                next_cursor: null,
              })
        },
      ),
    )
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(screen.getByRole('button', { name: '创建授权' }))
    const dialog = screen.getByRole('dialog', { name: '创建文档授权' })
    expect(
      within(dialog).queryByRole('textbox', { name: '筛选文档部门' }),
    ).not.toBeInTheDocument()
    await user.type(
      within(dialog).getByRole('textbox', { name: '精确目标账号' }),
      'reader@example.com',
    )
    await user.click(
      await within(dialog).findByRole('checkbox', {
        name: /First page document/,
      }),
    )
    await user.click(
      within(dialog).getByRole('button', { name: '加载更多可授权文档' }),
    )
    await user.click(
      await within(dialog).findByRole('checkbox', {
        name: /Second page document/,
      }),
    )
    await user.click(within(dialog).getByRole('button', { name: '审查授权' }))

    expect(within(dialog).getByRole('list', { name: '待授权文档' })).toHaveTextContent(
      'First page document',
    )
    expect(within(dialog).getByRole('list', { name: '待授权文档' })).toHaveTextContent(
      'Second page document',
    )
  })

  it('locks close, edit, and duplicate submit while create is pending', async () => {
    let requestCount = 0
    let releaseRequest: (() => void) | undefined
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(
        `${apiBaseUrl}/admin/document-access/grantable-documents`,
        () =>
          HttpResponse.json({
            items: [
              {
                doc_id: 'doc-pending',
                document_department_code: 'development',
                document_type: 'markdown',
                repository_path: 'docs/pending.md',
                title: 'Pending document',
              },
            ],
            next_cursor: null,
          }),
      ),
      http.post(`${apiBaseUrl}/admin/document-access/grants`, async () => {
        requestCount += 1
        await new Promise<void>((resolve) => {
          releaseRequest = resolve
        })
        return HttpResponse.json({
          created_count: 1,
          existing_count: 0,
          items: [grantDto('grant-pending', 'doc-pending')],
        })
      }),
    )
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(screen.getByRole('button', { name: '创建授权' }))
    const dialog = screen.getByRole('dialog', { name: '创建文档授权' })
    await user.type(
      within(dialog).getByRole('textbox', { name: '精确目标账号' }),
      'reader@example.com',
    )
    await user.click(
      await within(dialog).findByRole('checkbox', {
        name: /Pending document/,
      }),
    )
    await user.click(within(dialog).getByRole('button', { name: '审查授权' }))
    await user.click(
      within(dialog).getByRole('button', { name: '确认创建授权' }),
    )

    expect(
      await within(dialog).findByRole('button', { name: '正在创建…' }),
    ).toBeDisabled()
    expect(
      within(dialog).getByRole('button', { name: '返回修改' }),
    ).toBeDisabled()
    await user.click(
      within(dialog).getByRole('button', { name: '关闭创建文档授权' }),
    )
    expect(
      screen.getByRole('dialog', { name: '创建文档授权' }),
    ).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(
      screen.getByRole('dialog', { name: '创建文档授权' }),
    ).toBeInTheDocument()
    expect(requestCount).toBe(1)

    releaseRequest?.()
    expect(
      await screen.findByRole('status', { name: '文档授权创建结果' }),
    ).toHaveTextContent('新建 1 条，已存在 0 条')
  })

  it('preserves selection and refetches the catalog after a safe document error', async () => {
    let catalogRequestCount = 0
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(
        `${apiBaseUrl}/admin/document-access/grantable-documents`,
        () => {
          catalogRequestCount += 1
          return HttpResponse.json({
            items: [
              {
                doc_id: 'doc-stale',
                document_department_code: 'development',
                document_type: 'markdown',
                repository_path: 'docs/stale.md',
                title: 'Stale selection',
              },
            ],
            next_cursor: null,
          })
        },
      ),
      http.post(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json(
          {
            code: 'DOCUMENT_ACCESS_GRANT_INVALID',
            error_category: 'user_error',
            field_errors: [
              {
                code: 'invalid',
                field: 'document_ids',
                message: '所选文档已不可授权，请重新检查',
              },
            ],
            message: 'raw-create-marker',
            request_id: 'grant-create-validation',
            trace_id: null,
          },
          { status: 422 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(screen.getByRole('button', { name: '创建授权' }))
    const dialog = screen.getByRole('dialog', { name: '创建文档授权' })
    await user.type(
      within(dialog).getByRole('textbox', { name: '精确目标账号' }),
      'reader@example.com',
    )
    const selectedDocument = await within(dialog).findByRole('checkbox', {
      name: /Stale selection/,
    })
    await user.click(selectedDocument)
    await user.click(within(dialog).getByRole('button', { name: '审查授权' }))
    await user.click(
      within(dialog).getByRole('button', { name: '确认创建授权' }),
    )

    expect(
      await within(dialog).findByText('所选文档已不可授权，请重新检查'),
    ).toBeInTheDocument()
    expect(within(dialog).queryByText('raw-create-marker')).not.toBeInTheDocument()
    expect(
      within(dialog).getByRole('checkbox', { name: /Stale selection/ }),
    ).toBeChecked()
    expect(
      within(dialog).getByRole('textbox', { name: '精确目标账号' }),
    ).toHaveValue('reader@example.com')
    await waitFor(() => expect(catalogRequestCount).toBe(2))
  })

  it('maps a safe target account error without refetching the document catalog', async () => {
    let catalogRequestCount = 0
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(
        `${apiBaseUrl}/admin/document-access/grantable-documents`,
        () => {
          catalogRequestCount += 1
          return HttpResponse.json({
            items: [
              {
                doc_id: 'doc-account',
                document_department_code: 'development',
                document_type: 'markdown',
                repository_path: 'docs/account.md',
                title: 'Account validation document',
              },
            ],
            next_cursor: null,
          })
        },
      ),
      http.post(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json(
          {
            code: 'REQUEST_VALIDATION_ERROR',
            error_category: 'request_validation',
            field_errors: [
              {
                code: 'invalid',
                field: 'target_account',
                message: '请输入有效的精确目标账号',
              },
            ],
            message: 'raw-account-marker',
            request_id: 'grant-account-validation',
            trace_id: null,
          },
          { status: 422 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(screen.getByRole('button', { name: '创建授权' }))
    const dialog = screen.getByRole('dialog', { name: '创建文档授权' })
    await user.type(
      within(dialog).getByRole('textbox', { name: '精确目标账号' }),
      'reader@example.com',
    )
    await user.click(
      await within(dialog).findByRole('checkbox', {
        name: /Account validation document/,
      }),
    )
    await user.click(within(dialog).getByRole('button', { name: '审查授权' }))
    await user.click(
      within(dialog).getByRole('button', { name: '确认创建授权' }),
    )

    expect(
      await within(dialog).findByText('请输入有效的精确目标账号'),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByRole('textbox', { name: '精确目标账号' }),
    ).toHaveAttribute('aria-invalid', 'true')
    expect(within(dialog).queryByText('raw-account-marker')).not.toBeInTheDocument()
    expect(catalogRequestCount).toBe(1)
  })

  it('maps safe grantable catalog filter errors without rendering raw messages', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(
        `${apiBaseUrl}/admin/document-access/grantable-documents`,
        () =>
          HttpResponse.json(
            {
              code: 'REQUEST_VALIDATION_ERROR',
              error_category: 'request_validation',
              field_errors: [
                {
                  code: 'invalid',
                  field: 'query',
                  message: '文档筛选词过长',
                },
                {
                  code: 'invalid',
                  field: 'department_code',
                  message: '文档部门格式无效',
                },
              ],
              message: 'raw-catalog-marker',
              request_id: 'grantable-validation',
              trace_id: null,
            },
            { status: 422 },
          ),
      ),
    )
    const user = userEvent.setup()
    renderWorkspace('/admin/document-grants', true)

    await user.click(screen.getByRole('button', { name: '创建授权' }))
    const dialog = screen.getByRole('dialog', { name: '创建文档授权' })
    expect(await within(dialog).findByText('文档筛选词过长')).toBeInTheDocument()
    expect(within(dialog).getByText('文档部门格式无效')).toBeInTheDocument()
    expect(
      within(dialog).getByRole('textbox', { name: '筛选可授权文档' }),
    ).toHaveAttribute('aria-invalid', 'true')
    expect(
      within(dialog).getByRole('textbox', { name: '筛选文档部门' }),
    ).toHaveAttribute('aria-invalid', 'true')
    expect(within(dialog).queryByText('raw-catalog-marker')).not.toBeInTheDocument()
  })

  it('shows a safe create conflict on the review step and refetches grants', async () => {
    let grantListRequestCount = 0
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, () => {
        grantListRequestCount += 1
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
      http.get(
        `${apiBaseUrl}/admin/document-access/grantable-documents`,
        () =>
          HttpResponse.json({
            items: [
              {
                doc_id: 'doc-conflict',
                document_department_code: 'development',
                document_type: 'markdown',
                repository_path: 'docs/conflict.md',
                title: 'Conflict document',
              },
            ],
            next_cursor: null,
          }),
      ),
      http.post(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json(
          {
            code: 'DOCUMENT_ACCESS_GRANT_CONFLICT',
            message: 'raw-conflict-marker',
            request_id: 'grant-create-conflict',
          },
          { status: 409 },
        ),
      ),
    )
    const user = userEvent.setup()
    renderWorkspace()

    await user.click(screen.getByRole('button', { name: '创建授权' }))
    const dialog = screen.getByRole('dialog', { name: '创建文档授权' })
    await user.type(
      within(dialog).getByRole('textbox', { name: '精确目标账号' }),
      'reader@example.com',
    )
    await user.click(
      await within(dialog).findByRole('checkbox', {
        name: /Conflict document/,
      }),
    )
    await user.click(within(dialog).getByRole('button', { name: '审查授权' }))
    await user.click(
      within(dialog).getByRole('button', { name: '确认创建授权' }),
    )

    const error = await within(dialog).findByRole('region', {
      name: '创建文档授权失败',
    })
    expect(error).toHaveTextContent('DOCUMENT_ACCESS_GRANT_CONFLICT')
    expect(error).toHaveTextContent('grant-create-conflict')
    expect(error).not.toHaveTextContent('raw-conflict-marker')
    expect(
      within(dialog).getByText(/目标账号：/),
    ).toHaveTextContent('目标账号：reader@example.com')
    await waitFor(() => expect(grantListRequestCount).toBe(2))
  })
})
