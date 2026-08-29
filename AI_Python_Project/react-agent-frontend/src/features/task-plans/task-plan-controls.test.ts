import { describe, expect, it } from 'vitest'

import { availableTaskPlanActions } from '@/features/task-plans/task-plan-controls'


describe('TaskPlan structured control policy', () => {
  it('uses status and task kind without parsing backend messages', () => {
    expect(
      availableTaskPlanActions('question_decomposition', 'waiting_confirmation'),
    ).toEqual(['confirm', 'cancel'])
    expect(
      availableTaskPlanActions('question_decomposition', 'executing_confirmed'),
    ).toEqual(['retry', 'cancel'])
    expect(
      availableTaskPlanActions('question_decomposition', 'completed_with_warnings'),
    ).toEqual(['retry'])
    expect(
      availableTaskPlanActions('knowledge_document_management', 'preparing_confirmation'),
    ).toEqual(['retry', 'cancel'])
    expect(
      availableTaskPlanActions('knowledge_document_management', 'failed'),
    ).toEqual(['retry', 'cancel'])
    expect(
      availableTaskPlanActions('knowledge_document_management', 'completed'),
    ).toEqual([])
    expect(
      availableTaskPlanActions('question_decomposition', 'cancelled'),
    ).toEqual([])
  })
})
