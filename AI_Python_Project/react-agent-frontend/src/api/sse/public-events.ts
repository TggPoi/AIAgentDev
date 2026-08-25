import type { SseFrame } from '@/api/sse/parser'

const CONTRACT_VERSION = '1.0' as const

const TASK_PROGRESS_EVENT_TYPES = [
  'agent_task_document_action_prepared',
  'agent_task_document_draft_created',
  'agent_task_document_review_completed',
  'agent_task_document_revision_started',
  'agent_task_document_subagent_completed',
  'agent_task_document_subagent_failed',
  'agent_task_document_subagent_started',
  'agent_task_document_supervised',
  'agent_task_evidence_evaluated',
  'agent_task_execution_started',
  'agent_task_final_synthesis_completed',
  'agent_task_research_wave_started',
  'agent_task_research_worker_progress',
  'agent_task_research_worker_timed_out',
  'agent_task_status',
  'agent_task_step_completed',
  'agent_task_step_failed',
  'agent_task_step_started',
  'agent_task_sub_question_completed',
  'agent_task_sub_question_retrying',
  'agent_task_sub_question_started',
  'agent_task_tool_call_completed',
  'agent_task_tool_call_failed',
  'agent_task_tool_call_started',
  'agent_task_tool_selected',
  'agent_task_waiting_confirmation',
  'document_progress',
  'requirement_evidence_updated',
  'requirement_insufficient',
  'requirement_satisfied',
  'sub_question_completed',
  'sub_question_evidence_updated',
  'sub_question_started',
] as const

type TaskProgressEventName = (typeof TASK_PROGRESS_EVENT_TYPES)[number]
const taskProgressEventNames = new Set<string>(TASK_PROGRESS_EVENT_TYPES)

interface PublicEventBase {
  contractVersion: typeof CONTRACT_VERSION
  event: string
  receivedAt: number
  requestId: string
}

export interface AnswerDeltaEvent extends PublicEventBase {
  event: 'answer_delta'
  text: string
}

export interface SourcesEvent extends PublicEventBase {
  event: 'sources'
  sources: readonly PublicSource[]
}

export interface PublicSource {
  contentPreview: string
  docId: string | null
  href: string | null
  id: string
  score: number
  sectionPath: readonly string[]
  source: string
  sourceRevision: string | null
  sourceType: 'knowledge_document' | 'web'
  title: string | null
}

export interface GuardEvent extends PublicEventBase {
  action: 'block' | 'sanitize'
  categories: readonly string[]
  event: 'guard_blocked' | 'guard_sanitized'
  reason: string
  riskLevel: string
  text: string
}

export interface AgentRouteSelectedEvent extends PublicEventBase {
  confidence: number
  event: 'agent_route_selected'
  intent: string
  reason: string
  source: string
}

export interface AgentRouteClarificationEvent extends PublicEventBase {
  code: string
  confidence: number
  event: 'agent_route_clarification_required'
  question: string
}

export interface AgentTaskPlanCreatedEvent extends PublicEventBase {
  event: 'agent_task_plan_created'
  status?: string
  taskPlanId: string
}

export interface TaskProgressReferenceEvent extends PublicEventBase {
  event: TaskProgressEventName
  taskPlanId: string
}

export interface Nl2SqlGeneratedEvent extends PublicEventBase {
  attemptCount: number
  datasetId: string
  event: 'nl2sql_sql_generated'
  parameterizedSql: string
  queryId: string
}

export interface Nl2SqlResultEvent extends PublicEventBase {
  datasetId: string
  event: 'nl2sql_result'
  queryId: string
}

export interface DoneEvent extends PublicEventBase {
  event: 'done'
  stale?: boolean
  status: 'done'
}

export interface ErrorEvent extends PublicEventBase {
  code: string
  errorCategory: string
  event: 'error'
  message: string
  traceId?: string
}

