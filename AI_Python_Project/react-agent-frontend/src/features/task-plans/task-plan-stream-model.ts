import type {
  PublicSource,
  TaskPlanPublicEvent,
  UnknownPublicEvent,
} from '@/api/sse/public-events'
import type { TaskPlanStatus } from '@/features/task-plans/task-plan-models'


export type TaskPlanStreamStatus =
  | 'cancelled'
  | 'completed'
  | 'connecting'
  | 'failed'
  | 'idle'
  | 'interrupted'
  | 'streaming'

export interface TaskPlanTimelineItem {
  event: string
  receivedAt: number
  requestId: string
  status?: UnknownPublicEvent['status']
}

export interface TaskPlanStreamState {
  answer: string
  errorMessage: string | null
  requestId: string | null
  sources: readonly PublicSource[]
  status: TaskPlanStreamStatus
  taskPlanId: string | null
  taskStatus: TaskPlanStatus | null
  timeline: readonly TaskPlanTimelineItem[]
}

type TaskPlanStreamAction =
  | {
      requestId: string
      taskPlanId: string
      type: 'start'
    }
  | { event: TaskPlanPublicEvent; type: 'event' }

export function createInitialTaskPlanStreamState(): TaskPlanStreamState {
  return {
    answer: '',
    errorMessage: null,
    requestId: null,
    sources: [],
    status: 'idle',
    taskPlanId: null,
    taskStatus: null,
    timeline: [],
  }
}

export function taskPlanStreamReducer(
  state: TaskPlanStreamState,
  action: TaskPlanStreamAction,
): TaskPlanStreamState {
  if (action.type === 'start') {
    return {
      ...createInitialTaskPlanStreamState(),
      requestId: action.requestId,
      status: 'connecting',
      taskPlanId: action.taskPlanId,
    }
  }

  const event = action.event
  if (
    state.status === 'cancelled' ||
    state.status === 'completed' ||
    state.status === 'failed' ||
    state.status === 'interrupted' ||
    state.requestId !== event.requestId ||
    ('taskPlanId' in event && state.taskPlanId !== event.taskPlanId)
  ) {
    return state
  }
  const timelineItem: TaskPlanTimelineItem = {
    event: event.event,
    receivedAt: event.receivedAt,
    requestId: event.requestId,
    ...('kind' in event ? { status: event.status } : {}),
  }
  const timeline = [...state.timeline, timelineItem]
  if ('kind' in event) {
    return { ...state, status: 'streaming', timeline }
  }
  if (event.event === 'answer_delta') {
    return {
      ...state,
      answer: state.answer + event.text,
      status: 'streaming',
    }
  }
  if (event.event === 'sources') {
    return { ...state, sources: event.sources, status: 'streaming' }
  }
  if (event.event === 'done') {
    return {
      ...state,
      status: 'completed',
      taskStatus: event.taskStatus,
      timeline,
    }
  }
  if (event.event === 'error') {
    return {
      ...state,
      errorMessage: event.message,
      status: 'failed',
      timeline,
    }
  }
  if (event.event === 'agent_task_status') {
    return {
      ...state,
      status: 'streaming',
      taskStatus: event.status,
      timeline,
    }
  }
  return { ...state, status: 'streaming', timeline }
}
