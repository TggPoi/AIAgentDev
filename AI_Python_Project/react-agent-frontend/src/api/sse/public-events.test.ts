import { describe, expect, it } from 'vitest'

import {
  getTerminalKind,
  parsePublicEvent,
  parseTaskPlanPublicEvent,
  PublicEventProtocolError,
} from '@/api/sse/public-events'
import type { SseFrame } from '@/api/sse/parser'

function frame(event: string, data: unknown): SseFrame {
  return {
    data: JSON.stringify(data),
    event,
    receivedAt: 100,
  }
}

describe('parsePublicEvent', () => {
  it('validates a known event envelope and payload', () => {
    const event = parsePublicEvent(
      frame('answer_delta', {
        contract_version: '1.0',
        request_id: 'request-1',
        text: 'answer',
      }),
      'request-1',
    )

    expect(event).toEqual({
      contractVersion: '1.0',
      event: 'answer_delta',
      receivedAt: 100,
      requestId: 'request-1',
      text: 'answer',
    })
  })

  it('rejects mismatched request IDs and versions without exposing payloads', () => {
    const unsafe = frame('answer_delta', {
      contract_version: '2.0',
      request_id: 'wrong-request',
      secret: 'must-not-appear',
      text: 'answer',
    })

    expect(() => parsePublicEvent(unsafe, 'request-1')).toThrow(
      PublicEventProtocolError,
    )
    try {
      parsePublicEvent(unsafe, 'request-1')
    } catch (error) {
      expect(String(error)).not.toContain('must-not-appear')
    }
  })

  it('immediately reduces unknown events to the safe allowlist', () => {
    const event = parsePublicEvent(
      frame('future_sensitive_event', {
        contract_version: '1.0',
        request_id: 'request-1',
        prompt: 'private prompt',
        credentials: 'private credential',
      }),
      'request-1',
    )

    expect(event).toEqual({
      event: 'future_sensitive_event',
      kind: 'unknown',
      receivedAt: 100,
      requestId: 'request-1',
      status: 'unsupported_event',
    })
    expect(JSON.stringify(event)).not.toContain('private')
  })

  it('projects known sources without retaining arbitrary metadata', () => {
    const event = parsePublicEvent(
      frame('sources', {
        contract_version: '1.0',
        request_id: 'request-1',
        sources: [
          {
            content_preview: 'safe preview',
            doc_id: 'doc-1',
            href: null,
            id: 'chunk-1',
            metadata: { internal_url: 'private service' },
            score: 0.9,
            section_path: ['Guide'],
            source: 'elasticsearch',
            source_revision: 'revision-1',
            source_type: 'knowledge_document',
            title: 'Guide',
          },
        ],
      }),
      'request-1',
    )

    expect(event.event).toBe('sources')
    expect(JSON.stringify(event)).not.toContain('private service')
  })

  it('recognizes approved TaskPlan progress names through a safe reference', () => {
    const event = parsePublicEvent(
      frame('agent_task_execution_started', {
        contract_version: '1.0',
        request_id: 'request-1',
        task_plan_id: 'task-plan-1',
        tool_arguments: 'must-not-be-retained',
      }),
      'request-1',
    )

    expect(event).toEqual({
      contractVersion: '1.0',
      event: 'agent_task_execution_started',
      receivedAt: 100,
      requestId: 'request-1',
      taskPlanId: 'task-plan-1',
    })
  })

  it('centralizes success and failure terminal semantics', () => {
    const done = parsePublicEvent(
      frame('done', {
        contract_version: '1.0',
        request_id: 'request-1',
        status: 'done',
      }),
      'request-1',
    )
    const failed = parsePublicEvent(
      frame('error', {
        code: 'FAILED',
        contract_version: '1.0',
        error_category: 'system_error',
        message: 'failed safely',
        request_id: 'request-1',
      }),
      'request-1',
    )

    expect(getTerminalKind(done)).toBe('success')
    expect(getTerminalKind(failed)).toBe('failure')
  })
})

