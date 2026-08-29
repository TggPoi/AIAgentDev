import { describe, expect, it } from 'vitest'

import { parseTaskPlanPublicEvent } from '@/api/sse/public-events'
import {
  createInitialTaskPlanStreamState,
  taskPlanStreamReducer,
} from '@/features/task-plans/task-plan-stream-model'


describe('TaskPlan stream reducer', () => {
  it('binds the action before applying a typed status event', () => {
    let state = taskPlanStreamReducer(createInitialTaskPlanStreamState(), {
      requestId: 'request-1',
      taskPlanId: 'task-plan-1',
      type: 'start',
    })
    expect(state).toMatchObject({
      requestId: 'request-1',
      status: 'connecting',
      taskPlanId: 'task-plan-1',
      taskStatus: null,
    })

    const event = parseTaskPlanPublicEvent(
      {
        data: JSON.stringify({
          contract_version: '1.0',
          request_id: 'request-1',
          status: 'executing_confirmed',
          task_plan_id: 'task-plan-1',
        }),
        event: 'agent_task_status',
        receivedAt: 10,
      },
      'request-1',
    )
    state = taskPlanStreamReducer(state, { event, type: 'event' })

    expect(state).toMatchObject({
      status: 'streaming',
      taskStatus: 'executing_confirmed',
    })
    expect(state.timeline).toEqual([
      {
        event: 'agent_task_status',
        receivedAt: 10,
        requestId: 'request-1',
      },
    ])
  })

  it('reduces safe output, progress and the successful terminal', () => {
    let state = taskPlanStreamReducer(createInitialTaskPlanStreamState(), {
      requestId: 'request-1',
      taskPlanId: 'task-plan-1',
      type: 'start',
    })
    const event = (name: string, payload: Record<string, unknown>) =>
      parseTaskPlanPublicEvent(
        {
          data: JSON.stringify({
            contract_version: '1.0',
            request_id: 'request-1',
            task_plan_id: 'task-plan-1',
            ...payload,
          }),
          event: name,
          receivedAt: 20,
        },
        'request-1',
      )

    state = taskPlanStreamReducer(state, {
      event: event('answer_delta', { text: '公开结论' }),
      type: 'event',
    })
    state = taskPlanStreamReducer(state, {
      event: event('sources', {
        sources: [
          {
            content_preview: '公开预览',
            doc_id: 'doc-1',
            href: null,
            id: 'source-1',
            score: 0.9,
            section_path: [],
            source: 'elasticsearch',
            source_revision: 'revision-1',
            source_type: 'knowledge_document',
            title: '公开文档',
          },
        ],
      }),
      type: 'event',
    })
    state = taskPlanStreamReducer(state, {
      event: event('agent_task_research_worker_progress', {
        active_operation_count: 1,
        stage: 'answer_generation',
        status: 'running',
      }),
      type: 'event',
    })
    state = taskPlanStreamReducer(state, {
      event: event('done', {
        status: 'done',
        task_status: 'completed',
      }),
      type: 'event',
    })

    expect(state).toMatchObject({
      answer: '公开结论',
      status: 'completed',
      taskStatus: 'completed',
    })
    expect(state.sources).toHaveLength(1)
    expect(state.timeline.map((item) => item.event)).toContain(
      'agent_task_research_worker_progress',
    )
  })

  it('isolates plan IDs, projects unknown events and stops on error', () => {
    let state = taskPlanStreamReducer(createInitialTaskPlanStreamState(), {
      requestId: 'request-1',
      taskPlanId: 'task-plan-1',
      type: 'start',
    })
    const parsed = (
      event: string,
      taskPlanId: string,
      payload: Record<string, unknown>,
    ) =>
      parseTaskPlanPublicEvent(
        {
          data: JSON.stringify({
            contract_version: '1.0',
            request_id: 'request-1',
            task_plan_id: taskPlanId,
            ...payload,
          }),
          event,
          receivedAt: 30,
        },
        'request-1',
      )

    state = taskPlanStreamReducer(state, {
      event: parsed('agent_task_status', 'other-plan', {
        status: 'completed',
      }),
      type: 'event',
    })
    expect(state.taskStatus).toBeNull()

    state = taskPlanStreamReducer(state, {
      event: parsed('future_sensitive_event', 'task-plan-1', {
        credential: 'must-not-be-retained',
      }),
      type: 'event',
    })
    expect(state.timeline.at(-1)).toEqual({
      event: 'future_sensitive_event',
      receivedAt: 30,
      requestId: 'request-1',
      status: 'unsupported_event',
    })
    expect(JSON.stringify(state)).not.toContain('must-not-be-retained')

    state = taskPlanStreamReducer(state, {
      event: parsed('error', 'task-plan-1', {
        code: 'TASK_PLAN_FAILED',
        error_category: 'system_error',
        message: 'TaskPlan 执行失败',
        trace_id: null,
      }),
      type: 'event',
    })
    state = taskPlanStreamReducer(state, {
      event: parsed('answer_delta', 'task-plan-1', { text: '迟到回答' }),
      type: 'event',
    })

    expect(state).toMatchObject({
      answer: '',
      errorMessage: 'TaskPlan 执行失败',
      status: 'failed',
    })
  })
})
