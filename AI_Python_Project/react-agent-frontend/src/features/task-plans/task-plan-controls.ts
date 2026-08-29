import type {
  TaskPlanKind,
  TaskPlanStatus,
} from '@/features/task-plans/task-plan-models'

export type TaskPlanAction = 'cancel' | 'confirm' | 'retry'

const cancellableStatuses = new Set<TaskPlanStatus>([
  'created',
  'preparing_confirmation',
  'waiting_confirmation',
  'executing_confirmed',
  'failed',
])

export function availableTaskPlanActions(
  taskKind: TaskPlanKind,
  status: TaskPlanStatus,
): TaskPlanAction[] {
  const actions: TaskPlanAction[] = []
  if (status === 'waiting_confirmation') actions.push('confirm')

  const canRetry =
    taskKind === 'question_decomposition'
      ? status === 'executing_confirmed' ||
        status === 'failed' ||
        status === 'completed_with_warnings'
      : status === 'preparing_confirmation' ||
        status === 'executing_confirmed' ||
        status === 'failed'
  if (canRetry) actions.push('retry')
  if (cancellableStatuses.has(status)) actions.push('cancel')
  return actions
}
