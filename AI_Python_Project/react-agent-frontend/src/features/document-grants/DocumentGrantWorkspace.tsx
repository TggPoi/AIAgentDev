import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, PageSkeleton } from '@/components/ui/PageState'
import { TextField } from '@/components/ui/TextField'
import type { DocumentGrantApi } from '@/features/document-grants/document-grant-api'
import { CreateDocumentGrantDialog } from '@/features/document-grants/CreateDocumentGrantDialog'
import {
  type CreateDocumentGrantsResult,
  mergeDocumentGrantPages,
  type DocumentGrantStatus,
} from '@/features/document-grants/document-grant-models'
import { useDocumentGrantList } from '@/features/document-grants/document-grant-queries'
import styles from '@/features/document-grants/DocumentGrantWorkspace.module.css'


interface DocumentGrantWorkspaceProps {
  api: DocumentGrantApi
  canFilterGrantableDepartment: boolean
  userBoundary: string
}

const grantStatuses = new Set<DocumentGrantStatus>(['active', 'revoked'])
const statusLabels: Record<DocumentGrantStatus, string> = {
  active: '生效中',
  revoked: '已撤销',
}

function fieldError(error: unknown, field: string): string | undefined {
  if (!(error instanceof ApiError)) return undefined
  return error.fieldErrors.find((item) => item.field === field)?.message
}

function safeErrorState(error: unknown) {
  return (
    <ErrorState
      code={error instanceof ApiError ? error.code : undefined}
      message="文档授权列表加载失败"
      requestId={error instanceof ApiError ? error.requestId : undefined}
    />
  )
}

export function DocumentGrantWorkspace({
  api,
  canFilterGrantableDepartment,
  userBoundary,
}: DocumentGrantWorkspaceProps) {
  const [createOpen, setCreateOpen] = useState(false)
  const [createResult, setCreateResult] =
    useState<CreateDocumentGrantsResult | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const targetAccount = searchParams.get('target_account') || null
  const documentId = searchParams.get('doc_id') || null
  const departmentCode = searchParams.get('department_code') || null
  const statusValue = searchParams.get('status')
  const status =
    statusValue !== null &&
    grantStatuses.has(statusValue as DocumentGrantStatus)
      ? (statusValue as DocumentGrantStatus)
      : null
  const listQuery = useDocumentGrantList(api, userBoundary, {
    departmentCode,
    documentId,
    status,
    targetAccount,
  })
  const items = mergeDocumentGrantPages(listQuery.data?.pages ?? [])
  const targetAccountError = fieldError(listQuery.error, 'target_account')
  const documentIdError = fieldError(listQuery.error, 'doc_id')
  const statusError = fieldError(listQuery.error, 'status')
  const departmentError = fieldError(listQuery.error, 'department_code')
  const hasFieldError = Boolean(
    targetAccountError || documentIdError || statusError || departmentError,
  )

  const setFilter = (
    name: 'department_code' | 'doc_id' | 'status' | 'target_account',
    value: string,
  ) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(name, value)
    else next.delete(name)
    setSearchParams(next, { replace: true })
  }

  return (
    <section aria-labelledby="document-grant-list-title" className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Administration</p>
          <h2 id="document-grant-list-title">跨部门授权</h2>
          <p>查看当前身份获准管理的非公开文档精确只读授权。</p>
        </div>
        <Button onClick={() => setCreateOpen(true)} type="button">
          创建授权
        </Button>
      </header>
      {createResult ? (
        <p aria-label="文档授权创建结果" className={styles.success} role="status">
          新建 {createResult.createdCount} 条，已存在 {createResult.existingCount}{' '}
          条
        </p>
      ) : null}
      <div className={styles.filters}>
        <TextField
          error={targetAccountError}
          id="document-grant-target-account"
          label="目标账号"
          onChange={(event) =>
            setFilter('target_account', event.currentTarget.value)
          }
          value={targetAccount ?? ''}
        />
        <TextField
          error={documentIdError}
          id="document-grant-document-id"
          label="文档 ID"
          onChange={(event) => setFilter('doc_id', event.currentTarget.value)}
          value={documentId ?? ''}
        />
        <label className={styles.selectField}>
          授权状态
          <select
            aria-invalid={statusError ? 'true' : 'false'}
            onChange={(event) =>
              setFilter('status', event.currentTarget.value)
            }
            value={status ?? ''}
          >
            <option value="">全部状态</option>
            <option value="active">生效中</option>
            <option value="revoked">已撤销</option>
          </select>
          {statusError ? (
            <span className={styles.fieldError}>{statusError}</span>
          ) : null}
        </label>
        <TextField
          error={departmentError}
          id="document-grant-department"
          label="文档部门"
          onChange={(event) =>
            setFilter('department_code', event.currentTarget.value)
          }
          value={departmentCode ?? ''}
        />
      </div>
      {listQuery.isPending ? <PageSkeleton /> : null}
      {listQuery.isError && !hasFieldError
        ? safeErrorState(listQuery.error)
        : null}
      {listQuery.isSuccess && items.length === 0 ? (
        <EmptyState
          description="当前管理范围与筛选条件下没有文档授权。"
          title="暂无授权记录"
        />
      ) : null}
      {items.length > 0 ? (
        <ol aria-label="文档授权列表" className={styles.list}>
          {items.map((item) => (
            <li className={styles.card} key={item.grantId}>
              <div className={styles.cardHeader}>
                <strong>{item.repositoryPath}</strong>
                <span className={styles.badge}>{statusLabels[item.status]}</span>
              </div>
              <dl className={styles.facts}>
                <div>
                  <dt>文档 ID</dt>
                  <dd>{item.documentId}</dd>
                </div>
                <div>
                  <dt>文档部门</dt>
                  <dd>{item.documentDepartmentCode}</dd>
                </div>
                <div>
                  <dt>目标账号</dt>
                  <dd>{item.grantee.username}</dd>
                </div>
              </dl>
              <p>
                授权人：{item.grantedByUserId} · 授权时间：{item.grantedAt}
              </p>
              {item.status === 'revoked' ? (
                <p>
                  撤销人：{item.revokedByUserId ?? '未知'} · 撤销时间：
                  {item.revokedAt ?? '未知'}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
      {listQuery.hasNextPage ? (
        <Button
          disabled={listQuery.isFetchingNextPage}
          onClick={() => void listQuery.fetchNextPage()}
          type="button"
          variant="secondary"
        >
          {listQuery.isFetchingNextPage ? '正在加载…' : '加载更多授权'}
        </Button>
      ) : null}
      {createOpen ? (
        <CreateDocumentGrantDialog
          api={api}
          canFilterDepartment={canFilterGrantableDepartment}
          onClose={() => setCreateOpen(false)}
          onCreated={setCreateResult}
          userBoundary={userBoundary}
        />
      ) : null}
    </section>
  )
}
