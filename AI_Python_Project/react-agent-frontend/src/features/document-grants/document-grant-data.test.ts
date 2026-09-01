import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { createHttpClient } from '@/api/http-client'
import { createDocumentGrantApi } from '@/features/document-grants/document-grant-api'
import type { CreateDocumentAccessGrantsRequestDto } from '@/features/document-grants/document-grant-contracts'
import {
  mergeGrantableDocumentPages,
  mergeDocumentGrantPages,
  type DocumentGrant,
  type GrantableDocument,
} from '@/features/document-grants/document-grant-models'
import { documentGrantKeys } from '@/features/document-grants/document-grant-queries'
import { server } from '@/test/server'


const apiBaseUrl = 'http://document-grants.test'

function createApi() {
  return createDocumentGrantApi(
    createHttpClient({
      baseUrl: apiBaseUrl,
      getAccessToken: () => null,
      requestIdFactory: () => 'document-grant-request-id',
    }),
  )
}

function grantDto(grantId: string, documentId: string) {
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
    revoked_at: null,
    revoked_by_user_id: null,
    status: 'active' as const,
  }
}

describe('document grant private query keys', () => {
  it('isolates list filters by authenticated user', () => {
    const params = {
      departmentCode: 'development',
      documentId: 'doc-1',
      limit: 20,
      status: 'active' as const,
      targetAccount: 'reader@example.com',
    }

    expect(documentGrantKeys.list('admin-a', params)).not.toEqual(
      documentGrantKeys.list('admin-b', params),
    )
  })

  it('isolates grantable-document filters by authenticated user', () => {
    const params = {
      departmentCode: 'development',
      limit: 20,
      query: 'runbook',
    }

    expect(documentGrantKeys.grantableList('admin-a', params)).not.toEqual(
      documentGrantKeys.grantableList('admin-b', params),
    )
  })
})

function grantableDocument(
  documentId: string,
  title = 'Runbook',
): GrantableDocument {
  return {
    documentDepartmentCode: 'development',
    documentId,
    documentType: 'markdown',
    repositoryPath: `docs/${documentId}.md`,
    title,
  }
}

describe('grantable document keyset page merge', () => {
  it('preserves server order and keeps the first occurrence of each document', () => {
    expect(
      mergeGrantableDocumentPages([
        {
          items: [grantableDocument('doc-b'), grantableDocument('doc-a')],
          nextCursor: 'cursor-2',
        },
        {
          items: [
            grantableDocument('doc-a', 'Duplicate'),
            grantableDocument('doc-c'),
          ],
          nextCursor: null,
        },
      ]).map((item) => item.documentId),
    ).toEqual(['doc-b', 'doc-a', 'doc-c'])
  })
})

function grant(grantId: string, documentId: string): DocumentGrant {
  return {
    documentDepartmentCode: 'development',
    documentId,
    grantId,
    grantedAt: '2026-09-01T01:00:00Z',
    grantedByUserId: 'manager-1',
    grantee: {
      displayName: 'Reader',
      primaryDepartmentCode: 'operations',
      userId: 'reader-1',
      username: 'reader',
    },
    repositoryPath: `docs/${documentId}.md`,
    revokedAt: null,
    revokedByUserId: null,
    status: 'active',
  }
}

describe('document grant keyset page merge', () => {
  it('preserves server order and keeps the first occurrence of each grant', () => {
    expect(
      mergeDocumentGrantPages([
        {
          items: [grant('grant-b', 'doc-b'), grant('grant-a', 'doc-a')],
          nextCursor: 'cursor-2',
        },
        {
          items: [
            grant('grant-a', 'duplicate-doc'),
            grant('grant-c', 'doc-c'),
          ],
          nextCursor: null,
        },
      ]).map((item) => item.grantId),
    ).toEqual(['grant-b', 'grant-a', 'grant-c'])
  })
})

