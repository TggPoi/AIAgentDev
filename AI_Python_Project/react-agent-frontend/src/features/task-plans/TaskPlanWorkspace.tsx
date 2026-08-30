import { useEffect, useReducer, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { MarkdownViewer } from '@/components/ui/MarkdownViewer'
import { EmptyState, ErrorState, PageSkeleton } from '@/components/ui/PageState'
import type { TaskPlanApi } from '@/features/task-plans/task-plan-api'
import { availableTaskPlanActions } from '@/features/task-plans/task-plan-controls'
import {
  mergeTaskPlanPages,
  type DocumentTaskPlanDetail,
  type ResearchTaskPlanDetail,
  type TaskPlanStatus,
} from '@/features/task-plans/task-plan-models'
import {
  useCancelTaskPlan,
  useTaskPlanDetail,
  useTaskPlanList,
  useTaskPlanMarkdown,
  useRetryTaskPlan,
  taskPlanKeys,
} from '@/features/task-plans/task-plan-queries'
import {
  createInitialTaskPlanStreamState,
  taskPlanStreamReducer,
} from '@/features/task-plans/task-plan-stream-model'
import styles from '@/features/task-plans/TaskPlanWorkspace.module.css'


interface TaskPlanWorkspaceProps {
  api: TaskPlanApi
  taskPlanId: string | null
  userBoundary: string
}

const statusLabels: Record<TaskPlanStatus, string> = {
  cancelled: '已取消',
  completed: '已完成',
  completed_with_warnings: '完成但有警告',
  created: '已创建',
  executing_confirmed: '执行中',
  failed: '失败',
  preparing_confirmation: '准备确认',
  waiting_confirmation: '等待确认',
}

const statusValues = new Set<TaskPlanStatus>(
  Object.keys(statusLabels) as TaskPlanStatus[],
)

function errorState(error: unknown, message: string) {
  return (
    <ErrorState
      code={error instanceof ApiError ? error.code : undefined}
      message={message}
      requestId={error instanceof ApiError ? error.requestId : undefined}
    />
  )
}

function TaskPlanListView({ api, userBoundary }: Omit<TaskPlanWorkspaceProps, 'taskPlanId'>) {
  const [searchParams, setSearchParams] = useSearchParams()
  const statusValue = searchParams.get('status')
  const status =
    statusValue !== null && statusValues.has(statusValue as TaskPlanStatus)
      ? (statusValue as TaskPlanStatus)
      : null
  const sessionId = searchParams.get('session_id')
  const query = useTaskPlanList(api, userBoundary, { sessionId, status })
  const items = mergeTaskPlanPages(query.data?.pages ?? [])

  const setFilter = (name: 'session_id' | 'status', value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(name, value)
    else next.delete(name)
    setSearchParams(next, { replace: true })
  }

  return (
    <section aria-labelledby="task-plan-list-title" className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>Agent Operations</p>
        <h2 id="task-plan-list-title">TaskPlan</h2>
        <p>查看等待确认、执行中以及已经结束的结构化任务。</p>
      </header>
      <div className={styles.filters}>
        <label>
          状态
          <select
            onChange={(event) => setFilter('status', event.currentTarget.value)}
            value={status ?? ''}
          >
            <option value="">全部状态</option>
            {Object.entries(statusLabels).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          会话 ID
          <input
            onChange={(event) => setFilter('session_id', event.currentTarget.value)}
            value={sessionId ?? ''}
          />
        </label>
      </div>
      {query.isPending ? <PageSkeleton /> : null}
      {query.isError ? errorState(query.error, 'TaskPlan 列表加载失败') : null}
      {query.isSuccess && items.length === 0 ? (
        <EmptyState description="当前筛选条件下没有任务。" title="暂无 TaskPlan" />
      ) : null}
      {items.length > 0 ? (
        <ol aria-label="TaskPlan 列表" className={styles.list}>
          {items.map((item) => (
            <li key={item.taskPlanId}>
              <Link className={styles.cardLink} to={`/tasks/${encodeURIComponent(item.taskPlanId)}`}>
                <span className={styles.cardTitle}>{item.summary}</span>
                <span>{item.taskKind === 'question_decomposition' ? '研究任务' : '文档任务'}</span>
                <span className={styles.status}>{statusLabels[item.status]}</span>
              </Link>
            </li>
          ))}
        </ol>
      ) : null}
      {query.hasNextPage ? (
        <Button
          disabled={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
          type="button"
          variant="secondary"
        >
          {query.isFetchingNextPage ? '正在加载…' : '加载更多任务'}
        </Button>
      ) : null}
    </section>
  )
}

function ResearchFacts({ detail }: { detail: ResearchTaskPlanDetail }) {
  return (
    <section className={styles.panel} aria-labelledby="research-facts-title">
      <h3 id="research-facts-title">研究计划</h3>
      <dl className={styles.facts}>
        <div><dt>需求</dt><dd>{detail.requirements.length}</dd></div>
        <div><dt>子问题</dt><dd>{detail.subQuestions.length}</dd></div>
        <div><dt>证据</dt><dd>{detail.evidence.length}</dd></div>
        <div><dt>当前波次</dt><dd>{detail.progress.current_wave}</dd></div>
      </dl>
      <p>{detail.finalSynthesisInstruction}</p>
    </section>
  )
}

function DocumentFacts({ detail }: { detail: DocumentTaskPlanDetail }) {
  return (
    <section className={styles.panel} aria-labelledby="document-steps-title">
      <h3 id="document-steps-title">文档步骤</h3>
      <ol className={styles.steps}>
        {detail.steps.map((step) => (
          <li key={step.stepId}>
            <strong>{step.toolName}</strong>
            <span>{step.status} · 风险 {step.riskLevel}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}

function streamStatusMessage(status: ReturnType<typeof createInitialTaskPlanStreamState>['status']) {
  switch (status) {
    case 'connecting':
      return '正在连接执行流…'
    case 'streaming':
      return '任务正在执行…'
    case 'completed':
      return '执行流已完成，正在同步最新状态。'
    case 'failed':
      return '执行流失败，已重新读取服务端状态。'
    case 'interrupted':
      return '连接提前结束，已重新读取服务端状态。'
    case 'cancelled':
      return '已停止本地接收，服务端任务状态正在重新同步。'
    default:
      return ''
  }
}

function timelineEventLabel(event: string): string {
  switch (event) {
    case 'agent_task_status':
      return '任务状态已更新'
    case 'agent_task_execution_started':
      return '任务已开始执行'
    case 'agent_task_final_synthesis_completed':
      return '最终结论已汇总'
    case 'agent_task_step_completed':
      return '执行步骤已完成'
    case 'agent_task_step_failed':
      return '执行步骤失败'
    case 'sub_question_completed':
      return '研究子问题已完成'
    case 'guard_blocked':
      return '安全检查已阻止不安全内容'
    case 'guard_sanitized':
      return '安全检查已净化内容'
    case 'done':
      return '执行流已完成'
    case 'error':
      return '执行流失败'
    default:
      if (event.startsWith('agent_task_document_') || event === 'document_progress') {
        return '文档执行进度已更新'
      }
      if (
        event.startsWith('agent_task_research_') ||
        event.startsWith('agent_task_sub_question_') ||
        event.startsWith('sub_question_')
      ) {
        return '研究执行进度已更新'
      }
      if (event.startsWith('requirement_')) {
        return '证据要求状态已更新'
      }
      return '执行进度已更新'
  }
}

function TaskPlanDetailView({
  api,
  taskPlanId,
  userBoundary,
}: TaskPlanWorkspaceProps & { taskPlanId: string }) {
  const queryClient = useQueryClient()
  const detailQuery = useTaskPlanDetail(api, userBoundary, taskPlanId)
  const markdownQuery = useTaskPlanMarkdown(api, userBoundary, taskPlanId)
  const cancelMutation = useCancelTaskPlan(api, userBoundary, taskPlanId)
  const retryMutation = useRetryTaskPlan(api, userBoundary, taskPlanId)
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false)
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false)
  const [confirmError, setConfirmError] = useState<ApiError | null>(null)
  const [streamState, dispatchStream] = useReducer(
    taskPlanStreamReducer,
    undefined,
    createInitialTaskPlanStreamState,
  )
  const activeController = useRef<AbortController | null>(null)
  const streamActive =
    streamState.status === 'connecting' || streamState.status === 'streaming'

  useEffect(() => {
    return () => activeController.current?.abort()
  }, [])

  const reconcileFacts = () =>
    Promise.all([
      queryClient.invalidateQueries({
        queryKey: taskPlanKeys.detail(userBoundary, taskPlanId),
      }),
      queryClient.invalidateQueries({
        queryKey: taskPlanKeys.listRoot(userBoundary),
      }),
    ])

  const confirmTaskPlan = async () => {
    if (streamActive) return
    const requestId = crypto.randomUUID()
    const idempotencyKey = crypto.randomUUID()
    const controller = new AbortController()
    activeController.current = controller
    setConfirmDialogOpen(false)
    setConfirmError(null)
    dispatchStream({ requestId, taskPlanId, type: 'start' })

    try {
      let terminalReceived = false
      for await (const event of api.confirmTaskPlan(
        taskPlanId,
        requestId,
        idempotencyKey,
        controller.signal,
      )) {
        dispatchStream({ event, type: 'event' })
        if (event.event === 'done' || event.event === 'error') {
          terminalReceived = true
          break
        }
      }
      if (!terminalReceived) {
        dispatchStream({ message: null, type: 'interrupt' })
      }
    } catch (error) {
      if (controller.signal.aborted) {
        dispatchStream({ message: null, type: 'cancel' })
      } else if (
        error instanceof ApiError &&
        error.statusKind !== 'protocol'
      ) {
        setConfirmError(error)
        dispatchStream({ message: null, type: 'fail' })
      } else {
        dispatchStream({ message: null, type: 'interrupt' })
      }
    } finally {
      if (activeController.current === controller) {
        activeController.current = null
      }
      await reconcileFacts()
    }
  }

  if (detailQuery.isPending) return <PageSkeleton />
  if (detailQuery.isError) return errorState(detailQuery.error, 'TaskPlan 详情不可用')
  const detail = detailQuery.data
  const actions = availableTaskPlanActions(detail.taskKind, detail.status)
  const controlsPending =
    cancelMutation.isPending || retryMutation.isPending || streamActive

  return (
    <article className={styles.page} aria-labelledby="task-plan-detail-title">
      <Link to="/tasks">← 返回 TaskPlan 列表</Link>
      <header className={styles.detailHeader}>
        <p className={styles.eyebrow}>
          {detail.kind === 'research' ? 'Research TaskPlan' : 'Document TaskPlan'}
        </p>
        <h2 id="task-plan-detail-title">{detail.objective}</h2>
        <span className={styles.status}>{statusLabels[detail.status]}</span>
      </header>
      {actions.length > 0 ? (
        <div className={styles.actions}>
          {actions.includes('confirm') ? (
            <Button
              disabled={controlsPending}
              onClick={() => setConfirmDialogOpen(true)}
              type="button"
            >
              确认执行
            </Button>
          ) : null}
          {actions.includes('retry') ? (
            <Button
              disabled={controlsPending}
              onClick={() => retryMutation.mutate(crypto.randomUUID())}
              type="button"
            >
              {retryMutation.isPending ? '正在重试…' : '重试任务'}
            </Button>
          ) : null}
          {actions.includes('cancel') ? (
            <Button
              disabled={controlsPending}
              onClick={() => setCancelDialogOpen(true)}
              type="button"
              variant="secondary"
            >
              取消任务
            </Button>
          ) : null}
          {streamActive ? (
            <Button
              onClick={() => activeController.current?.abort()}
              type="button"
              variant="secondary"
            >
              停止接收
            </Button>
          ) : null}
        </div>
      ) : null}
      {retryMutation.isError
        ? errorState(retryMutation.error, 'TaskPlan 重试失败')
        : null}
      {cancelMutation.isError
        ? errorState(cancelMutation.error, 'TaskPlan 取消失败')
        : null}
      {confirmError ? errorState(confirmError, 'TaskPlan 确认失败') : null}
      {streamState.status !== 'idle' ? (
        <section aria-live="polite" className={styles.panel}>
          <h3>执行进度</h3>
          <p>{streamStatusMessage(streamState.status)}</p>
          {streamState.errorMessage ? <p>{streamState.errorMessage}</p> : null}
          {streamState.answer ? (
            <MarkdownViewer markdown={streamState.answer} />
          ) : null}
          {streamState.timeline.length > 0 ? (
            <ol aria-label="TaskPlan 执行时间线" className={styles.steps}>
              {streamState.timeline.map((item, index) => (
                <li key={`${item.receivedAt}-${item.event}-${index}`}>
                  {item.status === 'unsupported_event'
                    ? '收到当前版本暂不支持的公开事件'
                    : timelineEventLabel(item.event)}
                </li>
              ))}
            </ol>
          ) : null}
          {streamState.sources.length > 0 ? (
            <ul aria-label="TaskPlan 执行来源" className={styles.steps}>
              {streamState.sources.map((source) => (
                <li key={source.id}>{source.title}</li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}
      {detail.kind === 'research' ? (
        <ResearchFacts detail={detail} />
      ) : (
        <DocumentFacts detail={detail} />
      )}
      <section className={styles.panel} aria-labelledby="task-plan-markdown-title">
        <h3 id="task-plan-markdown-title">计划审查</h3>
        {markdownQuery.isPending ? <PageSkeleton /> : null}
        {markdownQuery.isError
          ? errorState(markdownQuery.error, '计划 Markdown 加载失败')
          : null}
        {markdownQuery.isSuccess ? (
          <MarkdownViewer markdown={markdownQuery.data} />
        ) : null}
      </section>
      <Dialog
        label="确认执行 TaskPlan"
        onClose={() => {
          if (!streamActive) setConfirmDialogOpen(false)
        }}
        open={confirmDialogOpen}
      >
        <p>确认后服务端将开始执行真实任务。请先完成上方计划审查。</p>
        <div className={styles.actions}>
          <Button
            disabled={controlsPending}
            onClick={() => void confirmTaskPlan()}
            type="button"
          >
            开始执行
          </Button>
          <Button
            disabled={controlsPending}
            onClick={() => setConfirmDialogOpen(false)}
            type="button"
            variant="secondary"
          >
            返回
          </Button>
        </div>
      </Dialog>
      <Dialog
        label="取消 TaskPlan"
        onClose={() => {
          if (!cancelMutation.isPending) setCancelDialogOpen(false)
        }}
        open={cancelDialogOpen}
      >
        <p>取消是服务端操作，运行中的任务会在安全屏障后停止。</p>
        <div className={styles.actions}>
          <Button
            disabled={controlsPending}
            onClick={() =>
              cancelMutation.mutate(crypto.randomUUID(), {
                onSuccess: () => setCancelDialogOpen(false),
              })
            }
            type="button"
          >
            {cancelMutation.isPending ? '正在取消…' : '确认取消'}
          </Button>
          <Button
            disabled={controlsPending}
            onClick={() => setCancelDialogOpen(false)}
            type="button"
            variant="secondary"
          >
            返回
          </Button>
        </div>
      </Dialog>
    </article>
  )
}

export function TaskPlanWorkspace({ api, taskPlanId, userBoundary }: TaskPlanWorkspaceProps) {
  return taskPlanId === null ? (
    <TaskPlanListView api={api} userBoundary={userBoundary} />
  ) : (
    <TaskPlanDetailView api={api} taskPlanId={taskPlanId} userBoundary={userBoundary} />
  )
}
