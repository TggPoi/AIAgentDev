import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { PropsWithChildren } from 'react'
import { describe, expect, it } from 'vitest'

import { createHttpClient } from '@/api/http-client'
import { createDocumentGrantApi } from '@/features/document-grants/document-grant-api'
import {
  documentGrantKeys,
  useCreateDocumentGrants,
  useRevokeDocumentGrant,
} from '@/features/document-grants/document-grant-queries'
import { knowledgeDocumentKeys } from '@/features/knowledge-documents/knowledge-document-queries'
import { server } from '@/test/server'


const apiBaseUrl = 'http://document-grant-mutations.test'

function grantDto(documentId: string) {
  return {
    document_department_code: 'development',
    document_id: documentId,
    grant_id: `grant-${documentId}`,
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

function createHarness() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  })
  const api = createDocumentGrantApi(
    createHttpClient({
      baseUrl: apiBaseUrl,
      getAccessToken: () => null,
      requestIdFactory: () => 'document-grant-mutation-request',
    }),
  )
  const wrapper = ({ children }: PropsWithChildren) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return { api, queryClient, wrapper }
}

function seedQuery(queryClient: QueryClient, queryKey: readonly unknown[]) {
  queryClient.setQueryData(queryKey, { serverFact: true })
}

describe('document grant mutation convergence', () => {
  it('creates without browser ACL state and invalidates only related document facts', async () => {
    server.use(
      http.post(`${apiBaseUrl}/admin/document-access/grants`, () =>
        HttpResponse.json({
          created_count: 1,
          existing_count: 0,
          items: [grantDto('doc-1')],
        }),
      ),
    )
    const { api, queryClient, wrapper } = createHarness()
    const grantListKey = documentGrantKeys.list('manager-1', {
      departmentCode: null,
      documentId: null,
      limit: 20,
      status: null,
      targetAccount: null,
    })
    const documentListKey = knowledgeDocumentKeys.list('manager-1', {
      departmentCode: null,
      documentType: null,
      limit: 20,
      query: null,
    })
    const relatedDetailKey = knowledgeDocumentKeys.detail('manager-1', 'doc-1')
    const relatedContentKey = knowledgeDocumentKeys.content(
      'manager-1',
      'doc-1',
    )
    const unrelatedDetailKey = knowledgeDocumentKeys.detail(
      'manager-1',
      'doc-other',
    )
    for (const key of [
      grantListKey,
      documentListKey,
      relatedDetailKey,
      relatedContentKey,
      unrelatedDetailKey,
    ]) {
      seedQuery(queryClient, key)
    }
    const { result } = renderHook(
      () => useCreateDocumentGrants(api, 'manager-1'),
      { wrapper },
    )

    await result.current.mutateAsync({
      document_ids: ['doc-1'],
      target_account: 'reader@example.com',
    })

    expect(queryClient.getQueryState(grantListKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(documentListKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(relatedDetailKey)?.isInvalidated).toBe(
      true,
    )
    expect(queryClient.getQueryState(relatedContentKey)?.isInvalidated).toBe(
      true,
    )
    expect(queryClient.getQueryState(unrelatedDetailKey)?.isInvalidated).toBe(
      false,
    )
  })

  it('does not optimistically revoke and refreshes related facts from the response', async () => {
    let releaseResponse: (() => void) | undefined
    const responseGate = new Promise<void>((resolve) => {
      releaseResponse = resolve
    })
    server.use(
      http.delete(
        `${apiBaseUrl}/admin/document-access/grants/grant-doc-1`,
        async () => {
          await responseGate
          return HttpResponse.json({
            ...grantDto('doc-1'),
            revoked_at: '2026-09-01T02:00:00Z',
            revoked_by_user_id: 'manager-1',
            status: 'revoked',
          })
        },
      ),
    )
    const { api, queryClient, wrapper } = createHarness()
    const grantListKey = documentGrantKeys.list('manager-1', {
      departmentCode: null,
      documentId: null,
      limit: 20,
      status: null,
      targetAccount: null,
    })
    const documentListKey = knowledgeDocumentKeys.list('manager-1', {
      departmentCode: null,
      documentType: null,
      limit: 20,
      query: null,
    })
    const relatedDetailKey = knowledgeDocumentKeys.detail('manager-1', 'doc-1')
    const relatedContentKey = knowledgeDocumentKeys.content(
      'manager-1',
      'doc-1',
    )
    for (const key of [
      grantListKey,
      documentListKey,
      relatedDetailKey,
      relatedContentKey,
    ]) {
      seedQuery(queryClient, key)
    }
    const oldGrantList = queryClient.getQueryData(grantListKey)
    const { result } = renderHook(
      () => useRevokeDocumentGrant(api, 'manager-1'),
      { wrapper },
    )

    const mutation = result.current.mutateAsync('grant-doc-1')
    await waitFor(() => expect(result.current.isPending).toBe(true))
    expect(queryClient.getQueryData(grantListKey)).toBe(oldGrantList)
    expect(queryClient.getQueryState(grantListKey)?.isInvalidated).toBe(false)

    releaseResponse?.()
    await expect(mutation).resolves.toMatchObject({
      documentId: 'doc-1',
      status: 'revoked',
    })

    expect(queryClient.getQueryState(grantListKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(documentListKey)?.isInvalidated).toBe(true)
    expect(queryClient.getQueryState(relatedDetailKey)?.isInvalidated).toBe(
      true,
    )
    expect(queryClient.getQueryState(relatedContentKey)?.isInvalidated).toBe(
      true,
    )
  })

  it.each([403, 404, 409])(
    'reloads grant records after create fails with %s',
    async (status) => {
      server.use(
        http.post(`${apiBaseUrl}/admin/document-access/grants`, () =>
          HttpResponse.json(
            {
              code: `GRANT_${status}`,
              error_category: 'document_access_grant',
              message: 'safe error',
              request_id: `grant-${status}`,
              trace_id: null,
            },
            { status },
          ),
        ),
      )
      const { api, queryClient, wrapper } = createHarness()
      const grantListKey = documentGrantKeys.list('manager-1', {
        departmentCode: null,
        documentId: null,
        limit: 20,
        status: null,
        targetAccount: null,
      })
      seedQuery(queryClient, grantListKey)
      const { result } = renderHook(
        () => useCreateDocumentGrants(api, 'manager-1'),
        { wrapper },
      )

      await expect(
        result.current.mutateAsync({
          document_ids: ['doc-1'],
          target_account: 'reader@example.com',
        }),
      ).rejects.toMatchObject({ status })

      expect(queryClient.getQueryState(grantListKey)?.isInvalidated).toBe(true)
    },
  )

  it.each([403, 404, 409])(
    'reloads grant records after revoke fails with %s',
    async (status) => {
      server.use(
        http.delete(
          `${apiBaseUrl}/admin/document-access/grants/grant-doc-1`,
          () =>
            HttpResponse.json(
              {
                code: `GRANT_${status}`,
                error_category: 'document_access_grant',
                message: 'safe error',
                request_id: `grant-${status}`,
                trace_id: null,
              },
              { status },
            ),
        ),
      )
      const { api, queryClient, wrapper } = createHarness()
      const grantListKey = documentGrantKeys.list('manager-1', {
        departmentCode: null,
        documentId: null,
        limit: 20,
        status: null,
        targetAccount: null,
      })
      seedQuery(queryClient, grantListKey)
      const { result } = renderHook(
        () => useRevokeDocumentGrant(api, 'manager-1'),
        { wrapper },
      )

      await expect(
        result.current.mutateAsync('grant-doc-1'),
      ).rejects.toMatchObject({ status })

      expect(queryClient.getQueryState(grantListKey)?.isInvalidated).toBe(true)
    },
  )
})
