import {
  type InfiniteData,
  useInfiniteQuery,
  useQuery,
} from '@tanstack/react-query'

import type { KnowledgeDocumentApi } from '@/features/knowledge-documents/knowledge-document-api'
import type {
  KnowledgeDocumentContent,
  KnowledgeDocumentDetail,
  KnowledgeDocumentPage,
  KnowledgeDocumentType,
} from '@/features/knowledge-documents/knowledge-document-models'


export interface KnowledgeDocumentListFilters {
  departmentCode: string | null
  documentType: KnowledgeDocumentType | null
  query: string | null
}

export interface KnowledgeDocumentListKeyParams
  extends KnowledgeDocumentListFilters {
  limit: number
}

export const KNOWLEDGE_DOCUMENT_LIST_LIMIT = 20

export const knowledgeDocumentKeys = {
  content: (userBoundary: string, docId: string) =>
    [userBoundary, 'knowledge-document-content', docId] as const,
  contentRoot: (userBoundary: string) =>
    [userBoundary, 'knowledge-document-content'] as const,
  detail: (userBoundary: string, docId: string) =>
    [userBoundary, 'knowledge-document-detail', docId] as const,
  detailRoot: (userBoundary: string) =>
    [userBoundary, 'knowledge-document-detail'] as const,
  list: (userBoundary: string, params: KnowledgeDocumentListKeyParams) =>
    [...knowledgeDocumentKeys.listRoot(userBoundary), params] as const,
  listRoot: (userBoundary: string) =>
    [userBoundary, 'knowledge-documents'] as const,
}

export function useKnowledgeDocumentList(
  api: KnowledgeDocumentApi,
  userBoundary: string,
  filters: KnowledgeDocumentListFilters,
) {
  const params = { ...filters, limit: KNOWLEDGE_DOCUMENT_LIST_LIMIT }
  return useInfiniteQuery<
    KnowledgeDocumentPage,
    Error,
    InfiniteData<KnowledgeDocumentPage>,
    ReturnType<typeof knowledgeDocumentKeys.list>,
    string | null
  >({
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api.listDocuments({
        cursor: pageParam,
        ...filters,
        limit: KNOWLEDGE_DOCUMENT_LIST_LIMIT,
        signal,
      }),
    queryKey: knowledgeDocumentKeys.list(userBoundary, params),
  })
}

export function useKnowledgeDocumentDetail(
  api: KnowledgeDocumentApi,
  userBoundary: string,
  docId: string | null,
) {
  return useQuery<KnowledgeDocumentDetail, Error>({
    enabled: docId !== null,
    queryFn: ({ signal }) => api.getDocument(docId ?? '', signal),
    queryKey: knowledgeDocumentKeys.detail(
      userBoundary,
      docId ?? '__no-document__',
    ),
  })
}

export function useKnowledgeDocumentContent(
  api: KnowledgeDocumentApi,
  userBoundary: string,
  docId: string | null,
) {
  return useQuery<KnowledgeDocumentContent, Error>({
    enabled: docId !== null,
    queryFn: ({ signal }) => api.getDocumentContent(docId ?? '', signal),
    queryKey: knowledgeDocumentKeys.content(
      userBoundary,
      docId ?? '__no-document__',
    ),
  })
}
