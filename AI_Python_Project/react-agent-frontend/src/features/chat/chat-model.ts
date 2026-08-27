import { ApiError } from '@/api/api-error'
import type {
  PublicEvent,
  PublicSource,
  UnknownPublicEvent,
} from '@/api/sse/public-events'
import type { RagChatRequestDto } from '@/features/chat/chat-contracts'


export type ChatStreamStatus =
  | 'cancelled'
  | 'completed'
  | 'connecting'
  | 'failed'
  | 'idle'
  | 'interrupted'
  | 'streaming'

export interface ChatTimelineItem {
  description?: string
  event: string
  receivedAt: number
  requestId: string
  status?: UnknownPublicEvent['status']
}

export interface ChatState {
  answer: string
  clarification: string | null
  errorMessage: string | null
  query: string
  requestId: string | null
  sources: readonly PublicSource[]
  stale: boolean
  status: ChatStreamStatus
  taskPlanId: string | null
  timeline: readonly ChatTimelineItem[]
}

interface ChatRequestInput {
  allowDirectWeb: boolean
  allowWebFallback: boolean
  canUseWebSearch: boolean
  query: string
  sessionId: string | null
}

type ChatAction =
  | { type: 'reset' }
  | { query: string; requestId: string; type: 'start' }
  | { event: PublicEvent; type: 'event' }
  | { message: string; requestId: string; type: 'fail' }
  | { message: string; requestId: string; type: 'interrupt' }
  | { requestId: string; type: 'cancel' }

const terminalStatuses = new Set<ChatStreamStatus>([
  'cancelled',
  'completed',
  'failed',
  'interrupted',
])

export function createInitialChatState(): ChatState {
  return {
    answer: '',
    clarification: null,
    errorMessage: null,
    query: '',
    requestId: null,
    sources: [],
    stale: false,
    status: 'idle',
    taskPlanId: null,
    timeline: [],
  }
}

export function buildChatRequest(input: ChatRequestInput): RagChatRequestDto {
  const allowDirectWeb = input.canUseWebSearch && input.allowDirectWeb
  return {
    allow_direct_web: allowDirectWeb,
    allow_web_fallback: allowDirectWeb && input.allowWebFallback,
    min_score: 0,
    mode: 'hybrid',
    query: input.query,
    ...(input.sessionId === null ? {} : { session_id: input.sessionId }),
    top_k: 5,
  }
}

export function queryErrorMessage(error: unknown): string | null {
  if (!(error instanceof ApiError)) {
    return null
  }
  return (
    error.fieldErrors.find((fieldError) => fieldError.field === 'query')
      ?.message ?? null
  )
}

function isCurrentRequest(state: ChatState, requestId: string): boolean {
  return state.requestId === requestId && !terminalStatuses.has(state.status)
}

function projectTimelineEvent(event: PublicEvent): ChatTimelineItem {
  let description: string | undefined
  if (!('kind' in event)) {
    switch (event.event) {
      case 'agent_route_selected':
        description = `已选择 ${event.intent} 路由`
        break
      case 'agent_route_clarification_required':
        description = '需要补充信息'
        break
      case 'agent_task_plan_created':
        description = '已创建 TaskPlan'
        break
      case 'guard_blocked':
        description = '安全检查已阻止本次请求'
        break
      case 'guard_sanitized':
        description = '安全检查已净化输入'
        break
      case 'nl2sql_sql_generated':
        description = '已生成参数化 SQL'
        break
      case 'nl2sql_result':
        description = '结构化数据查询已完成'
        break
    }
  }
  return {
    ...(description === undefined ? {} : { description }),
    event: event.event,
    receivedAt: event.receivedAt,
    requestId: event.requestId,
    ...('kind' in event ? { status: event.status } : {}),
  }
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  if (action.type === 'reset') {
    return createInitialChatState()
  }
  if (action.type === 'start') {
    return {
      ...createInitialChatState(),
      query: action.query,
      requestId: action.requestId,
      status: 'connecting',
    }
  }

  const actionRequestId =
    action.type === 'event' ? action.event.requestId : action.requestId
  if (!isCurrentRequest(state, actionRequestId)) {
    return state
  }

  if (action.type === 'cancel') {
    return { ...state, status: 'cancelled' }
  }
  if (action.type === 'fail') {
    return { ...state, errorMessage: action.message, status: 'failed' }
  }
  if (action.type === 'interrupt') {
    return {
      ...state,
      errorMessage: action.message,
      status: 'interrupted',
    }
  }

  const receivedEvent = action.event
  if ('kind' in receivedEvent) {
    return {
      ...state,
      status: 'streaming',
      timeline: [...state.timeline, projectTimelineEvent(receivedEvent)],
    }
  }
  switch (receivedEvent.event) {
    case 'answer_delta':
      return {
        ...state,
        answer: state.answer + receivedEvent.text,
        status: 'streaming',
      }
    case 'sources':
      return {
        ...state,
        sources: receivedEvent.sources,
        status: 'streaming',
      }
    case 'done':
      return {
        ...state,
        stale: receivedEvent.stale ?? false,
        status: 'completed',
      }
    case 'error':
      return {
        ...state,
        errorMessage: receivedEvent.message,
        status: 'failed',
      }
    case 'agent_route_clarification_required':
      return {
        ...state,
        clarification: receivedEvent.question,
        status: 'streaming',
        timeline: [...state.timeline, projectTimelineEvent(receivedEvent)],
      }
    case 'agent_task_plan_created':
      return {
        ...state,
        status: 'streaming',
        taskPlanId: receivedEvent.taskPlanId,
        timeline: [...state.timeline, projectTimelineEvent(receivedEvent)],
      }
    default:
      return {
        ...state,
        status: 'streaming',
        timeline: [...state.timeline, projectTimelineEvent(receivedEvent)],
      }
  }
}