describe('document grant HTTP adapter', () => {
  it('lists server-trimmed grantable documents with opaque paging and safe mapping', async () => {
    server.use(
      http.get(
        `${apiBaseUrl}/admin/document-access/grantable-documents`,
        ({ request }) => {
          const url = new URL(request.url)
          expect(url.searchParams.get('cursor')).toBe('opaque+/=')
          expect(url.searchParams.get('limit')).toBe('20')
          expect(url.searchParams.get('query')).toBe('runbook')
          expect(url.searchParams.get('department_code')).toBe('development')
          return HttpResponse.json({
            items: [
              {
                doc_id: 'doc-1',
                document_department_code: 'development',
                document_type: 'markdown',
                private_acl: 'must-not-enter-domain-model',
                repository_path: 'docs/doc-1.md',
                title: 'Runbook',
                visibility: 'must-not-enter-domain-model',
              },
            ],
            next_cursor: 'cursor-2',
            private_scope: 'must-not-enter-domain-model',
          })
        },
      ),
    )

    await expect(
      createApi().listGrantableDocuments({
        cursor: 'opaque+/=',
        departmentCode: 'development',
        limit: 20,
        query: 'runbook',
      }),
    ).resolves.toEqual({
      items: [grantableDocument('doc-1')],
      nextCursor: 'cursor-2',
    })
  })

  it('omits empty grantable-document filters instead of inventing management scope', async () => {
    server.use(
      http.get(
        `${apiBaseUrl}/admin/document-access/grantable-documents`,
        ({ request }) => {
          const url = new URL(request.url)
          expect(url.searchParams.has('cursor')).toBe(false)
          expect(url.searchParams.has('query')).toBe(false)
          expect(url.searchParams.has('department_code')).toBe(false)
          expect(url.searchParams.get('limit')).toBe('20')
          return HttpResponse.json({ items: [], next_cursor: null })
        },
      ),
    )

    await createApi().listGrantableDocuments({
      cursor: null,
      departmentCode: null,
      limit: 20,
      query: null,
    })
  })

  it('passes opaque cursors and filters, then maps only allowlisted fields', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('cursor')).toBe('opaque+/=')
        expect(url.searchParams.get('limit')).toBe('20')
        expect(url.searchParams.get('target_account')).toBe(
          'reader@example.com',
        )
        expect(url.searchParams.get('doc_id')).toBe('doc-1')
        expect(url.searchParams.get('status')).toBe('active')
        expect(url.searchParams.get('department_code')).toBe('development')
        return HttpResponse.json({
          items: [
            {
              ...grantDto('grant-1', 'doc-1'),
              private_acl: 'must-not-enter-domain-model',
            },
          ],
          next_cursor: 'cursor-2',
          private_scope: 'must-not-enter-domain-model',
        })
      }),
    )

    await expect(
      createApi().listGrants({
        cursor: 'opaque+/=',
        departmentCode: 'development',
        documentId: 'doc-1',
        limit: 20,
        status: 'active',
        targetAccount: 'reader@example.com',
      }),
    ).resolves.toEqual({
      items: [grant('grant-1', 'doc-1')],
      nextCursor: 'cursor-2',
    })
  })

  it('omits empty optional filters instead of inventing grant scope', async () => {
    server.use(
      http.get(`${apiBaseUrl}/admin/document-access/grants`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.has('cursor')).toBe(false)
        expect(url.searchParams.has('target_account')).toBe(false)
        expect(url.searchParams.has('doc_id')).toBe(false)
        expect(url.searchParams.has('status')).toBe(false)
        expect(url.searchParams.has('department_code')).toBe(false)
        expect(url.searchParams.get('limit')).toBe('20')
        return HttpResponse.json({ items: [], next_cursor: null })
      }),
    )

    await createApi().listGrants({
      cursor: null,
      departmentCode: null,
      documentId: null,
      limit: 20,
      status: null,
      targetAccount: null,
    })
  })

  it('posts the generated create request and maps idempotent counts', async () => {
    const request: CreateDocumentAccessGrantsRequestDto = {
      document_ids: ['doc-1', 'doc-2'],
      target_account: 'reader@example.com',
    }
    let receivedBody: unknown
    server.use(
      http.post(
        `${apiBaseUrl}/admin/document-access/grants`,
        async ({ request: httpRequest }) => {
          receivedBody = await httpRequest.json()
          return HttpResponse.json({
            created_count: 1,
            existing_count: 1,
            items: [
              {
                ...grantDto('grant-1', 'doc-1'),
                private_acl: 'must-not-enter-domain-model',
              },
              grantDto('grant-2', 'doc-2'),
            ],
          })
        },
      ),
    )

    const response = await createApi().createGrants(request)

    expect(receivedBody).toEqual(request)
    expect(response).toEqual({
      createdCount: 1,
      existingCount: 1,
      items: [grant('grant-1', 'doc-1'), grant('grant-2', 'doc-2')],
    })
  })

  it('deletes an encoded grant id and maps the retained audit record', async () => {
    server.use(
      http.delete(
        `${apiBaseUrl}/admin/document-access/grants/grant%2Fone%3F%23`,
        () =>
          HttpResponse.json({
            ...grantDto('grant/one?#', 'doc-1'),
            revoked_at: '2026-09-01T02:00:00Z',
            revoked_by_user_id: 'manager-1',
            status: 'revoked',
          }),
      ),
    )

    await expect(createApi().revokeGrant('grant/one?#')).resolves.toEqual({
      ...grant('grant/one?#', 'doc-1'),
      revokedAt: '2026-09-01T02:00:00Z',
      revokedByUserId: 'manager-1',
      status: 'revoked',
    })
  })
})
