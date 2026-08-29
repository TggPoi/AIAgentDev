import type {
  DocumentTaskPlanDetailDto,
  ResearchTaskPlanDetailDto,
  TaskPlanDetailDto,
  TaskPlanListItemDto,
  TaskPlanListResponseDto,
  TaskPlanStatusDto,
} from '@/features/task-plans/task-plan-contracts'


export type TaskPlanKind =
  | 'knowledge_document_management'
  | 'question_decomposition'
export type TaskPlanStatus = TaskPlanStatusDto

export interface TaskPlanSummary {
  createdAt: string
  errorCode: string | null
  requiresConfirmation: boolean
  sessionId: string | null
  status: TaskPlanStatus
  summary: string
  taskKind: TaskPlanKind
  taskPlanId: string
  updatedAt: string
}

export interface TaskPlanPage {
  items: TaskPlanSummary[]
  nextCursor: string | null
}

interface TaskPlanDetailBase {
  createdAt: string
  errorCode: string | null
  objective: string
  sessionId: string | null
  status: TaskPlanStatus
  taskPlanId: string
  updatedAt: string
}

export interface ResearchTaskPlanDetail extends TaskPlanDetailBase {
  capabilitySnapshot: ResearchTaskPlanDetailDto['capability_snapshot']
  errorMessage: string | null
  evidence: ResearchTaskPlanDetailDto['evidence']
  finalOutput: ResearchTaskPlanDetailDto['final_output'] | null
  finalSynthesisInstruction: string
  kind: 'research'
  progress: ResearchTaskPlanDetailDto['progress']
  qualityReview: ResearchTaskPlanDetailDto['quality_review']
  requirementEvidenceStatuses:
    ResearchTaskPlanDetailDto['requirement_evidence_statuses']
  requirements: ResearchTaskPlanDetailDto['requirements']
  schemaVersion: 2
  sourceQuery: string
  subQuestionResults: ResearchTaskPlanDetailDto['sub_question_results']
  subQuestions: ResearchTaskPlanDetailDto['sub_questions']
  taskKind: 'question_decomposition'
  taskType: 'analysis'
  validationIssues: ResearchTaskPlanDetailDto['validation_issues']
}

export interface DocumentTaskPlanStep {
  errorCode: string | null
  requiresConfirmation: boolean
  riskLevel: DocumentTaskPlanDetailDto['steps'][number]['risk_level']
  status: DocumentTaskPlanDetailDto['steps'][number]['status']
  stepId: string
  toolName: string
}

export interface DocumentTaskPlanDetail extends TaskPlanDetailBase {
  kind: 'document'
  requiresConfirmation: boolean
  resultSummary: {
    completedSteps: number
    failedSteps: number
    skippedSteps: number
    totalSteps: number
  }
  steps: DocumentTaskPlanStep[]
  taskKind: 'knowledge_document_management'
  taskType: DocumentTaskPlanDetailDto['task_type']
}

export type TaskPlanDetail =
  | ResearchTaskPlanDetail
  | DocumentTaskPlanDetail

function mapTaskPlanSummary(dto: TaskPlanListItemDto): TaskPlanSummary {
  return {
    createdAt: dto.created_at,
    errorCode: dto.error_code ?? null,
    requiresConfirmation: dto.requires_confirmation,
    sessionId: dto.session_id ?? null,
    status: dto.status,
    summary: dto.summary,
    taskKind: dto.task_kind,
    taskPlanId: dto.task_plan_id,
    updatedAt: dto.updated_at,
  }
}

export function mapTaskPlanPage(
  dto: TaskPlanListResponseDto,
): TaskPlanPage {
  return {
    items: dto.items.map(mapTaskPlanSummary),
    nextCursor: dto.next_cursor ?? null,
  }
}

function mapResearchDetail(
  dto: ResearchTaskPlanDetailDto,
): ResearchTaskPlanDetail {
  return {
    capabilitySnapshot: { ...dto.capability_snapshot },
    createdAt: dto.created_at,
    errorCode: dto.error_code ?? null,
    errorMessage: dto.error_message ?? null,
    evidence: dto.evidence.map((item) => ({ ...item })),
    finalOutput: dto.final_output ? { ...dto.final_output } : null,
    finalSynthesisInstruction: dto.final_synthesis_instruction,
    kind: 'research',
    objective: dto.objective,
    progress: {
      ...dto.progress,
      events: dto.progress.events?.map((item) => ({ ...item })),
      workers: dto.progress.workers
        ? Object.fromEntries(
            Object.entries(dto.progress.workers).map(([key, value]) => [
              key,
              { ...value },
            ]),
          )
        : undefined,
    },
    qualityReview: { ...dto.quality_review },
    requirementEvidenceStatuses: dto.requirement_evidence_statuses.map(
      (item) => ({ ...item }),
    ),
    requirements: dto.requirements.map((item) => ({ ...item })),
    schemaVersion: dto.schema_version,
    sessionId: dto.session_id ?? null,
    sourceQuery: dto.source_query,
    status: dto.status,
    subQuestionResults: dto.sub_question_results.map((item) => ({ ...item })),
    subQuestions: dto.sub_questions.map((item) => ({ ...item })),
    taskKind: dto.task_kind,
    taskPlanId: dto.task_plan_id,
    taskType: dto.task_type,
    updatedAt: dto.updated_at,
    validationIssues: dto.validation_issues.map((item) => ({ ...item })),
  }
}

function mapDocumentDetail(
  dto: DocumentTaskPlanDetailDto,
): DocumentTaskPlanDetail {
  return {
    createdAt: dto.created_at,
    errorCode: dto.error_code ?? null,
    kind: 'document',
    objective: dto.objective,
    requiresConfirmation: dto.requires_confirmation,
    resultSummary: {
      completedSteps: dto.result_summary.completed_steps,
      failedSteps: dto.result_summary.failed_steps,
      skippedSteps: dto.result_summary.skipped_steps,
      totalSteps: dto.result_summary.total_steps,
    },
    sessionId: dto.session_id ?? null,
    status: dto.status,
    steps: dto.steps.map((step) => ({
      errorCode: step.error_code ?? null,
      requiresConfirmation: step.requires_confirmation,
      riskLevel: step.risk_level,
      status: step.status,
      stepId: step.step_id,
      toolName: step.tool_name,
    })),
    taskKind: dto.task_kind,
    taskPlanId: dto.task_plan_id,
    taskType: dto.task_type,
    updatedAt: dto.updated_at,
  }
}

export function mapTaskPlanDetail(dto: TaskPlanDetailDto): TaskPlanDetail {
  return dto.task_kind === 'question_decomposition'
    ? mapResearchDetail(dto)
    : mapDocumentDetail(dto)
}

export function mergeTaskPlanPages(
  pages: readonly TaskPlanPage[],
): TaskPlanSummary[] {
  const seen = new Set<string>()
  const merged: TaskPlanSummary[] = []
  for (const page of pages) {
    for (const item of page.items) {
      if (seen.has(item.taskPlanId)) continue
      seen.add(item.taskPlanId)
      merged.push(item)
    }
  }
  return merged
}
