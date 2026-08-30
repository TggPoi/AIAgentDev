import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router-dom'

import { createHttpClient } from '@/api/http-client'
import { createKnowledgeDocumentApi } from '@/features/knowledge-documents/knowledge-document-api'
import { KnowledgeDocumentWorkspace } from '@/features/knowledge-documents/KnowledgeDocumentWorkspace'
import { server } from '@/test/server'


const apiBaseUrl = 'http://knowledge-document-workspace.test'

function createApi() {
  return createKnowledgeDocumentApi(
    createHttpClient({
      baseUrl: apiBaseUrl,
      getAccessToken: () => null,
      requestIdFactory: () => 'knowledge-document-workspace-request',
    }),
  )
}

function LocationProbe() {
  const location = useLocation()
  return (
    <output aria-label="current-route">
      {`${location.pathname}${location.search}`}
    </output>
  )
}

function renderWorkspace(initialEntry: string, docId: string | null = null) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <KnowledgeDocumentWorkspace
          api={createApi()}
          docId={docId}
          userBoundary="reader-1"
        />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function documentDto(
  docId: string,
  title: string,
  accessSource: 'department' | 'explicit_grant' | 'public',
) {
  return {
    access_source: accessSource,
    department_code: accessSource === 'public' ? 'source-owner' : 'engineering',
    doc_id: docId,
    document_type: 'markdown' as const,
    file_name: `${docId}.md`,
    repository_path: `docs/${docId}.md`,
    source_revision: 'revision-1',
    title,
    updated_at: '2026-08-30T01:00:00Z',
  }
}

function detailDto(docId: string, title: string) {
  return {
    ...documentDto(docId, title, 'public'),
    source_id: 'source-1',
    source_project_path: 'group/project',
    visibility: 'public',
  }
}

describe('KnowledgeDocumentWorkspace list', () => {
  it('stores filters in the URL, explains access source and appends opaque cursor pages', async () => {
    const requests: URL[] = []
    server.use(
      http.get(`${apiBaseUrl}/knowledge/documents`, ({ request }) => {
        const url = new URL(request.url)
        requests.push(url)
        return HttpResponse.json(
          url.searchParams.get('cursor') === null
            ? {
                items: [
                  documentDto('doc-public', '公共指南', 'public'),
                  documentDto('doc-grant', '外部门授权文档', 'explicit_grant'),
                ],
                next_cursor: 'opaque+/=',
              }
            : {
                items: [
                  documentDto('doc-department', '部门手册', 'department'),
                ],
                next_cursor: null,
              },
        )
      }),
    )
    const user = userEvent.setup()
    renderWorkspace('/documents')

    const list = await screen.findByRole('list', { name: '知识文档列表' })
    expect(within(list).getByText('公共区域')).toBeInTheDocument()
    expect(within(list).getByText('精确授权')).toBeInTheDocument()
    expect(within(list).getByText('来源部门：source-owner')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('关键词'), {
      target: { value: 'agent' },
    })
    fireEvent.change(screen.getByLabelText('部门'), {
      target: { value: 'engineering' },
    })
    await user.selectOptions(screen.getByLabelText('文档格式'), 'markdown')

    await waitFor(() => {
      expect(screen.getByLabelText('current-route')).toHaveTextContent(
        '/documents?query=agent&department_code=engineering&document_type=markdown',
      )
    })
    await waitFor(() => {
      expect(
        requests.some(
          (url) =>
            url.searchParams.get('query') === 'agent' &&
            url.searchParams.get('department_code') === 'engineering' &&
            url.searchParams.get('document_type') === 'markdown',
        ),
      ).toBe(true)
    })

    await user.click(screen.getByRole('button', { name: '加载更多文档' }))
    expect(await screen.findByText('部门手册')).toBeInTheDocument()
    expect(requests.at(-1)?.searchParams.get('cursor')).toBe('opaque+/=')
  })

  it('maps approved 422 fields without rendering an unsafe backend message', async () => {
    server.use(
      http.get(`${apiBaseUrl}/knowledge/documents`, () =>
        HttpResponse.json(
          {
            code: 'REQUEST_VALIDATION_ERROR',
            error_category: 'user_error',
            field_errors: [
              { field: 'query', code: 'too_long', message: '关键词过长' },
            ],
            message: 'must-not-be-rendered',
            request_id: 'request-filter-error',
            trace_id: null,
          },
          { status: 422 },
        ),
      ),
    )

    renderWorkspace('/documents?query=too-long')

    expect(await screen.findByText('关键词过长')).toBeInTheDocument()
    expect(screen.getByLabelText('关键词')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.queryByText('must-not-be-rendered')).not.toBeInTheDocument()
  })
})

