import type { HttpClient } from '@/api/http-client'
import type {
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
  getTaskPlan(taskPlanId: string, signal?: AbortSignal): Promise<TaskPlanDetail>
  getTaskPlanMarkdown(taskPlanId: string, signal?: AbortSignal): Promise<string>
  listTaskPlans(request: TaskPlanListRequest): Promise<TaskPlanPage>
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
  }
}
