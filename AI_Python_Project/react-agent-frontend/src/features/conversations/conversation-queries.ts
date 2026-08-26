import {
  type InfiniteData,
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from '@tanstack/react-query'

import type { ConversationApi } from '@/features/conversations/conversation-api'
import type {
  ConversationMessagePage,
  ConversationPage,
} from '@/features/conversations/conversation-models'


export interface ConversationListKeyParams {
  limit: number
}

export interface ConversationMessageKeyParams {
  limit: number
}

export const conversationKeys = {
  listRoot: (userBoundary: string) =>
    [userBoundary, 'conversations'] as const,
  list: (userBoundary: string, params: ConversationListKeyParams) =>
    [...conversationKeys.listRoot(userBoundary), params] as const,
  messageRoot: (userBoundary: string, sessionId: string) =>
    [userBoundary, 'conversation-messages', sessionId] as const,
  messages: (
    userBoundary: string,
    sessionId: string,
    params: ConversationMessageKeyParams,
  ) => [...conversationKeys.messageRoot(userBoundary, sessionId), params] as const,
}

export const CONVERSATION_LIST_LIMIT = 20
export const CONVERSATION_MESSAGE_LIMIT = 50

export function useConversationList(
  api: ConversationApi,
  userBoundary: string,
) {
  return useInfiniteQuery<
    ConversationPage,
    Error,
    InfiniteData<ConversationPage>,
    ReturnType<typeof conversationKeys.list>,
    string | null
  >({
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api.listConversations({
        cursor: pageParam,
        limit: CONVERSATION_LIST_LIMIT,
        signal,
      }),
    queryKey: conversationKeys.list(userBoundary, {
      limit: CONVERSATION_LIST_LIMIT,
    }),
  })
}

export function useConversationMessages(
  api: ConversationApi,
  userBoundary: string,
  sessionId: string | null,
) {
  return useInfiniteQuery<
    ConversationMessagePage,
    Error,
    InfiniteData<ConversationMessagePage>,
    ReturnType<typeof conversationKeys.messages>,
    string | null
  >({
    enabled: sessionId !== null,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api.listMessages(sessionId ?? '', {
        cursor: pageParam,
        limit: CONVERSATION_MESSAGE_LIMIT,
        signal,
      }),
    queryKey: conversationKeys.messages(
      userBoundary,
      sessionId ?? '__no-session__',
      { limit: CONVERSATION_MESSAGE_LIMIT },
    ),
  })
}

export function useCreateConversation(
  api: ConversationApi,
  userBoundary: string,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (title?: string) => api.createConversation(title),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: conversationKeys.listRoot(userBoundary),
      }),
  })
}

export function useRenameConversation(
  api: ConversationApi,
  userBoundary: string,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId, title }: { sessionId: string; title: string }) =>
      api.renameConversation(sessionId, title),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: conversationKeys.listRoot(userBoundary),
      }),
  })
}

export function useDeleteConversation(
  api: ConversationApi,
  userBoundary: string,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => api.deleteConversation(sessionId),
    onSuccess: async (_, sessionId) => {
      queryClient.removeQueries({
        queryKey: conversationKeys.messageRoot(userBoundary, sessionId),
      })
      await queryClient.invalidateQueries({
        queryKey: conversationKeys.listRoot(userBoundary),
      })
    },
  })
}
