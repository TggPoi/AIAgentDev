import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'

import { createHttpClient } from '@/api/http-client'
import { createTaskPlanApi } from '@/features/task-plans/task-plan-api'
import type { TaskPlanDetailDto } from '@/features/task-plans/task-plan-contracts'
import {
  mapTaskPlanDetail,
  mergeTaskPlanPages,
  type TaskPlanSummary,
} from '@/features/task-plans/task-plan-models'
import { taskPlanKeys } from '@/features/task-plans/task-plan-queries'
import { server } from '@/test/server'


const apiBaseUrl = 'http://task-plans.test'

function createApi() {
  return createTaskPlanApi(
    createHttpClient({
      baseUrl: apiBaseUrl,
      getAccessToken: () => null,
      requestIdFactory: () => 'task-plan-request-id',
    }),
  )
}

function summary(taskPlanId: string): TaskPlanSummary {
  return {
    createdAt: '2026-08-29T01:00:00Z',
    errorCode: null,
    requiresConfirmation: true,
    sessionId: 'session-a',
    status: 'waiting_confirmation',
    summary: `计划 ${taskPlanId}`,
    taskKind: 'question_decomposition',
    taskPlanId,
    updatedAt: '2026-08-29T02:00:00Z',
  }
}

function researchDetailDto(): TaskPlanDetailDto {
  return {
    task_kind: 'question_decomposition',
    task_plan_id: 'research-1',
    schema_version: 2,
    status: 'waiting_confirmation',
    session_id: 'session-a',
    task_type: 'analysis',
    source_query: '比较两个公开方案',
    objective: '形成有证据的比较结论',
    requirements: [],
    sub_questions: [],
    final_synthesis_instruction: '只使用已验证证据',
    capability_snapshot: {
      available_source_types: ['knowledge_retrieval', 'web_search'],
      knowledge_retrieval_available: true,
      nl2sql_query_available: false,
      web_direct_allowed: true,
      web_fallback_allowed: false,
    },
    quality_review: {
      verdict: 'accepted',
      checks: {
        semantic_alignment: 'pass',
        requirement_coverage: 'pass',
        source_alignment: 'pass',
        dependency_quality: 'pass',
        executability: 'pass',
        completion_policy_alignment: 'pass',
      },
      revision_count: 0,
    },
    validation_issues: [],
    progress: { current_wave: 0, events: [], workers: {} },
    sub_question_results: [],
    evidence: [],
    requirement_evidence_statuses: [],
    final_output: null,
    error_code: null,
    error_message: null,
    created_at: '2026-08-29T01:00:00Z',
    updated_at: '2026-08-29T02:00:00Z',
  }
}

function documentDetailDto(): TaskPlanDetailDto {
  return {
    task_kind: 'knowledge_document_management',
    task_plan_id: 'document-1',
    status: 'waiting_confirmation',
    session_id: null,
    task_type: 'report_generation',
    objective: '生成公开报告',
    requires_confirmation: true,
    steps: [
      {
        step_id: 'step-1',
        tool_name: 'knowledge_document_create',
        status: 'pending',
        requires_confirmation: true,
        risk_level: 'medium',
        error_code: null,
      },
    ],
    result_summary: {
      total_steps: 1,
      completed_steps: 0,
      failed_steps: 0,
      skipped_steps: 0,
    },
    error_code: null,
    created_at: '2026-08-29T01:00:00Z',
    updated_at: '2026-08-29T02:00:00Z',
  }
}

describe('TaskPlan private query keys', () => {
  it('isolates list, detail and markdown facts by authenticated user', () => {
    expect(taskPlanKeys.listRoot('user-a')).not.toEqual(
      taskPlanKeys.listRoot('user-b'),
    )
    expect(taskPlanKeys.detail('user-a', 'shared-plan')).not.toEqual(
      taskPlanKeys.detail('user-b', 'shared-plan'),
    )
    expect(taskPlanKeys.markdown('user-a', 'shared-plan')).not.toEqual(
      taskPlanKeys.markdown('user-b', 'shared-plan'),
    )
  })
})

describe('TaskPlan keyset page merge', () => {
  it('preserves server order and keeps the first occurrence of each plan', () => {
    expect(
      mergeTaskPlanPages([
        {
          items: [summary('task-b'), summary('task-a')],
          nextCursor: 'opaque+/=',
        },
        {
          items: [summary('task-a'), summary('task-c')],
          nextCursor: null,
        },
      ]).map((item) => item.taskPlanId),
    ).toEqual(['task-b', 'task-a', 'task-c'])
  })
})

describe('TaskPlan detail adapter', () => {
  it('keeps research and document details as distinct complete models', () => {
    const research = mapTaskPlanDetail(researchDetailDto())
    const document = mapTaskPlanDetail(documentDetailDto())

    expect(research).toMatchObject({
      kind: 'research',
      objective: '形成有证据的比较结论',
      sourceQuery: '比较两个公开方案',
      taskKind: 'question_decomposition',
      taskPlanId: 'research-1',
    })
    expect(research.kind === 'research' && research.schemaVersion).toBe(2)
    expect(document).toMatchObject({
      kind: 'document',
      objective: '生成公开报告',
      requiresConfirmation: true,
      taskKind: 'knowledge_document_management',
      taskPlanId: 'document-1',
    })
    expect(document.kind === 'document' && document.steps[0]).toMatchObject({
      riskLevel: 'medium',
      stepId: 'step-1',
    })
  })
})

describe('TaskPlan HTTP adapter', () => {
  it('passes opaque filters and maps list/detail/Markdown responses', async () => {
    server.use(
      http.get(`${apiBaseUrl}/agent/task-plans`, ({ request }) => {
        const url = new URL(request.url)
        expect(url.searchParams.get('cursor')).toBe('opaque+/=')
        expect(url.searchParams.get('limit')).toBe('20')
        expect(url.searchParams.get('status')).toBe('waiting_confirmation')
        expect(url.searchParams.get('session_id')).toBe('session/a')
        return HttpResponse.json({
          items: [
            {
              task_plan_id: 'research-1',
              task_kind: 'question_decomposition',
              status: 'waiting_confirmation',
              session_id: 'session/a',
              summary: '公开计划摘要',
              requires_confirmation: true,
              error_code: null,
              created_at: '2026-08-29T01:00:00Z',
              updated_at: '2026-08-29T02:00:00Z',
            },
          ],
          next_cursor: 'next-cursor',
        })
      }),
      http.get(`${apiBaseUrl}/agent/task-plans/research-1`, () =>
        HttpResponse.json(researchDetailDto()),
      ),
      http.get(`${apiBaseUrl}/agent/task-plans/research-1/markdown`, () =>
        HttpResponse.text('# 审查计划', {
          headers: { 'Content-Type': 'text/plain; charset=utf-8' },
        }),
      ),
    )

    const api = createApi()
    const page = await api.listTaskPlans({
      cursor: 'opaque+/=',
      limit: 20,
      sessionId: 'session/a',
      status: 'waiting_confirmation',
    })
    const detail = await api.getTaskPlan('research-1')
    const markdown = await api.getTaskPlanMarkdown('research-1')

    expect(page.nextCursor).toBe('next-cursor')
    expect(page.items[0]).toMatchObject({
      sessionId: 'session/a',
      taskPlanId: 'research-1',
    })
    expect(detail.kind).toBe('research')
    expect(markdown).toBe('# 审查计划')
  })
})
