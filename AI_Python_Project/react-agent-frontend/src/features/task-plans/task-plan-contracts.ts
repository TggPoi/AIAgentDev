import type { components } from '@/api/generated/backend-schema'


export type TaskPlanStatusDto = components['schemas']['AgentTaskPlanStatus']
export type TaskPlanControlResponseDto =
  components['schemas']['AgentTaskPlanControlResponse']
export type TaskPlanListItemDto = components['schemas']['AgentTaskPlanListItem']
export type TaskPlanListResponseDto =
  components['schemas']['AgentTaskPlanListResponse']
export type ResearchTaskPlanDetailDto =
  components['schemas']['ResearchTaskPlanPublicView']
export type DocumentTaskPlanDetailDto =
  components['schemas']['DocumentTaskPlanPublicView']
export type TaskPlanDetailDto =
  | ResearchTaskPlanDetailDto
  | DocumentTaskPlanDetailDto
