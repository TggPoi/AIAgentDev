import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { PropsWithChildren } from 'react'
import { describe, expect, it } from 'vitest'

import { createHttpClient } from '@/api/http-client'
import { createTaskPlanApi } from '@/features/task-plans/task-plan-api'
import {
  taskPlanKeys,
  useCancelTaskPlan,
  useRetryTaskPlan,
} from '@/features/task-plans/task-plan-queries'
import { server } from '@/test/server'


const apiBaseUrl = 'http://task-plan-mutations.test'

describe('TaskPlan mutation convergence', () => {
  it('invalidates detail and list facts after a successful cancel', async () => {
    server.use(
      http.post(
        `${apiBaseUrl}/agent/task-plans/document-cancel/cancel`,
        () =>
          HttpResponse.json({
            message: '任务已取消',
            request_id: 'cancel-request',
            status: 'cancelled',
            task_plan_id: 'document-cancel',
            trace_id: null,
          }),
      ),
    )
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    })
    const detailKey = taskPlanKeys.detail('user-a', 'document-cancel')
    const listKey = taskPlanKeys.list('user-a', {
      limit: 20,
      sessionId: null,
      status: null,
    })
    queryClient.setQueryData(detailKey, { status: 'waiting_confirmation' })
    queryClient.setQueryData(listKey, { pages: [], pageParams: [] })
    const api = createTaskPlanApi(
      createHttpClient({
        baseUrl: apiBaseUrl,
        getAccessToken: () => null,
        requestIdFactory: () => 'cancel-request',
      }),
    )
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(
      () => useCancelTaskPlan(api, 'user-a', 'document-cancel'),
      { wrapper },
    )

    await result.current.mutateAsync('task-plan-cancel-success-key')

    await waitFor(() => {
      expect(queryClient.getQueryState(detailKey)?.isInvalidated).toBe(true)
      expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true)
    })
  })

  it('invalidates detail and list facts after a retry conflict', async () => {
    server.use(
      http.post(
        `${apiBaseUrl}/agent/task-plans/research-conflict/retry`,
        () =>
          HttpResponse.json(
            {
              code: 'AGENT_TASK_PLAN_STATUS_CONFLICT',
              error_category: 'user_error',
              message: '任务状态已变化',
              request_id: 'retry-conflict-request',
              trace_id: null,
            },
            { status: 409 },
          ),
      ),
    )
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
    })
    const detailKey = taskPlanKeys.detail('user-a', 'research-conflict')
    const listKey = taskPlanKeys.list('user-a', {
      limit: 20,
      sessionId: null,
      status: null,
    })
    queryClient.setQueryData(detailKey, { status: 'failed' })
    queryClient.setQueryData(listKey, { pages: [], pageParams: [] })
    const api = createTaskPlanApi(
      createHttpClient({
        baseUrl: apiBaseUrl,
        getAccessToken: () => null,
        requestIdFactory: () => 'retry-conflict-request',
      }),
    )
    const wrapper = ({ children }: PropsWithChildren) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(
      () => useRetryTaskPlan(api, 'user-a', 'research-conflict'),
      { wrapper },
    )

    await expect(
      result.current.mutateAsync('task-plan-retry-conflict-key'),
    ).rejects.toMatchObject({ status: 409 })

    await waitFor(() => {
      expect(queryClient.getQueryState(detailKey)?.isInvalidated).toBe(true)
      expect(queryClient.getQueryState(listKey)?.isInvalidated).toBe(true)
    })
  })
})
