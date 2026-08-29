import type { components } from '@/api/generated/backend-schema'
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

type TaskPlanStatus = components['schemas']['AgentTaskPlanStatus']
type TaskPlanDocumentProgressData =
  components['schemas']['TaskPlanDocumentProgressData']
type TaskPlanDocumentProgressEventName =
  components['schemas']['TaskPlanDocumentProgressFrame']['event']
type TaskPlanRequirementProgressData =
  components['schemas']['TaskPlanRequirementProgressData']
type TaskPlanRequirementProgressEventName =
  components['schemas']['TaskPlanRequirementProgressFrame']['event']
type TaskPlanResearchProgressData =
  components['schemas']['TaskPlanResearchProgressData']
type TaskPlanResearchProgressEventName =
  components['schemas']['TaskPlanResearchProgressFrame']['event']
type TaskPlanStepData = components['schemas']['TaskPlanStepData']
type TaskPlanStepEventName = components['schemas']['TaskPlanStepFrame']['event']
type TaskPlanSubQuestionData =
  components['schemas']['TaskPlanSubQuestionCompletedData']
const taskPlanStatuses = new Set<string>([
  'cancelled',
  'completed',
  'completed_with_warnings',
  'created',
  'executing_confirmed',
  'failed',
  'preparing_confirmation',
  'waiting_confirmation',
])

export interface TaskPlanStatusEvent extends PublicEventBase {
  event: 'agent_task_status'
  status: TaskPlanStatus
  taskPlanId: string
}

export interface TaskPlanExecutionStartedEvent extends PublicEventBase {
  event: 'agent_task_execution_started'
  taskPlanId: string
}

export interface TaskPlanFinalSynthesisEvent extends PublicEventBase {
  event: 'agent_task_final_synthesis_completed'
  status: TaskPlanStatus
  taskPlanId: string
  usedToolCount: number
  warningCount: number
}

export interface TaskPlanAnswerDeltaEvent extends PublicEventBase {
  event: 'answer_delta'
  taskPlanId: string
  text: string
}

export interface TaskPlanSourcesEvent extends PublicEventBase {
  event: 'sources'
  sources: readonly PublicSource[]
  taskPlanId: string
}

export interface TaskPlanGuardEvent extends PublicEventBase {
  action: 'block' | 'sanitize'
  categories: readonly string[]
  event: 'guard_blocked' | 'guard_sanitized'
  reason: string
  riskLevel: string
  taskPlanId: string
  text: string
}

export interface TaskPlanDoneEvent extends PublicEventBase {
  event: 'done'
  status: 'done'
  taskPlanId: string
  taskStatus: TaskPlanStatus
}

export interface TaskPlanErrorEvent extends PublicEventBase {
  code: string
  errorCategory: 'system_error'
  event: 'error'
  message: 'TaskPlan 执行失败'
  taskPlanId: string
  traceId: string | null
}

export interface TaskPlanResearchProgressEvent extends PublicEventBase {
  activeOperationCount: number
  attempt: number | null
  event: TaskPlanResearchProgressEventName
  evidenceCount: number | null
  reasonCode: string | null
  stage: TaskPlanResearchProgressData['stage'] | null
  status: TaskPlanResearchProgressData['status'] | null
  subQuestionId: string | null
  taskPlanId: string
  toolCallCount: number | null
  wave: number | null
}

export interface TaskPlanDocumentProgressEvent extends PublicEventBase {
  confidence: number | null
  deliverableCount: number | null
  deliverableId: string | null
  errorCode: string | null
  event: TaskPlanDocumentProgressEventName
  operation: TaskPlanDocumentProgressData['operation'] | null
  status: TaskPlanDocumentProgressData['status'] | null
  stepId: string | null
  taskPlanId: string
  verdict: TaskPlanDocumentProgressData['verdict'] | null
}

