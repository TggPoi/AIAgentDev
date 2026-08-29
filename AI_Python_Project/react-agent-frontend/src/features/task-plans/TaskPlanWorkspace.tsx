import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

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
} from '@/features/task-plans/task-plan-queries'
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

function TaskPlanDetailView({
  api,
  taskPlanId,
  userBoundary,
}: TaskPlanWorkspaceProps & { taskPlanId: string }) {
  const detailQuery = useTaskPlanDetail(api, userBoundary, taskPlanId)
  const markdownQuery = useTaskPlanMarkdown(api, userBoundary, taskPlanId)
  const cancelMutation = useCancelTaskPlan(api, userBoundary, taskPlanId)
  const retryMutation = useRetryTaskPlan(api, userBoundary, taskPlanId)
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false)

  if (detailQuery.isPending) return <PageSkeleton />
  if (detailQuery.isError) return errorState(detailQuery.error, 'TaskPlan 详情不可用')
  const detail = detailQuery.data
  const actions = availableTaskPlanActions(detail.taskKind, detail.status)
  const controlsPending = cancelMutation.isPending || retryMutation.isPending

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
      {actions.includes('retry') || actions.includes('cancel') ? (
        <div className={styles.actions}>
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
        </div>
      ) : null}
      {retryMutation.isError
        ? errorState(retryMutation.error, 'TaskPlan 重试失败')
        : null}
      {cancelMutation.isError
        ? errorState(cancelMutation.error, 'TaskPlan 取消失败')
        : null}
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
