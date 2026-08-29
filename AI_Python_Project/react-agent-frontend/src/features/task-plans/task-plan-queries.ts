import {
  type InfiniteData,
  type QueryClient,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { ApiError } from '@/api/api-error'
import type { TaskPlanApi } from '@/features/task-plans/task-plan-api'
import type {
  TaskPlanDetail,
  TaskPlanPage,
  TaskPlanStatus,
} from '@/features/task-plans/task-plan-models'


export interface TaskPlanListKeyParams {
  limit: number
  sessionId: string | null
  status: TaskPlanStatus | null
}

export interface TaskPlanListFilters {
  sessionId: string | null
  status: TaskPlanStatus | null
}

export const TASK_PLAN_LIST_LIMIT = 20

export const taskPlanKeys = {
  detail: (userBoundary: string, taskPlanId: string) =>
    [userBoundary, 'task-plan-detail', taskPlanId] as const,
  detailRoot: (userBoundary: string) =>
    [userBoundary, 'task-plan-detail'] as const,
  list: (userBoundary: string, params: TaskPlanListKeyParams) =>
    [...taskPlanKeys.listRoot(userBoundary), params] as const,
  listRoot: (userBoundary: string) =>
    [userBoundary, 'task-plans'] as const,
  markdown: (userBoundary: string, taskPlanId: string) =>
    [userBoundary, 'task-plan-markdown', taskPlanId] as const,
  markdownRoot: (userBoundary: string) =>
    [userBoundary, 'task-plan-markdown'] as const,
}

export function useTaskPlanList(
  api: TaskPlanApi,
  userBoundary: string,
  filters: TaskPlanListFilters,
) {
  const params = { ...filters, limit: TASK_PLAN_LIST_LIMIT }
  return useInfiniteQuery<
    TaskPlanPage,
    Error,
    InfiniteData<TaskPlanPage>,
    ReturnType<typeof taskPlanKeys.list>,
    string | null
  >({
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api.listTaskPlans({
        cursor: pageParam,
        limit: TASK_PLAN_LIST_LIMIT,
        sessionId: filters.sessionId,
        signal,
        status: filters.status,
      }),
    queryKey: taskPlanKeys.list(userBoundary, params),
  })
}

export function useTaskPlanDetail(
  api: TaskPlanApi,
  userBoundary: string,
  taskPlanId: string | null,
) {
  return useQuery<TaskPlanDetail, Error>({
    enabled: taskPlanId !== null,
    queryFn: ({ signal }) => api.getTaskPlan(taskPlanId ?? '', signal),
    queryKey: taskPlanKeys.detail(
      userBoundary,
      taskPlanId ?? '__no-task-plan__',
    ),
  })
}

export function useTaskPlanMarkdown(
  api: TaskPlanApi,
  userBoundary: string,
  taskPlanId: string | null,
) {
  return useQuery<string, Error>({
    enabled: taskPlanId !== null,
    queryFn: ({ signal }) => api.getTaskPlanMarkdown(taskPlanId ?? '', signal),
    queryKey: taskPlanKeys.markdown(
      userBoundary,
      taskPlanId ?? '__no-task-plan__',
    ),
  })
}

function refreshTaskPlanFacts(
  queryClient: QueryClient,
  userBoundary: string,
  taskPlanId: string,
) {
  return Promise.all([
    queryClient.invalidateQueries({
      queryKey: taskPlanKeys.detail(userBoundary, taskPlanId),
    }),
    queryClient.invalidateQueries({
      queryKey: taskPlanKeys.listRoot(userBoundary),
    }),
  ])
}

export function useCancelTaskPlan(
  api: TaskPlanApi,
  userBoundary: string,
  taskPlanId: string,
) {
  const queryClient = useQueryClient()
  const refreshFacts = () =>
    refreshTaskPlanFacts(queryClient, userBoundary, taskPlanId)
  return useMutation({
    mutationFn: (idempotencyKey: string) =>
      api.cancelTaskPlan(taskPlanId, idempotencyKey),
    onError: (error) =>
      error instanceof ApiError && error.status === 409
        ? refreshFacts()
        : undefined,
    onSuccess: refreshFacts,
  })
}

export function useRetryTaskPlan(
  api: TaskPlanApi,
  userBoundary: string,
  taskPlanId: string,
) {
  const queryClient = useQueryClient()
  const refreshFacts = () =>
    refreshTaskPlanFacts(queryClient, userBoundary, taskPlanId)
  return useMutation({
    mutationFn: (idempotencyKey: string) =>
      api.retryTaskPlan(taskPlanId, idempotencyKey),
    onError: (error) =>
      error instanceof ApiError && error.status === 409
        ? refreshFacts()
        : undefined,
    onSuccess: refreshFacts,
  })
}