export interface TaskPlanRequirementProgressEvent extends PublicEventBase {
  event: TaskPlanRequirementProgressEventName
  evidenceCount: number
  reasonCodes: readonly string[]
  requirementId: string
  status: TaskPlanRequirementProgressData['status']
  taskPlanId: string
}

export interface TaskPlanStepEvent extends PublicEventBase {
  errorCode: string | null
  event: TaskPlanStepEventName
  status: TaskPlanStepData['status']
  stepId: string
  taskPlanId: string
  toolName: string
}

export interface TaskPlanSubQuestionCompletedEvent extends PublicEventBase {
  errorCode: string | null
  event: 'sub_question_completed'
  evidenceCount: number
  status: TaskPlanSubQuestionData['status']
  subQuestionId: string
  taskPlanId: string
}

export type TaskPlanPublicEvent =
  | TaskPlanAnswerDeltaEvent
  | TaskPlanDocumentProgressEvent
  | TaskPlanDoneEvent
  | TaskPlanErrorEvent
  | TaskPlanExecutionStartedEvent
  | TaskPlanFinalSynthesisEvent
  | TaskPlanGuardEvent
  | TaskPlanRequirementProgressEvent
  | TaskPlanResearchProgressEvent
  | TaskPlanSourcesEvent
  | TaskPlanStatusEvent
  | TaskPlanStepEvent
  | TaskPlanSubQuestionCompletedEvent
  | UnknownPublicEvent

const taskPlanResearchProgressEventNames = new Set<string>([
  'agent_task_evidence_evaluated',
  'agent_task_research_wave_started',
  'agent_task_research_worker_progress',
  'agent_task_research_worker_timed_out',
  'agent_task_sub_question_retrying',
  'sub_question_started',
])
const taskPlanDocumentProgressEventNames = new Set<string>([
  'agent_task_document_action_prepared',
  'agent_task_document_draft_created',
  'agent_task_document_review_completed',
  'agent_task_document_revision_started',
  'agent_task_document_subagent_completed',
  'agent_task_document_subagent_failed',
  'agent_task_document_subagent_started',
  'agent_task_document_supervised',
])
const taskPlanRequirementProgressEventNames = new Set<string>([
  'requirement_evidence_updated',
  'requirement_insufficient',
  'requirement_satisfied',
])
const taskPlanStepEventNames = new Set<string>([
  'agent_task_step_completed',
  'agent_task_step_failed',
])

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

function optionalNullableNumber(
  data: Record<string, unknown>,
  field: string,
  event: string,
): number | null {
  const value = data[field]
  if (value === null || value === undefined) {
    return null
  }
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new PublicEventProtocolError(event, `invalid ${field}`)
  }
  return value
}

function requiredEnum<T extends string>(
  data: Record<string, unknown>,
  field: string,
  event: string,
  allowed: ReadonlySet<string>,
): T {
  const value = requiredString(data, field, event)
  if (!allowed.has(value)) {
    throw new PublicEventProtocolError(event, `invalid ${field}`)
  }
  return value as T
}

function optionalNullableEnum<T extends string>(
  data: Record<string, unknown>,
  field: string,
  event: string,
  allowed: ReadonlySet<string>,
): T | null {
  const value = optionalNullableString(data, field, event)
  if (value !== null && !allowed.has(value)) {
    throw new PublicEventProtocolError(event, `invalid ${field}`)
  }
  return value as T | null
}

