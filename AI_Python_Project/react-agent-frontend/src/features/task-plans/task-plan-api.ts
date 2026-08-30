import type { HttpClient } from '@/api/http-client'
import {
  parseTaskPlanPublicEvent,
  type TaskPlanPublicEvent,
} from '@/api/sse/public-events'
import { parseSseStream } from '@/api/sse/parser'
import type {
  TaskPlanConfirmRequestDto,
  TaskPlanControlResponseDto,
  TaskPlanDetailDto,
  TaskPlanListResponseDto,
} from '@/features/task-plans/task-plan-contracts'
import {
  mapTaskPlanDetail,
  mapTaskPlanPage,
  type TaskPlanDetail,
  type TaskPlanPage,
  type TaskPlanStatus,
} from '@/features/task-plans/task-plan-models'


export interface TaskPlanListRequest {
  cursor: string | null
  limit: number
  sessionId: string | null
  signal?: AbortSignal
  status: TaskPlanStatus | null
}

export interface TaskPlanApi {
  cancelTaskPlan(taskPlanId: string, idempotencyKey: string): Promise<void>
  confirmTaskPlan(
    taskPlanId: string,
    requestId: string,
    idempotencyKey: string,
    signal: AbortSignal,
  ): AsyncGenerator<TaskPlanPublicEvent>
  getTaskPlan(taskPlanId: string, signal?: AbortSignal): Promise<TaskPlanDetail>
  getTaskPlanMarkdown(taskPlanId: string, signal?: AbortSignal): Promise<string>
  listTaskPlans(request: TaskPlanListRequest): Promise<TaskPlanPage>
  retryTaskPlan(taskPlanId: string, idempotencyKey: string): Promise<void>
}

function taskPlanPath(taskPlanId: string): string {
  return `/agent/task-plans/${encodeURIComponent(taskPlanId)}`
}

function listPath(request: TaskPlanListRequest): string {
  const search = new URLSearchParams()
  if (request.cursor !== null) search.set('cursor', request.cursor)
  search.set('limit', String(request.limit))
  if (request.status !== null) search.set('status', request.status)
  if (request.sessionId !== null) search.set('session_id', request.sessionId)
  return `/agent/task-plans?${search.toString()}`
}

export function createTaskPlanApi(httpClient: HttpClient): TaskPlanApi {
  return {
    async cancelTaskPlan(taskPlanId, idempotencyKey) {
      await httpClient.request<TaskPlanControlResponseDto>(
        `${taskPlanPath(taskPlanId)}/cancel`,
        {
          headers: { 'Idempotency-Key': idempotencyKey },
          method: 'POST',
        },
      )
    },

    async *confirmTaskPlan(taskPlanId, requestId, idempotencyKey, signal) {
      const body: TaskPlanConfirmRequestDto = { confirmed: true }
      const response = await httpClient.openEventStream(
        `${taskPlanPath(taskPlanId)}/confirm/stream`,
        {
          headers: { 'Idempotency-Key': idempotencyKey },
          json: body,
          method: 'POST',
          requestId,
          signal,
        },
      )
      for await (const frame of parseSseStream(response.body)) {
        yield parseTaskPlanPublicEvent(frame, requestId)
      }
    },

    async getTaskPlan(taskPlanId, signal) {
      const response = await httpClient.request<TaskPlanDetailDto>(
        taskPlanPath(taskPlanId),
        { signal },
      )
      return mapTaskPlanDetail(response.data)
    },

    async getTaskPlanMarkdown(taskPlanId, signal) {
      const response = await httpClient.request<string>(
        `${taskPlanPath(taskPlanId)}/markdown`,
        { responseType: 'text', signal },
      )
      return response.data
    },

    async listTaskPlans(request) {
      const response = await httpClient.request<TaskPlanListResponseDto>(
        listPath(request),
        { signal: request.signal },
      )
      return mapTaskPlanPage(response.data)
    },

    async retryTaskPlan(taskPlanId, idempotencyKey) {
      await httpClient.request<TaskPlanControlResponseDto>(
        `${taskPlanPath(taskPlanId)}/retry`,
        {
          headers: { 'Idempotency-Key': idempotencyKey },
          method: 'POST',
        },
      )
    },
  }
}