export interface UnknownPublicEvent {
  event: string
  kind: 'unknown'
  receivedAt: number
  requestId: string
  status: 'unsupported_event'
}

export type KnownPublicEvent =
  | AgentRouteClarificationEvent
  | AgentRouteSelectedEvent
  | AgentTaskPlanCreatedEvent
  | AnswerDeltaEvent
  | DoneEvent
  | ErrorEvent
  | GuardEvent
  | Nl2SqlGeneratedEvent
  | Nl2SqlResultEvent
  | SourcesEvent
  | TaskProgressReferenceEvent

export type PublicEvent = KnownPublicEvent | UnknownPublicEvent
export type TerminalKind = 'failure' | 'success'

export class PublicEventProtocolError extends Error {
  constructor(event: string, reason: string) {
    super(`Invalid public SSE event ${event}: ${reason}`)
    this.name = 'PublicEventProtocolError'
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function requiredString(
  data: Record<string, unknown>,
  field: string,
  event: string,
): string {
  const value = data[field]
  if (typeof value !== 'string' || value.length === 0) {
    throw new PublicEventProtocolError(event, `missing ${field}`)
  }
  return value
}

function requiredNumber(
  data: Record<string, unknown>,
  field: string,
  event: string,
): number {
  const value = data[field]
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new PublicEventProtocolError(event, `missing ${field}`)
  }
  return value
}

function requiredStringArray(
  data: Record<string, unknown>,
  field: string,
  event: string,
): string[] {
  const value = data[field]
  if (!Array.isArray(value) || !value.every((item) => typeof item === 'string')) {
    throw new PublicEventProtocolError(event, `invalid ${field}`)
  }
  return value
}

function optionalNullableString(
  data: Record<string, unknown>,
  field: string,
  event: string,
): string | null {
  const value = data[field]
  if (value === null || value === undefined) {
    return null
  }
  if (typeof value !== 'string') {
    throw new PublicEventProtocolError(event, `invalid ${field}`)
  }
  return value
}

function projectSource(
  source: Record<string, unknown>,
  event: string,
): PublicSource {
  const sourceType = requiredString(source, 'source_type', event)
  if (sourceType !== 'knowledge_document' && sourceType !== 'web') {
    throw new PublicEventProtocolError(event, 'invalid source_type')
  }

  return {
    contentPreview: requiredString(source, 'content_preview', event),
    docId: optionalNullableString(source, 'doc_id', event),
    href: optionalNullableString(source, 'href', event),
    id: requiredString(source, 'id', event),
    score: requiredNumber(source, 'score', event),
    sectionPath: requiredStringArray(source, 'section_path', event),
    source: requiredString(source, 'source', event),
    sourceRevision: optionalNullableString(source, 'source_revision', event),
    sourceType,
    title: optionalNullableString(source, 'title', event),
  }
}

function validateEnvelope(
  frame: SseFrame,
  expectedRequestId: string,
): Record<string, unknown> {
  let value: unknown
  try {
    value = JSON.parse(frame.data)
  } catch {
    throw new PublicEventProtocolError(frame.event, 'data is not valid JSON')
  }
  if (!isRecord(value)) {
    throw new PublicEventProtocolError(frame.event, 'data is not an object')
  }
  if (value.contract_version !== CONTRACT_VERSION) {
    throw new PublicEventProtocolError(frame.event, 'contract version mismatch')
  }
  if (value.request_id !== expectedRequestId) {
    throw new PublicEventProtocolError(frame.event, 'request ID mismatch')
  }
  return value
}

function base(frame: SseFrame, requestId: string): PublicEventBase {
  return {
    contractVersion: CONTRACT_VERSION,
    event: frame.event,
    receivedAt: frame.receivedAt,
    requestId,
  }
}

function isTaskProgressEventName(value: string): value is TaskProgressEventName {
  return taskProgressEventNames.has(value)
}

export function parsePublicEvent(
  frame: SseFrame,
  expectedRequestId: string,
): PublicEvent {
  const data = validateEnvelope(frame, expectedRequestId)
  const common = base(frame, expectedRequestId)

  switch (frame.event) {
    case 'answer_delta':
      return {
        ...common,
        event: frame.event,
        text: requiredString(data, 'text', frame.event),
      }
    case 'sources': {
      const sources = data.sources
      if (!Array.isArray(sources) || !sources.every(isRecord)) {
        throw new PublicEventProtocolError(frame.event, 'invalid sources')
      }
      return {
        ...common,
        event: frame.event,
        sources: sources.map((source) => projectSource(source, frame.event)),
      }
    }
    case 'guard_blocked':
    case 'guard_sanitized': {
      const action = requiredString(data, 'action', frame.event)
      if (action !== 'block' && action !== 'sanitize') {
        throw new PublicEventProtocolError(frame.event, 'invalid action')
      }
      return {
        ...common,
        action,
        categories: requiredStringArray(data, 'categories', frame.event),
        event: frame.event,
        reason: requiredString(data, 'reason', frame.event),
        riskLevel: requiredString(data, 'risk_level', frame.event),
        text: requiredString(data, 'text', frame.event),
      }
    }
    case 'agent_route_selected':
      return {
        ...common,
        confidence: requiredNumber(data, 'confidence', frame.event),
        event: frame.event,
        intent: requiredString(data, 'intent', frame.event),
        reason: requiredString(data, 'reason', frame.event),
        source: requiredString(data, 'source', frame.event),
      }
    case 'agent_route_clarification_required':
      return {
        ...common,
        code: requiredString(data, 'code', frame.event),
        confidence: requiredNumber(data, 'confidence', frame.event),
        event: frame.event,
        question: requiredString(data, 'question', frame.event),
      }
    case 'agent_task_plan_created': {
      const status = data.status
      return {
        ...common,
        event: frame.event,
        ...(typeof status === 'string' ? { status } : {}),
        taskPlanId: requiredString(data, 'task_plan_id', frame.event),
      }
    }
    case 'nl2sql_sql_generated':
      return {
        ...common,
        attemptCount: requiredNumber(data, 'attempt_count', frame.event),
        datasetId: requiredString(data, 'dataset_id', frame.event),
        event: frame.event,
        parameterizedSql: requiredString(
          data,
          'parameterized_sql',
          frame.event,
        ),
        queryId: requiredString(data, 'query_id', frame.event),
      }
    case 'nl2sql_result':
      return {
        ...common,
        datasetId: requiredString(data, 'dataset_id', frame.event),
        event: frame.event,
        queryId: requiredString(data, 'query_id', frame.event),
      }
    case 'done':
      if (data.status !== 'done') {
        throw new PublicEventProtocolError(frame.event, 'invalid status')
      }
      return {
        ...common,
        event: frame.event,
        ...(typeof data.stale === 'boolean' ? { stale: data.stale } : {}),
        status: 'done',
      }
    case 'error': {
      const traceId = data.trace_id
      return {
        ...common,
        code: requiredString(data, 'code', frame.event),
        errorCategory: requiredString(data, 'error_category', frame.event),
        event: frame.event,
        message: requiredString(data, 'message', frame.event),
        ...(typeof traceId === 'string' ? { traceId } : {}),
      }
    }
    default:
      if (isTaskProgressEventName(frame.event)) {
        return {
          ...common,
          event: frame.event,
          taskPlanId: requiredString(data, 'task_plan_id', frame.event),
        }
      }
      return {
        event: frame.event,
        kind: 'unknown',
        receivedAt: frame.receivedAt,
        requestId: expectedRequestId,
        status: 'unsupported_event',
      }
  }
}

export function getTerminalKind(event: PublicEvent): TerminalKind | null {
  if (event.event === 'done') {
    return 'success'
  }
  if (event.event === 'error') {
    return 'failure'
  }
  return null
}