describe('parseTaskPlanPublicEvent', () => {
  it('projects the generated status event without retaining extra payload', () => {
    const event = parseTaskPlanPublicEvent(
      frame('agent_task_status', {
        contract_version: '1.0',
        request_id: 'request-1',
        status: 'executing_confirmed',
        task_plan_id: 'task-plan-1',
        tool_arguments: 'must-not-be-retained',
      }),
      'request-1',
    )

    expect(event).toEqual({
      contractVersion: '1.0',
      event: 'agent_task_status',
      receivedAt: 100,
      requestId: 'request-1',
      status: 'executing_confirmed',
      taskPlanId: 'task-plan-1',
    })
    expect(JSON.stringify(event)).not.toContain('must-not-be-retained')
  })

  it('projects each generated progress category through explicit fields', () => {
    const cases = [
      {
        expected: {
          activeOperationCount: 2,
          event: 'agent_task_research_worker_progress',
          stage: 'tool_execution',
          status: 'running',
          subQuestionId: 'sq-1',
          taskPlanId: 'task-plan-1',
          toolCallCount: 3,
          wave: 1,
        },
        frame: frame('agent_task_research_worker_progress', {
          active_operation_count: 2,
          contract_version: '1.0',
          request_id: 'request-1',
          stage: 'tool_execution',
          status: 'running',
          sub_question_id: 'sq-1',
          task_plan_id: 'task-plan-1',
          tool_call_count: 3,
          wave: 1,
        }),
      },
      {
        expected: {
          confidence: 0.9,
          event: 'agent_task_document_review_completed',
          status: 'completed',
          taskPlanId: 'task-plan-1',
          verdict: 'approved',
        },
        frame: frame('agent_task_document_review_completed', {
          confidence: 0.9,
          contract_version: '1.0',
          request_id: 'request-1',
          status: 'completed',
          task_plan_id: 'task-plan-1',
          verdict: 'approved',
        }),
      },
      {
        expected: {
          event: 'requirement_satisfied',
          evidenceCount: 4,
          reasonCodes: ['ENOUGH_EVIDENCE'],
          requirementId: 'requirement-1',
          status: 'satisfied',
          taskPlanId: 'task-plan-1',
        },
        frame: frame('requirement_satisfied', {
          contract_version: '1.0',
          evidence_count: 4,
          reason_codes: ['ENOUGH_EVIDENCE'],
          request_id: 'request-1',
          requirement_id: 'requirement-1',
          status: 'satisfied',
          task_plan_id: 'task-plan-1',
        }),
      },
      {
        expected: {
          errorCode: null,
          event: 'agent_task_step_completed',
          status: 'completed',
          stepId: 'step-1',
          taskPlanId: 'task-plan-1',
          toolName: 'knowledge_document_create',
        },
        frame: frame('agent_task_step_completed', {
          contract_version: '1.0',
          error_code: null,
          request_id: 'request-1',
          status: 'completed',
          step_id: 'step-1',
          task_plan_id: 'task-plan-1',
          tool_name: 'knowledge_document_create',
        }),
      },
      {
        expected: {
          errorCode: null,
          event: 'sub_question_completed',
          evidenceCount: 2,
          status: 'completed',
          subQuestionId: 'sq-1',
          taskPlanId: 'task-plan-1',
        },
        frame: frame('sub_question_completed', {
          contract_version: '1.0',
          error_code: null,
          evidence_count: 2,
          request_id: 'request-1',
          status: 'completed',
          sub_question_id: 'sq-1',
          task_plan_id: 'task-plan-1',
        }),
      },
    ]

    for (const item of cases) {
      expect(parseTaskPlanPublicEvent(item.frame, 'request-1')).toMatchObject({
        contractVersion: '1.0',
        receivedAt: 100,
        requestId: 'request-1',
        ...item.expected,
      })
    }
  })

  it('projects execution, output, guard and terminal frame categories', () => {
    const cases = [
      {
        event: 'agent_task_execution_started',
        expected: { taskPlanId: 'task-plan-1' },
        payload: {},
      },
      {
        event: 'agent_task_final_synthesis_completed',
        expected: {
          status: 'completed_with_warnings',
          taskPlanId: 'task-plan-1',
          usedToolCount: 2,
          warningCount: 1,
        },
        payload: {
          status: 'completed_with_warnings',
          used_tool_count: 2,
          warning_count: 1,
        },
      },
      {
        event: 'answer_delta',
        expected: { taskPlanId: 'task-plan-1', text: '公开回答' },
        payload: { text: '公开回答' },
      },
      {
        event: 'sources',
        expected: {
          sources: [
            expect.objectContaining({
              docId: 'doc-1',
              id: 'source-1',
              sourceType: 'knowledge_document',
            }),
          ],
          taskPlanId: 'task-plan-1',
        },
        payload: {
          sources: [
            {
              content_preview: '公开预览',
              doc_id: 'doc-1',
              href: null,
              id: 'source-1',
              score: 0.8,
              section_path: ['Guide'],
              source: 'elasticsearch',
              source_revision: 'revision-1',
              source_type: 'knowledge_document',
              title: 'Guide',
            },
          ],
        },
      },
      {
        event: 'guard_sanitized',
        expected: {
          action: 'sanitize',
          categories: ['prompt_injection'],
          reason: '已安全净化',
          riskLevel: 'medium',
          taskPlanId: 'task-plan-1',
          text: '已净化文本',
        },
        payload: {
          action: 'sanitize',
          categories: ['prompt_injection'],
          reason: '已安全净化',
          risk_level: 'medium',
          text: '已净化文本',
        },
      },
      {
        event: 'done',
        expected: {
          status: 'done',
          taskPlanId: 'task-plan-1',
          taskStatus: 'completed',
        },
        payload: { status: 'done', task_status: 'completed' },
      },
      {
        event: 'error',
        expected: {
          code: 'TASK_PLAN_FAILED',
          errorCategory: 'system_error',
          message: 'TaskPlan 执行失败',
          taskPlanId: 'task-plan-1',
          traceId: 'trace-1',
        },
        payload: {
          code: 'TASK_PLAN_FAILED',
          error_category: 'system_error',
          message: 'TaskPlan 执行失败',
          trace_id: 'trace-1',
        },
      },
    ]

    for (const item of cases) {
      const event = parseTaskPlanPublicEvent(
        frame(item.event, {
          contract_version: '1.0',
          request_id: 'request-1',
          task_plan_id: 'task-plan-1',
          ...item.payload,
        }),
        'request-1',
      )
      expect(event).toMatchObject({
        contractVersion: '1.0',
        event: item.event,
        requestId: 'request-1',
        ...item.expected,
      })
    }
  })
})
