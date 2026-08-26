import type { HttpClient } from '@/api/http-client'
import type {
  ConversationItemDto,
  ConversationListResponseDto,
  ConversationMessageListResponseDto,
  CreateConversationRequestDto,
  UpdateConversationRequestDto,
} from '@/features/conversations/conversation-contracts'
import {
  mapConversationMessagePage,
  mapConversationPage,
  type ConversationMessagePage,
  type ConversationPage,
  type ConversationSummary,
} from '@/features/conversations/conversation-models'


export interface ConversationPageRequest {
  cursor: string | null
  limit: number
  signal?: AbortSignal
}

export interface ConversationApi {
  createConversation(title?: string): Promise<ConversationSummary>
  deleteConversation(sessionId: string): Promise<void>
  listConversations(request: ConversationPageRequest): Promise<ConversationPage>
  listMessages(
    sessionId: string,
    request: ConversationPageRequest,
  ): Promise<ConversationMessagePage>
  renameConversation(
    sessionId: string,
    title: string,
  ): Promise<ConversationSummary>
}

function pagePath(path: string, request: ConversationPageRequest): string {
  const search = new URLSearchParams()
  if (request.cursor !== null) search.set('cursor', request.cursor)
  search.set('limit', String(request.limit))
  return `${path}?${search.toString()}`
}

function sessionPath(sessionId: string): string {
  return `/conversations/${encodeURIComponent(sessionId)}`
}

export function createConversationApi(httpClient: HttpClient): ConversationApi {
  return {
    async createConversation(title) {
      const body: CreateConversationRequestDto =
        title === undefined ? {} : { title }
      const response = await httpClient.request<ConversationItemDto>(
        '/conversations',
        { json: body, method: 'POST' },
      )
      return mapConversationPage({ items: [response.data] }).items[0]
    },

    async deleteConversation(sessionId) {
      await httpClient.request(sessionPath(sessionId), {
        method: 'DELETE',
        responseType: 'empty',
      })
    },

    async listConversations(request) {
      const response = await httpClient.request<ConversationListResponseDto>(
        pagePath('/conversations', request),
        { signal: request.signal },
      )
      return mapConversationPage(response.data)
    },

    async listMessages(sessionId, request) {
      const response =
        await httpClient.request<ConversationMessageListResponseDto>(
          pagePath(`${sessionPath(sessionId)}/messages`, request),
          { signal: request.signal },
        )
      return mapConversationMessagePage(response.data)
    },

    async renameConversation(sessionId, title) {
      const body: UpdateConversationRequestDto = { title }
      const response = await httpClient.request<ConversationItemDto>(
        sessionPath(sessionId),
        { json: body, method: 'PATCH' },
      )
      return mapConversationPage({ items: [response.data] }).items[0]
    },
  }
}
