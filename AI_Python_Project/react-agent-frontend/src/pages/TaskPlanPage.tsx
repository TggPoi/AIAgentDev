import { useMemo } from 'react'
import { useParams } from 'react-router-dom'

import { useAuth } from '@/features/auth/AuthProvider'
import { createTaskPlanApi } from '@/features/task-plans/task-plan-api'
import { TaskPlanWorkspace } from '@/features/task-plans/TaskPlanWorkspace'


export function TaskPlanPage() {
  const auth = useAuth()
  const { taskPlanId } = useParams<{ taskPlanId: string }>()
  const api = useMemo(() => createTaskPlanApi(auth.httpClient), [auth.httpClient])
  const snapshot = auth.snapshot
  if (snapshot === null) return null

  return (
    <TaskPlanWorkspace
      api={api}
      key={`${snapshot.currentUser.userId}:${taskPlanId ?? '__list__'}`}
      taskPlanId={taskPlanId ?? null}
      userBoundary={snapshot.currentUser.userId}
    />
  )
}
