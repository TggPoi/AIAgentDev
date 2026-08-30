import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { createHttpClient } from '@/api/http-client'
import { createKnowledgeDocumentApi } from '@/features/knowledge-documents/knowledge-document-api'
import {
  mergeKnowledgeDocumentPages,
  type KnowledgeDocumentSummary,
} from '@/features/knowledge-documents/knowledge-document-models'
import { knowledgeDocumentKeys } from '@/features/knowledge-documents/knowledge-document-queries'
import { server } from '@/test/server'


const apiBaseUrl = 'http://knowledge-documents.test'

function createApi() {
  return createKnowledgeDocumentApi(
    createHttpClient({
      baseUrl: apiBaseUrl,
      getAccessToken: () => null,
      requestIdFactory: () => 'knowledge-document-request-id',
    }),
  )
}

function documentDto(docId: string, title: string) {
  return {
    access_source: 'public' as const,
    department_code: 'public-source-owner',
    doc_id: docId,
    document_type: 'markdown' as const,
    file_name: `${docId}.md`,
    repository_path: `docs/${docId}.md`,
    source_revision: 'revision-1',
    title,
    updated_at: '2026-08-30T01:00:00Z',
  }
}

function documentSummary(
  docId: string,
  title: string,
): KnowledgeDocumentSummary {
  return {
    accessSource: 'public',
    departmentCode: 'public-source-owner',
    docId,
    documentType: 'markdown',
    fileName: `${docId}.md`,
    repositoryPath: `docs/${docId}.md`,
    sourceRevision: 'revision-1',
    title,
    updatedAt: '2026-08-30T01:00:00Z',
  }
}

describe('knowledge document private query keys', () => {
  it('isolates list filters, detail and content by authenticated user', () => {
    const filters = {
      departmentCode: 'engineering',
      documentType: 'markdown' as const,
      limit: 20,
      query: 'agent',
    }

    expect(knowledgeDocumentKeys.list('user-a', filters)).not.toEqual(
      knowledgeDocumentKeys.list('user-b', filters),
    )
    expect(knowledgeDocumentKeys.detail('user-a', 'shared-doc')).not.toEqual(
      knowledgeDocumentKeys.detail('user-b', 'shared-doc'),
    )
    expect(knowledgeDocumentKeys.content('user-a', 'shared-doc')).not.toEqual(
      knowledgeDocumentKeys.content('user-b', 'shared-doc'),
    )
  })
})

describe('knowledge document keyset page merge', () => {
  it('preserves server order and keeps the first occurrence of each document', () => {
    expect(
      mergeKnowledgeDocumentPages([
        {
          items: [
            documentSummary('doc-b', 'B'),
            documentSummary('doc-a', 'A'),
          ],
          nextCursor: 'cursor-2',
        },
        {
          items: [
            documentSummary('doc-a', 'A duplicate'),
            documentSummary('doc-c', 'C'),
          ],
          nextCursor: null,
        },
      ]).map((item) => item.docId),
    ).toEqual(['doc-b', 'doc-a', 'doc-c'])
  })
})

describe('knowledge document HTTP adapter', () => {
  it('passes opaque cursors and non-empty filters, then maps the list page', async () => {
    server.use(
      http.get(`${apiBaseUrl}/knowledge/documents`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('cursor')).toBe('opaque+/=')
        expect(url.searchParams.get('limit')).toBe('20')
        expect(url.searchParams.get('query')).toBe('agent')
        expect(url.searchParams.get('department_code')).toBe('engineering')
        expect(url.searchParams.get('document_type')).toBe('markdown')
        return HttpResponse.json({
          items: [documentDto('doc-a', '公开文档')],
          next_cursor: 'cursor-2',
        })
      }),
    )

    const page = await createApi().listDocuments({
      cursor: 'opaque+/=',
      departmentCode: 'engineering',
      documentType: 'markdown',
      limit: 20,
      query: 'agent',
    })

    expect(page).toEqual({
      items: [documentSummary('doc-a', '公开文档')],
      nextCursor: 'cursor-2',
    })
  })

  it('omits empty optional filters instead of inventing server semantics', async () => {
    server.use(
      http.get(`${apiBaseUrl}/knowledge/documents`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.has('cursor')).toBe(false)
        expect(url.searchParams.has('query')).toBe(false)
        expect(url.searchParams.has('department_code')).toBe(false)
        expect(url.searchParams.has('document_type')).toBe(false)
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
    )

    await createApi().listDocuments({
      cursor: null,
      departmentCode: null,
      documentType: null,
      limit: 20,
      query: null,
    })
  })

  it('encodes document ids and maps detail and content without arbitrary fields', async () => {
    const encodedDocId = 'doc%20id%3F%23'
    server.use(
      http.get(`${apiBaseUrl}/knowledge/documents/${encodedDocId}`, () =>
        HttpResponse.json({
          ...documentDto('doc id?#', '文档详情'),
          source_id: 'source-1',
          source_project_path: 'group/project',
          visibility: 'public',
          unexpected_field: 'must-not-enter-domain-model',
        }),
      ),
      http.get(
        `${apiBaseUrl}/knowledge/documents/${encodedDocId}/content`,
        () =>
          HttpResponse.json({
            content: '# 安全预览',
            doc_id: 'doc id?#',
            document_type: 'markdown',
            render_mode: 'markdown',
            source_revision: 'revision-1',
            truncated: true,
            warnings: ['preview_truncated'],
            unexpected_field: 'must-not-enter-domain-model',
          }),
      ),
    )

    const api = createApi()
    const detail = await api.getDocument('doc id?#')
    const content = await api.getDocumentContent('doc id?#')

    expect(detail).toEqual({
      ...documentSummary('doc id?#', '文档详情'),
      sourceId: 'source-1',
      sourceProjectPath: 'group/project',
      visibility: 'public',
    })
    expect(content).toEqual({
      content: '# 安全预览',
      docId: 'doc id?#',
      documentType: 'markdown',
      renderMode: 'markdown',
      sourceRevision: 'revision-1',
      truncated: true,
      warnings: ['preview_truncated'],
    })
  })

  it('returns only the protected Blob and declared download headers', async () => {
    server.use(
      http.get(
        `${apiBaseUrl}/knowledge/documents/doc-download/download`,
        () =>
          new HttpResponse('document bytes', {
            headers: {
              'Content-Disposition': "attachment; filename*=UTF-8''guide.md",
              'Content-Type': 'application/octet-stream',
              'X-Unlisted-Metadata': 'must-not-enter-domain-model',
              'X-Source-Revision': 'revision-1',
            },
          }),
      ),
    )

    const download = await createApi().downloadDocument('doc-download')

    expect(await download.blob.text()).toBe('document bytes')
    expect(download).toMatchObject({
      contentDisposition: "attachment; filename*=UTF-8''guide.md",
      sourceRevision: 'revision-1',
    })
    expect(download).not.toHaveProperty('headers')
  })
})
