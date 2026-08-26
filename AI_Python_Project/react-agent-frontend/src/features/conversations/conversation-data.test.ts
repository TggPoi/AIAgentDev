import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { createHttpClient } from '@/api/http-client'
import { createConversationApi } from '@/features/conversations/conversation-api'
import {
  mergeConversationPages,
  mergeMessagePages,
} from '@/features/conversations/conversation-models'
import { conversationKeys } from '@/features/conversations/conversation-queries'
import { server } from '@/test/server'


const apiBaseUrl = 'http://conversations.test'

function createApi() {
  return createConversationApi(
    createHttpClient({
      baseUrl: apiBaseUrl,
      getAccessToken: () => null,
      requestIdFactory: () => 'conversation-request-id',
    }),
  )
}

function conversationDto(sessionId: string, title: string) {
  return {
    session_id: sessionId,
    title,
    created_at: '2026-08-26T01:00:00Z',
    updated_at: '2026-08-26T02:00:00Z',
    message_count: 2,
    last_message_role: 'assistant' as const,
    last_message_preview: '已持久化回答',
  }
}

function conversation(sessionId: string, title: string) {
  return {
    createdAt: '2026-08-26T01:00:00Z',
    kind: 'conversation' as const,
    lastMessagePreview: '已持久化回答',
    lastMessageRole: 'assistant' as const,
    messageCount: 2,
    sessionId,
    title,
    updatedAt: '2026-08-26T02:00:00Z',
  }
}

describe('conversation private query keys', () => {
  it('isolates the same session id and list params by authenticated user', () => {
    expect(conversationKeys.list('user-a', { limit: 20 })).not.toEqual(
      conversationKeys.list('user-b', { limit: 20 }),
    )
    expect(
      conversationKeys.messages('user-a', 'shared-session', { limit: 50 }),
    ).not.toEqual(
      conversationKeys.messages('user-b', 'shared-session', { limit: 50 }),
    )
  })
})

describe('conversation keyset page merge', () => {
  it('preserves server order and keeps the first occurrence of each conversation', () => {
    const first = {
      items: [
        conversation('session-b', 'B'),
        conversation('session-a', 'A'),
      ],
      nextCursor: 'cursor-2',
    }
    const second = {
      items: [
        conversation('session-a', 'A duplicate'),
        conversation('session-c', 'C'),
      ],
      nextCursor: null,
    }

    expect(mergeConversationPages([first, second]).map((item) => item.sessionId)).toEqual([
      'session-b',
      'session-a',
      'session-c',
    ])
  })

  it('deduplicates persisted messages without re-sorting server pages', () => {
    const message = (messageId: string, sequenceNo: number) => ({
      agentTaskPlanId: null,
      agentTaskStatus: null,
      content: messageId,
      createdAt: '2026-08-26T01:00:00Z',
      kind: 'persisted' as const,
      messageId,
      role: 'user' as const,
      sequenceNo,
      sources: [],
      terminalStatus: 'completed' as const,
    })

    expect(
      mergeMessagePages([
        { items: [message('m-1', 1), message('m-2', 2)], nextCursor: 'next' },
        { items: [message('m-2', 2), message('m-3', 3)], nextCursor: null },
      ]).map((item) => item.messageId),
    ).toEqual(['m-1', 'm-2', 'm-3'])
  })
})

describe('conversation HTTP adapter', () => {
  it('passes opaque list cursors and maps transport fields to the domain model', async () => {
    server.use(
      http.get(`${apiBaseUrl}/conversations`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('cursor')).toBe('opaque+/=')
        expect(url.searchParams.get('limit')).toBe('20')
        return HttpResponse.json({
          items: [conversationDto('session-a', '会话 A')],
          next_cursor: 'cursor-2',
        })
      }),
    )

    const page = await createApi().listConversations({
      cursor: 'opaque+/=',
      limit: 20,
    })

    expect(page).toEqual({
      items: [
        {
          createdAt: '2026-08-26T01:00:00Z',
          kind: 'conversation',
          lastMessagePreview: '已持久化回答',
          lastMessageRole: 'assistant',
          messageCount: 2,
          sessionId: 'session-a',
          title: '会话 A',
          updatedAt: '2026-08-26T02:00:00Z',
        },
      ],
      nextCursor: 'cursor-2',
    })
  })

  it('uses the declared create, rename and empty delete contracts', async () => {
    const observed: string[] = []
    server.use(
      http.post(`${apiBaseUrl}/conversations`, async ({ request }) => {
        observed.push(`create:${JSON.stringify(await request.json())}`)
        return HttpResponse.json(conversationDto('session-new', '新会话'), {
          status: 201,
        })
      }),
      http.patch(
        `${apiBaseUrl}/conversations/session-new`,
        async ({ request }) => {
          observed.push(`rename:${JSON.stringify(await request.json())}`)
          return HttpResponse.json(conversationDto('session-new', '已重命名'))
        },
      ),
      http.delete(`${apiBaseUrl}/conversations/session-new`, () => {
        observed.push('delete')
        return new HttpResponse(null, { status: 204 })
      }),
    )

    const api = createApi()
    await api.createConversation('新会话')
    await api.renameConversation('session-new', '已重命名')
    await api.deleteConversation('session-new')

    expect(observed).toEqual([
      'create:{"title":"新会话"}',
      'rename:{"title":"已重命名"}',
      'delete',
    ])
  })

  it('restores persisted message facts while discarding arbitrary source metadata', async () => {
    server.use(
      http.get(
        `${apiBaseUrl}/conversations/session-a/messages`,
        ({ request }) => {
          const url = new URL(request.url)
          expect(url.searchParams.get('cursor')).toBe('message-cursor')
          expect(url.searchParams.get('limit')).toBe('50')
          return HttpResponse.json({
            items: [
              {
                message_id: 'message-1',
                sequence_no: 1,
                role: 'assistant',
                content: '历史回答',
                sources: [
                  {
                    id: 'source-1',
                    source: 'elasticsearch',
                    source_type: 'knowledge_document',
                    doc_id: 'doc-1',
                    href: null,
                    title: '公开标题',
                    content_preview: '公开预览',
                    score: 0.8,
                    scores: { rrf_score: 0.8 },
                    metadata: { internal_value: 'must-not-enter-domain-model' },
                  },
                ],
                agent_task_plan_id: 'task-1',
                agent_task_status: 'waiting_confirmation',
                terminal_status: 'completed',
                created_at: '2026-08-26T03:00:00Z',
              },
            ],
            next_cursor: null,
          })
        },
      ),
    )

    const page = await createApi().listMessages('session-a', {
      cursor: 'message-cursor',
      limit: 50,
    })

    expect(page.items[0]).toEqual({
      agentTaskPlanId: 'task-1',
      agentTaskStatus: 'waiting_confirmation',
      content: '历史回答',
      createdAt: '2026-08-26T03:00:00Z',
      kind: 'persisted',
      messageId: 'message-1',
      role: 'assistant',
      sequenceNo: 1,
      sources: [
        {
          contentPreview: '公开预览',
          docId: 'doc-1',
          href: null,
          id: 'source-1',
          sectionPath: [],
          sourceType: 'knowledge_document',
          title: '公开标题',
        },
      ],
      terminalStatus: 'completed',
    })
  })
})
