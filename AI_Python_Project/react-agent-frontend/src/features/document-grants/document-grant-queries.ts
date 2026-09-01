import {
  type InfiniteData,
  type QueryClient,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query'

import { ApiError } from '@/api/api-error'
import type { DocumentGrantApi } from '@/features/document-grants/document-grant-api'
import type { CreateDocumentAccessGrantsRequestDto } from '@/features/document-grants/document-grant-contracts'
import type {
  DocumentGrantPage,
  DocumentGrantStatus,
  GrantableDocumentPage,
} from '@/features/document-grants/document-grant-models'
import { knowledgeDocumentKeys } from '@/features/knowledge-documents/knowledge-document-queries'

export interface DocumentGrantListFilters {
  departmentCode: string | null
  documentId: string | null
  status: DocumentGrantStatus | null
  targetAccount: string | null
}

export interface DocumentGrantListKeyParams extends DocumentGrantListFilters {
  limit: number
}

export interface GrantableDocumentListFilters {
  departmentCode: string | null
  query: string | null
}

export interface GrantableDocumentListKeyParams
  extends GrantableDocumentListFilters {
  limit: number
}

export const DOCUMENT_GRANT_LIST_LIMIT = 20

export const documentGrantKeys = {
  grantableList: (
    userBoundary: string,
    params: GrantableDocumentListKeyParams,
  ) => [...documentGrantKeys.grantableListRoot(userBoundary), params] as const,
  grantableListRoot: (userBoundary: string) =>
    [userBoundary, 'document-access-grantable-documents'] as const,
  list: (userBoundary: string, params: DocumentGrantListKeyParams) =>
    [...documentGrantKeys.listRoot(userBoundary), params] as const,
  listRoot: (userBoundary: string) =>
    [userBoundary, 'document-access-grants'] as const,
}

export function useGrantableDocumentList(
  api: DocumentGrantApi,
  userBoundary: string,
  filters: GrantableDocumentListFilters,
) {
  const params = { ...filters, limit: DOCUMENT_GRANT_LIST_LIMIT }
  return useInfiniteQuery<
    GrantableDocumentPage,
    Error,
    InfiniteData<GrantableDocumentPage>,
    ReturnType<typeof documentGrantKeys.grantableList>,
    string | null
  >({
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api.listGrantableDocuments({
        cursor: pageParam,
        ...filters,
        limit: DOCUMENT_GRANT_LIST_LIMIT,
        signal,
      }),
    queryKey: documentGrantKeys.grantableList(userBoundary, params),
  })
}

export function useDocumentGrantList(
  api: DocumentGrantApi,
  userBoundary: string,
  filters: DocumentGrantListFilters,
) {
  const params = { ...filters, limit: DOCUMENT_GRANT_LIST_LIMIT }
  return useInfiniteQuery<
    DocumentGrantPage,
    Error,
    InfiniteData<DocumentGrantPage>,
    ReturnType<typeof documentGrantKeys.list>,
    string | null
  >({
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api.listGrants({
        cursor: pageParam,
        ...filters,
        limit: DOCUMENT_GRANT_LIST_LIMIT,
        signal,
      }),
    queryKey: documentGrantKeys.list(userBoundary, params),
  })
}

function invalidateDocumentGrantList(
  queryClient: QueryClient,
  userBoundary: string,
) {
  return queryClient.invalidateQueries({
    queryKey: documentGrantKeys.listRoot(userBoundary),
  })
}

function invalidateRelatedDocumentFacts(
  queryClient: QueryClient,
  userBoundary: string,
  documentIds: readonly string[],
) {
  const uniqueDocumentIds = [...new Set(documentIds)]
  return Promise.all([
    queryClient.invalidateQueries({
      queryKey: knowledgeDocumentKeys.listRoot(userBoundary),
    }),
    ...uniqueDocumentIds.flatMap((documentId) => [
      queryClient.invalidateQueries({
        exact: true,
        queryKey: knowledgeDocumentKeys.detail(userBoundary, documentId),
      }),
      queryClient.invalidateQueries({
        exact: true,
        queryKey: knowledgeDocumentKeys.content(userBoundary, documentId),
      }),
    ]),
  ])
}

function refreshGrantRecordsOnFailure(
  error: Error,
  queryClient: QueryClient,
  userBoundary: string,
) {
  return error instanceof ApiError && [403, 404, 409].includes(error.status)
    ? invalidateDocumentGrantList(queryClient, userBoundary)
    : undefined
}

export function useCreateDocumentGrants(
  api: DocumentGrantApi,
  userBoundary: string,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (request: CreateDocumentAccessGrantsRequestDto) =>
      api.createGrants(request),
    onError: (error) =>
      refreshGrantRecordsOnFailure(error, queryClient, userBoundary),
    onSuccess: async (result) => {
      await Promise.all([
        invalidateDocumentGrantList(queryClient, userBoundary),
        invalidateRelatedDocumentFacts(
          queryClient,
          userBoundary,
          result.items.map((item) => item.documentId),
        ),
      ])
    },
  })
}

export function useRevokeDocumentGrant(
  api: DocumentGrantApi,
  userBoundary: string,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (grantId: string) => api.revokeGrant(grantId),
    onError: (error) =>
      refreshGrantRecordsOnFailure(error, queryClient, userBoundary),
    onSuccess: async (grant) => {
      await Promise.all([
        invalidateDocumentGrantList(queryClient, userBoundary),
        invalidateRelatedDocumentFacts(queryClient, userBoundary, [
          grant.documentId,
        ]),
      ])
    },
  })
}
