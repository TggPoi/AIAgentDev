import type { HttpClient } from '@/api/http-client'
import type {
  KnowledgeDocumentContentResponseDto,
  KnowledgeDocumentDetailDto,
  KnowledgeDocumentListResponseDto,
} from '@/features/knowledge-documents/knowledge-document-contracts'
import {
  mapKnowledgeDocumentContent,
  mapKnowledgeDocumentDetail,
  mapKnowledgeDocumentPage,
  type KnowledgeDocumentContent,
  type KnowledgeDocumentDetail,
  type KnowledgeDocumentPage,
  type KnowledgeDocumentType,
} from '@/features/knowledge-documents/knowledge-document-models'


export interface KnowledgeDocumentListRequest {
  cursor: string | null
  departmentCode: string | null
  documentType: KnowledgeDocumentType | null
  limit: number
  query: string | null
  signal?: AbortSignal
}

export interface KnowledgeDocumentDownload {
  blob: Blob
  contentDisposition: string | null
  sourceRevision: string | null
}

export interface KnowledgeDocumentApi {
  downloadDocument(
    docId: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeDocumentDownload>
  getDocument(
    docId: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeDocumentDetail>
  getDocumentContent(
    docId: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeDocumentContent>
  listDocuments(request: KnowledgeDocumentListRequest): Promise<KnowledgeDocumentPage>
}

function documentPath(docId: string): string {
  return `/knowledge/documents/${encodeURIComponent(docId)}`
}

function listPath(request: KnowledgeDocumentListRequest): string {
  const search = new URLSearchParams()
  if (request.cursor !== null) search.set('cursor', request.cursor)
  search.set('limit', String(request.limit))
  if (request.query !== null) search.set('query', request.query)
  if (request.departmentCode !== null) {
    search.set('department_code', request.departmentCode)
  }
  if (request.documentType !== null) {
    search.set('document_type', request.documentType)
  }
  return `/knowledge/documents?${search.toString()}`
}

export function createKnowledgeDocumentApi(
  httpClient: HttpClient,
): KnowledgeDocumentApi {
  return {
    async downloadDocument(docId, signal) {
      const response = await httpClient.request<Blob>(
        `${documentPath(docId)}/download`,
        { responseType: 'blob', signal },
      )
      return {
        blob: response.data,
        contentDisposition: response.headers.get('Content-Disposition'),
        sourceRevision: response.headers.get('X-Source-Revision'),
      }
    },

    async getDocument(docId, signal) {
      const response = await httpClient.request<KnowledgeDocumentDetailDto>(
        documentPath(docId),
        { signal },
      )
      return mapKnowledgeDocumentDetail(response.data)
    },

    async getDocumentContent(docId, signal) {
      const response =
        await httpClient.request<KnowledgeDocumentContentResponseDto>(
          `${documentPath(docId)}/content`,
          { signal },
        )
      return mapKnowledgeDocumentContent(response.data)
    },

    async listDocuments(request) {
      const response =
        await httpClient.request<KnowledgeDocumentListResponseDto>(
          listPath(request),
          { signal: request.signal },
        )
      return mapKnowledgeDocumentPage(response.data)
    },
  }
}