function optionalStringArray(
  data: Record<string, unknown>,
  field: string,
  event: string,
): string[] {
  if (data[field] === null || data[field] === undefined) {
    return []
  }
  return requiredStringArray(data, field, event)
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

function requiredTaskPlanStatus(
  data: Record<string, unknown>,
  event: string,
): TaskPlanStatus {
  const status = requiredString(data, 'status', event)
  if (!taskPlanStatuses.has(status)) {
    throw new PublicEventProtocolError(event, 'invalid status')
  }
  return status as TaskPlanStatus
}

export function parseTaskPlanPublicEvent(
  frame: SseFrame,
  expectedRequestId: string,
): TaskPlanPublicEvent {
  const data = validateEnvelope(frame, expectedRequestId)
  const common = base(frame, expectedRequestId)
  const taskPlanId = () => requiredString(data, 'task_plan_id', frame.event)

  if (taskPlanResearchProgressEventNames.has(frame.event)) {
    return {
      ...common,
      activeOperationCount: requiredNumber(
        data,
        'active_operation_count',
        frame.event,
      ),
      attempt: optionalNullableNumber(data, 'attempt', frame.event),
      event: frame.event as TaskPlanResearchProgressEventName,
      evidenceCount: optionalNullableNumber(data, 'evidence_count', frame.event),
      reasonCode: optionalNullableString(data, 'reason_code', frame.event),
      stage: optionalNullableEnum<
        NonNullable<TaskPlanResearchProgressData['stage']>
      >(
        data,
        'stage',
        frame.event,
        new Set([
          'starting',
          'tool_setup',
          'tool_selection',
          'tool_execution',
          'answer_generation',
          'evidence_evaluation',
          'retry_preparation',
          'completed',
        ]),
      ),
      status: optionalNullableEnum<
        NonNullable<TaskPlanResearchProgressData['status']>
      >(
        data,
        'status',
        frame.event,
        new Set([
          'pending',
          'running',
          'completed',
          'partial',
          'failed',
          'skipped',
          'retrying',
        ]),
      ),
      subQuestionId: optionalNullableString(
        data,
        'sub_question_id',
        frame.event,
      ),
      taskPlanId: taskPlanId(),
      toolCallCount: optionalNullableNumber(data, 'tool_call_count', frame.event),
      wave: optionalNullableNumber(data, 'wave', frame.event),
    }
  }
  if (taskPlanDocumentProgressEventNames.has(frame.event)) {
    return {
      ...common,
      confidence: optionalNullableNumber(data, 'confidence', frame.event),
      deliverableCount: optionalNullableNumber(
        data,
        'deliverable_count',
        frame.event,
      ),
      deliverableId: optionalNullableString(data, 'deliverable_id', frame.event),
      errorCode: optionalNullableString(data, 'error_code', frame.event),
      event: frame.event as TaskPlanDocumentProgressEventName,
      operation: optionalNullableEnum<
        NonNullable<TaskPlanDocumentProgressData['operation']>
      >(
        data,
        'operation',
        frame.event,
        new Set(['create', 'update', 'delete']),
      ),
      status: optionalNullableEnum<
        NonNullable<TaskPlanDocumentProgressData['status']>
      >(
        data,
        'status',
        frame.event,
        new Set(['running', 'completed', 'partial', 'failed', 'skipped']),
      ),
      stepId: optionalNullableString(data, 'step_id', frame.event),
      taskPlanId: taskPlanId(),
      verdict: optionalNullableEnum<
        NonNullable<TaskPlanDocumentProgressData['verdict']>
      >(
        data,
        'verdict',
        frame.event,
        new Set(['approved', 'revision_required', 'rejected']),
      ),
    }
  }
  if (taskPlanRequirementProgressEventNames.has(frame.event)) {
    return {
      ...common,
      event: frame.event as TaskPlanRequirementProgressEventName,
      evidenceCount: requiredNumber(data, 'evidence_count', frame.event),
      reasonCodes: optionalStringArray(data, 'reason_codes', frame.event),
      requirementId: requiredString(data, 'requirement_id', frame.event),
      status: requiredEnum<TaskPlanRequirementProgressData['status']>(
        data,
        'status',
        frame.event,
        new Set(['pending', 'partially_satisfied', 'satisfied', 'failed']),
      ),
      taskPlanId: taskPlanId(),
    }
  }
  if (taskPlanStepEventNames.has(frame.event)) {
    return {
      ...common,
      errorCode: optionalNullableString(data, 'error_code', frame.event),
      event: frame.event as TaskPlanStepEventName,
      status: requiredEnum<TaskPlanStepData['status']>(
        data,
        'status',
        frame.event,
        new Set(['completed', 'failed']),
      ),
      stepId: requiredString(data, 'step_id', frame.event),
      taskPlanId: taskPlanId(),
      toolName: requiredString(data, 'tool_name', frame.event),
    }
  }
  if (frame.event === 'sub_question_completed') {
    return {
      ...common,
      errorCode: optionalNullableString(data, 'error_code', frame.event),
      event: frame.event,
      evidenceCount: requiredNumber(data, 'evidence_count', frame.event),
      status: requiredEnum<TaskPlanSubQuestionData['status']>(
        data,
        'status',
        frame.event,
        new Set(['completed', 'partial', 'failed', 'skipped']),
      ),
      subQuestionId: requiredString(data, 'sub_question_id', frame.event),
      taskPlanId: taskPlanId(),
    }
  }

  if (frame.event === 'agent_task_execution_started') {
    return { ...common, event: frame.event, taskPlanId: taskPlanId() }
  }
  if (frame.event === 'agent_task_final_synthesis_completed') {
    return {
      ...common,
      event: frame.event,
      status: requiredTaskPlanStatus(data, frame.event),
      taskPlanId: taskPlanId(),
      usedToolCount: requiredNumber(data, 'used_tool_count', frame.event),
      warningCount: requiredNumber(data, 'warning_count', frame.event),
    }
  }
  if (frame.event === 'answer_delta') {
    return {
      ...common,
      event: frame.event,
      taskPlanId: taskPlanId(),
      text: requiredString(data, 'text', frame.event),
    }
  }
  if (frame.event === 'sources') {
    const sources = data.sources
    if (!Array.isArray(sources) || !sources.every(isRecord)) {
      throw new PublicEventProtocolError(frame.event, 'invalid sources')
    }
    return {
      ...common,
      event: frame.event,
      sources: sources.map((source) => projectSource(source, frame.event)),
      taskPlanId: taskPlanId(),
    }
  }
  if (frame.event === 'guard_blocked' || frame.event === 'guard_sanitized') {
    return {
      ...common,
      action: requiredEnum<'block' | 'sanitize'>(
        data,
        'action',
        frame.event,
        new Set(['block', 'sanitize']),
      ),
      categories: requiredStringArray(data, 'categories', frame.event),
      event: frame.event,
      reason: requiredString(data, 'reason', frame.event),
      riskLevel: requiredString(data, 'risk_level', frame.event),
      taskPlanId: taskPlanId(),
      text: requiredString(data, 'text', frame.event),
    }
  }
  if (frame.event === 'done') {
    if (data.status !== 'done') {
      throw new PublicEventProtocolError(frame.event, 'invalid status')
    }
    return {
      ...common,
      event: frame.event,
      status: 'done',
      taskPlanId: taskPlanId(),
      taskStatus: requiredTaskPlanStatus(
        { status: data.task_status },
        frame.event,
      ),
    }
  }
  if (frame.event === 'error') {
    if (
      data.error_category !== 'system_error' ||
      data.message !== 'TaskPlan 执行失败'
    ) {
      throw new PublicEventProtocolError(frame.event, 'invalid public error')
    }
    return {
      ...common,
      code: requiredString(data, 'code', frame.event),
      errorCategory: 'system_error',
      event: frame.event,
      message: 'TaskPlan 执行失败',
      taskPlanId: taskPlanId(),
      traceId: optionalNullableString(data, 'trace_id', frame.event),
    }
  }

  if (frame.event === 'agent_task_status') {
    return {
      ...common,
      event: frame.event,
      status: requiredTaskPlanStatus(data, frame.event),
      taskPlanId: taskPlanId(),
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
