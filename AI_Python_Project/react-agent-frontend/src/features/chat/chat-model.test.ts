import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api/api-error'
import type { PublicEvent } from '@/api/sse/public-events'
import {
  buildChatRequest,
  chatReducer,
  createInitialChatState,
  queryErrorMessage,
} from '@/features/chat/chat-model'


function event(value: Record<string, unknown>): PublicEvent {
  return {
    contractVersion: '1.0',
    receivedAt: 1,
    requestId: 'request-1',
    ...value,
  } as PublicEvent
}

describe('Chat model', () => {
  it('builds the approved request body and forces Web fields off without capability', () => {
    expect(
      buildChatRequest({
        allowDirectWeb: true,
        allowWebFallback: true,
        canUseWebSearch: false,
        query: '如何验证检索结果？',
        sessionId: 'session-1',
      }),
    ).toEqual({
      allow_direct_web: false,
      allow_web_fallback: false,
      min_score: 0,
      mode: 'hybrid',
      query: '如何验证检索结果？',
      session_id: 'session-1',
      top_k: 5,
    })

    expect(
      buildChatRequest({
        allowDirectWeb: true,
        allowWebFallback: true,
        canUseWebSearch: true,
        query: '公开信息',
        sessionId: null,
      }),
    ).toEqual({
      allow_direct_web: true,
      allow_web_fallback: true,
      min_score: 0,
      mode: 'hybrid',
      query: '公开信息',
      top_k: 5,
    })
  })

  it('maps only the safe query validation projection to the composer', () => {
    const error = new ApiError({
      code: 'REQUEST_VALIDATION_ERROR',
      fieldErrors: [
        { code: 'too_short', field: 'query', message: '问题不能为空' },
        { code: 'invalid', field: 'session_id', message: '不得展示' },
      ],
      message: '请求参数不合法',
      requestId: 'request-1',
      status: 422,
      statusKind: 'validation',
    })

    expect(queryErrorMessage(error)).toBe('问题不能为空')
    expect(queryErrorMessage(new Error('network'))).toBeNull()
  })

  it('binds the request before connecting and ignores mismatched or terminal-late events', () => {
    let state = chatReducer(createInitialChatState(), {
      query: '问题',
      requestId: 'request-1',
      type: 'start',
    })
    expect(state).toMatchObject({
      answer: '',
      query: '问题',
      requestId: 'request-1',
      status: 'connecting',
    })

    state = chatReducer(state, {
      event: event({ event: 'answer_delta', text: '第一段' }),
      type: 'event',
    })
    expect(state).toMatchObject({ answer: '第一段', status: 'streaming' })

    state = chatReducer(state, {
      event: { ...event({ event: 'answer_delta', text: '错误流' }), requestId: 'request-2' },
      type: 'event',
    })
    expect(state.answer).toBe('第一段')

    state = chatReducer(state, {
      event: event({ event: 'done', stale: true, status: 'done' }),
      type: 'event',
    })
    expect(state).toMatchObject({ stale: true, status: 'completed' })

    state = chatReducer(state, {
      event: event({ event: 'answer_delta', text: '迟到内容' }),
      type: 'event',
    })
    expect(state.answer).toBe('第一段')
  })

  it('keeps only the safe unknown-event projection in the timeline', () => {
    const started = chatReducer(createInitialChatState(), {
      query: '问题',
      requestId: 'request-1',
      type: 'start',
    })
    const state = chatReducer(started, {
      event: {
        event: 'future_event',
        kind: 'unknown',
        receivedAt: 2,
        requestId: 'request-1',
        status: 'unsupported_event',
      },
      type: 'event',
    })

    expect(state.timeline).toEqual([
      {
        event: 'future_event',
        receivedAt: 2,
        requestId: 'request-1',
        status: 'unsupported_event',
      },
    ])
  })

  it('projects sources, clarification and TaskPlan references into dedicated state', () => {
    let state = chatReducer(createInitialChatState(), {
      query: '复杂任务',
      requestId: 'request-1',
      type: 'start',
    })
    state = chatReducer(state, {
      event: event({
        event: 'sources',
        sources: [
          {
            contentPreview: '公开预览',
            docId: null,
            href: 'https://example.test/source',
            id: 'source-1',
            score: 0.8,
            sectionPath: [],
            source: 'web',
            sourceRevision: null,
            sourceType: 'web',
            title: '公开来源',
          },
        ],
      }),
      type: 'event',
    })
    state = chatReducer(state, {
      event: event({
        code: 'NEED_SCOPE',
        confidence: 0.4,
        event: 'agent_route_clarification_required',
        question: '请说明时间范围',
      }),
      type: 'event',
    })
    state = chatReducer(state, {
      event: event({
        event: 'agent_task_plan_created',
        status: 'pending',
        taskPlanId: 'task-1',
      }),
      type: 'event',
    })

    expect(state.sources).toHaveLength(1)
    expect(state.clarification).toBe('请说明时间范围')
    expect(state.taskPlanId).toBe('task-1')
    expect(state.timeline.map((item) => item.event)).toEqual([
      'agent_route_clarification_required',
      'agent_task_plan_created',
    ])
  })

  it('isolates late events after cancellation and resets at a session boundary', () => {
    let state = chatReducer(createInitialChatState(), {
      query: '旧会话问题',
      requestId: 'request-1',
      type: 'start',
    })
    state = chatReducer(state, { requestId: 'request-1', type: 'cancel' })
    state = chatReducer(state, {
      event: event({ event: 'answer_delta', text: '迟到内容' }),
      type: 'event',
    })
    expect(state).toMatchObject({ answer: '', status: 'cancelled' })

    state = chatReducer(state, { type: 'reset' })
    expect(state).toEqual(createInitialChatState())
  })

  it('treats error as the failure terminal without waiting for done', () => {
    let state = chatReducer(createInitialChatState(), {
      query: '失败问题',
      requestId: 'request-1',
      type: 'start',
    })
    state = chatReducer(state, {
      event: event({
        code: 'RAG_FAILED',
        errorCategory: 'system_error',
        event: 'error',
        message: '请求安全失败',
      }),
      type: 'event',
    })
    expect(state).toMatchObject({
      errorMessage: '请求安全失败',
      status: 'failed',
    })

    state = chatReducer(state, {
      event: event({ event: 'done', status: 'done' }),
      type: 'event',
    })
    expect(state.status).toBe('failed')
  })
})