describe('KnowledgeDocumentWorkspace detail', () => {
  it('renders Markdown safely and exposes truncation and allowlisted warnings', async () => {
    server.use(
      http.get(`${apiBaseUrl}/knowledge/documents/doc-markdown`, () =>
        HttpResponse.json(detailDto('doc-markdown', 'Markdown 指南')),
      ),
      http.get(`${apiBaseUrl}/knowledge/documents/doc-markdown/content`, () =>
        HttpResponse.json({
          content:
            '# 安全预览\n<script>must-not-render</script>\n[不安全链接](https://user:pass@example.com/private)',
          doc_id: 'doc-markdown',
          document_type: 'markdown',
          render_mode: 'markdown',
          source_revision: 'revision-1',
          truncated: true,
          warnings: ['preview_truncated', 'must-not-render-warning'],
        }),
      ),
    )

    renderWorkspace('/documents/doc-markdown', 'doc-markdown')

    expect(
      await screen.findByRole('heading', { name: 'Markdown 指南' }),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('heading', { name: '安全预览' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('must-not-render')).not.toBeInTheDocument()
    expect(screen.getByText('不安全链接')).not.toHaveAttribute('href')
    expect(screen.getByText('预览内容已被截断。')).toBeInTheDocument()
    expect(screen.getByText('内容预览包含非阻断提示。')).toBeInTheDocument()
    expect(screen.queryByText('must-not-render-warning')).not.toBeInTheDocument()
  })

  it.each([
    ['plain_text', '纯文本按原始换行显示。'],
    ['extracted_text', '提取文本不保留原始 PDF 或 Office 排版。'],
  ] as const)('renders %s content with the correct explanation', async (renderMode, notice) => {
    server.use(
      http.get(`${apiBaseUrl}/knowledge/documents/doc-text`, () =>
        HttpResponse.json(detailDto('doc-text', '文本预览')),
      ),
      http.get(`${apiBaseUrl}/knowledge/documents/doc-text/content`, () =>
        HttpResponse.json({
          content: '第一行\n第二行',
          doc_id: 'doc-text',
          document_type: renderMode === 'plain_text' ? 'text' : 'pdf',
          render_mode: renderMode,
          source_revision: 'revision-1',
          truncated: false,
          warnings: [],
        }),
      ),
    )

    renderWorkspace('/documents/doc-text', 'doc-text')

    expect(await screen.findByText(notice)).toBeInTheDocument()
    expect(screen.getByText(/第一行/)).toHaveTextContent('第一行 第二行')
  })

  it('uses one hidden 404 state and does not fetch content after detail denial', async () => {
    let contentRequests = 0
    server.use(
      http.get(`${apiBaseUrl}/knowledge/documents/doc-hidden`, () =>
        HttpResponse.json(
          {
            code: 'KNOWLEDGE_DOCUMENT_NOT_FOUND',
            message: 'must-not-be-rendered',
            request_id: 'request-hidden-document',
          },
          { status: 404 },
        ),
      ),
      http.get(`${apiBaseUrl}/knowledge/documents/doc-hidden/content`, () => {
        contentRequests += 1
        return HttpResponse.json({})
      }),
    )

    renderWorkspace('/documents/doc-hidden', 'doc-hidden')

    expect(
      await screen.findByRole('heading', { name: '文档不可用' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('must-not-be-rendered')).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回知识文档列表' })).toHaveAttribute(
      'href',
      '/documents',
    )
    expect(contentRequests).toBe(0)
  })
})
