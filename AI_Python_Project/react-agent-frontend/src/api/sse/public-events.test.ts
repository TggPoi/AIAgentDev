import { describe, expect, it } from 'vitest'

import {
  getTerminalKind,
  parsePublicEvent,
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
