import type { HttpClient } from '@/api/http-client'
import type {
  CreateDocumentAccessGrantsRequestDto,
  CreateDocumentAccessGrantsResponseDto,
  DocumentAccessGrantableDocumentListResponseDto,
  DocumentAccessGrantItemDto,
  DocumentAccessGrantListResponseDto,
} from '@/features/document-grants/document-grant-contracts'
import {
  mapCreateDocumentGrantsResult,
  mapDocumentGrant,
  mapDocumentGrantPage,
  mapGrantableDocumentPage,
  type CreateDocumentGrantsResult,
  type DocumentGrant,
  type DocumentGrantPage,
  type DocumentGrantStatus,
  type GrantableDocumentPage,
} from '@/features/document-grants/document-grant-models'


export interface DocumentGrantListRequest {
  cursor: string | null
  departmentCode: string | null
  documentId: string | null
  limit: number
  signal?: AbortSignal
  status: DocumentGrantStatus | null
  targetAccount: string | null
}

export interface GrantableDocumentListRequest {
  cursor: string | null
  departmentCode: string | null
  limit: number
  query: string | null
  signal?: AbortSignal
}

export interface DocumentGrantApi {
  createGrants(
    request: CreateDocumentAccessGrantsRequestDto,
  ): Promise<CreateDocumentGrantsResult>
  listGrantableDocuments(
    request: GrantableDocumentListRequest,
  ): Promise<GrantableDocumentPage>
  listGrants(request: DocumentGrantListRequest): Promise<DocumentGrantPage>
  revokeGrant(grantId: string): Promise<DocumentGrant>
}

function listPath(request: DocumentGrantListRequest): string {
  const search = new URLSearchParams()
  if (request.cursor !== null) search.set('cursor', request.cursor)
  search.set('limit', String(request.limit))
  if (request.targetAccount !== null) {
    search.set('target_account', request.targetAccount)
  }
  if (request.documentId !== null) search.set('doc_id', request.documentId)
  if (request.status !== null) search.set('status', request.status)
  if (request.departmentCode !== null) {
    search.set('department_code', request.departmentCode)
  }
  return `/admin/document-access/grants?${search.toString()}`
}

function grantableDocumentListPath(
  request: GrantableDocumentListRequest,
): string {
  const search = new URLSearchParams()
  if (request.cursor !== null) search.set('cursor', request.cursor)
  search.set('limit', String(request.limit))
  if (request.query !== null) search.set('query', request.query)
  if (request.departmentCode !== null) {
    search.set('department_code', request.departmentCode)
  }
  return `/admin/document-access/grantable-documents?${search.toString()}`
}

export function createDocumentGrantApi(httpClient: HttpClient): DocumentGrantApi {
  return {
    async createGrants(request) {
      const response =
        await httpClient.request<CreateDocumentAccessGrantsResponseDto>(
          '/admin/document-access/grants',
          { json: request, method: 'POST' },
        )
      return mapCreateDocumentGrantsResult(response.data)
    },

    async listGrantableDocuments(request) {
      const response =
        await httpClient.request<DocumentAccessGrantableDocumentListResponseDto>(
          grantableDocumentListPath(request),
          { signal: request.signal },
        )
      return mapGrantableDocumentPage(response.data)
    },

    async listGrants(request) {
      const response =
        await httpClient.request<DocumentAccessGrantListResponseDto>(
          listPath(request),
          { signal: request.signal },
        )
      return mapDocumentGrantPage(response.data)
    },

    async revokeGrant(grantId) {
      const response = await httpClient.request<DocumentAccessGrantItemDto>(
        `/admin/document-access/grants/${encodeURIComponent(grantId)}`,
        { method: 'DELETE' },
      )
      return mapDocumentGrant(response.data)
    },
  }
}
