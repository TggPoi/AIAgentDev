import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { EmptyState, ErrorState, PageSkeleton } from '@/components/ui/PageState'
import { TextField } from '@/components/ui/TextField'
import { CreateManagedUserDialog } from '@/features/user-management/CreateManagedUserDialog'
import { EditManagedUserAccessDialog } from '@/features/user-management/EditManagedUserAccessDialog'
import { ManagedUserAccountControls } from '@/features/user-management/ManagedUserAccountControls'
import type { UserManagementApi } from '@/features/user-management/user-management-api'
import {
  mergeManagedUserPages,
  type AccessCatalog,
  type AccessCatalogItem,
  type UserStatus,
} from '@/features/user-management/user-management-models'
import {
  useAccessCatalog,
  useManagedUserDetail,
  useManagedUserList,
} from '@/features/user-management/user-management-queries'
import styles from '@/features/user-management/UserManagementWorkspace.module.css'


interface UserManagementWorkspaceProps {
  api: UserManagementApi
  userBoundary: string
  userId: string | null
}

const userStatuses = new Set<UserStatus>(['active', 'disabled'])
const statusLabels: Record<UserStatus, string> = {
  active: '启用',
  disabled: '已禁用',
}

function safeErrorState(error: unknown, message: string) {
  return (
    <ErrorState
      code={error instanceof ApiError ? error.code : undefined}
      message={message}
      requestId={error instanceof ApiError ? error.requestId : undefined}
    />
  )
}

function fieldError(error: unknown, field: string): string | undefined {
  if (!(error instanceof ApiError)) return undefined
  return error.fieldErrors.find((item) => item.field === field)?.message
}

function catalogLabel(
  items: readonly AccessCatalogItem[],
  code: string,
): string {
  return items.find((item) => item.code === code)?.name ?? code
}

function UserListView({
  api,
  userBoundary,
}: Omit<UserManagementWorkspaceProps, 'userId'>) {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [createOpen, setCreateOpen] = useState(false)
  const query = searchParams.get('query') || null
  const departmentCode = searchParams.get('department_code') || null
  const statusValue = searchParams.get('status')
  const status =
    statusValue !== null && userStatuses.has(statusValue as UserStatus)
      ? (statusValue as UserStatus)
      : null
  const catalogQuery = useAccessCatalog(api, userBoundary)
  const listQuery = useManagedUserList(api, userBoundary, {
    departmentCode,
    query,
    status,
  })
  const items = mergeManagedUserPages(listQuery.data?.pages ?? [])
  const queryError = fieldError(listQuery.error, 'query')
  const statusError = fieldError(listQuery.error, 'status')
  const departmentError = fieldError(listQuery.error, 'department_code')
  const hasFieldError = Boolean(queryError || statusError || departmentError)

  const setFilter = (
    name: 'department_code' | 'query' | 'status',
    value: string,
  ) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(name, value)
    else next.delete(name)
    setSearchParams(next, { replace: true })
  }

  return (
    <section aria-labelledby="managed-user-list-title" className={styles.page}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>Administration</p>
          <h2 id="managed-user-list-title">用户管理</h2>
          <p>查看当前身份获准管理的账号、部门归属与访问状态。</p>
        </div>
        <Button
          disabled={!catalogQuery.isSuccess}
          onClick={() => setCreateOpen(true)}
          type="button"
        >
          创建账号
        </Button>
      </header>
      <div className={styles.filters}>
        <TextField
          error={queryError}
          id="managed-user-query"
          label="关键词"
          onChange={(event) => setFilter('query', event.currentTarget.value)}
          value={query ?? ''}
        />
        <label className={styles.selectField}>
          账号状态
          <select
            aria-invalid={statusError ? 'true' : 'false'}
            onChange={(event) =>
              setFilter('status', event.currentTarget.value)
            }
            value={status ?? ''}
          >
            <option value="">全部状态</option>
            <option value="active">启用</option>
            <option value="disabled">已禁用</option>
          </select>
          {statusError ? (
            <span className={styles.fieldError}>{statusError}</span>
          ) : null}
        </label>
        <label className={styles.selectField}>
          部门
          <select
            aria-invalid={departmentError ? 'true' : 'false'}
            disabled={!catalogQuery.isSuccess}
            onChange={(event) =>
              setFilter('department_code', event.currentTarget.value)
            }
            value={departmentCode ?? ''}
          >
            <option value="">全部部门</option>
            {catalogQuery.data?.departments.map((department) => (
              <option key={department.code} value={department.code}>
                {department.name}
              </option>
            ))}
          </select>
          {departmentError ? (
            <span className={styles.fieldError}>{departmentError}</span>
          ) : null}
        </label>
      </div>
      {catalogQuery.isPending || listQuery.isPending ? <PageSkeleton /> : null}
      {catalogQuery.isError
        ? safeErrorState(catalogQuery.error, '访问目录加载失败')
        : null}
      {listQuery.isError && !hasFieldError
        ? safeErrorState(listQuery.error, '用户列表加载失败')
        : null}
      {listQuery.isSuccess && items.length === 0 ? (
        <EmptyState
          description="当前管理范围与筛选条件下没有用户。"
          title="暂无用户"
        />
      ) : null}
      {items.length > 0 ? (
        <ol aria-label="用户列表" className={styles.list}>
          {items.map((item) => (
            <li key={item.userId}>
              <Link
                className={styles.cardLink}
                to={`/admin/users/${encodeURIComponent(item.userId)}`}
              >
                <span className={styles.cardHeader}>
                  <strong>{item.username}</strong>
                  <span className={styles.badge}>
                    {statusLabels[item.status]}
                  </span>
                </span>
                <span>
                  {catalogQuery.isSuccess
                    ? catalogLabel(
                        catalogQuery.data.accountTypes,
                        item.accountType,
                      )
                    : item.accountType}
                </span>
                <span>
                  主部门：
                  {item.primaryDepartmentCode === null
                    ? '无'
                    : catalogQuery.isSuccess
                      ? catalogLabel(
                          catalogQuery.data.departments,
                          item.primaryDepartmentCode,
                        )
                      : item.primaryDepartmentCode}
                </span>
              </Link>
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
          {listQuery.isFetchingNextPage ? '正在加载…' : '加载更多用户'}
        </Button>
      ) : null}
      {catalogQuery.isSuccess ? (
        <CreateManagedUserDialog
          api={api}
          catalog={catalogQuery.data}
          onClose={() => setCreateOpen(false)}
          onCreated={(createdUserId) =>
            navigate(`/admin/users/${encodeURIComponent(createdUserId)}`)
          }
          open={createOpen}
          userBoundary={userBoundary}
        />
      ) : null}
    </section>
  )
}

function CodeList({
  catalogItems,
  codes,
  emptyText,
}: {
  catalogItems?: readonly AccessCatalogItem[]
  codes: readonly string[]
  emptyText: string
}) {
  return codes.length === 0 ? (
    <p className={styles.muted}>{emptyText}</p>
  ) : (
    <ul className={styles.codeList}>
      {codes.map((code) => (
        <li key={code}>{catalogItems ? catalogLabel(catalogItems, code) : code}</li>
      ))}
    </ul>
  )
}

function UserDetailView({
  api,
  userBoundary,
  userId,
}: UserManagementWorkspaceProps & { userId: string }) {
  const [editAccessOpen, setEditAccessOpen] = useState(false)
  const catalogQuery = useAccessCatalog(api, userBoundary)
  const detailQuery = useManagedUserDetail(api, userBoundary, userId)

  if (catalogQuery.isPending || detailQuery.isPending) return <PageSkeleton />
  if (detailQuery.isError) {
    const unavailable =
      detailQuery.error instanceof ApiError &&
      (detailQuery.error.statusKind === 'authorization' ||
        detailQuery.error.statusKind === 'not_found')
    return (
      <div className={styles.page}>
        <Link to="/admin/users">返回用户列表</Link>
        {safeErrorState(
          detailQuery.error,
          unavailable ? '用户不可用' : '用户详情加载失败',
        )}
      </div>
    )
  }
  if (catalogQuery.isError) {
    return (
      <div className={styles.page}>
        <Link to="/admin/users">返回用户列表</Link>
        {safeErrorState(catalogQuery.error, '访问目录加载失败')}
      </div>
    )
  }

  const detail = detailQuery.data
  const catalog: AccessCatalog = catalogQuery.data
  return (
    <article aria-labelledby="managed-user-detail-title" className={styles.page}>
      <Link to="/admin/users">← 返回用户列表</Link>
      <header className={styles.detailHeader}>
        <p className={styles.eyebrow}>{statusLabels[detail.status]}</p>
        <h2 id="managed-user-detail-title">{detail.username}</h2>
        <p>{detail.displayName ?? '未设置展示名称'}</p>
        <div className={styles.detailActions}>
          <Button onClick={() => setEditAccessOpen(true)} type="button">
            编辑访问
          </Button>
        </div>
      </header>
      <dl className={styles.facts}>
        <div>
          <dt>账号类型</dt>
          <dd>{catalogLabel(catalog.accountTypes, detail.accountType)}</dd>
        </div>
        <div>
          <dt>邮箱</dt>
          <dd>{detail.email ?? '未设置'}</dd>
        </div>
        <div>
          <dt>最近登录</dt>
          <dd>{detail.lastLoginAt ?? '尚未登录'}</dd>
        </div>
      </dl>
      <section className={styles.panel}>
        <h3>部门访问</h3>
        {detail.departmentAccess.map((department) => (
          <article className={styles.accessCard} key={department.departmentCode}>
            <h4>
              {catalogLabel(catalog.departments, department.departmentCode)}
              {department.isPrimary ? '（主部门）' : ''}
            </h4>
            <p>部门角色</p>
            <CodeList
              catalogItems={catalog.departmentRoles}
              codes={department.roleCodes}
              emptyText="无部门角色"
            />
            <p>部门有效权限</p>
            <CodeList
              codes={department.permissionCodes}
              emptyText="无部门有效权限"
            />
          </article>
        ))}
      </section>
      <section className={styles.panel}>
        <h3>全局访问</h3>
        <p>全局角色</p>
        <CodeList codes={detail.globalRoleCodes} emptyText="无全局角色" />
        <p>直接权限</p>
        <CodeList
          catalogItems={catalog.directPermissions}
          codes={detail.directPermissionCodes}
          emptyText="无直接权限"
        />
        <p>有效全局权限</p>
        <CodeList
          catalogItems={catalog.directPermissions}
          codes={detail.effectiveGlobalPermissionCodes}
          emptyText="无有效全局权限"
        />
      </section>
      <ManagedUserAccountControls
        api={api}
        detail={detail}
        userBoundary={userBoundary}
      />
      {editAccessOpen ? (
        <EditManagedUserAccessDialog
          api={api}
          catalog={catalog}
          detail={detail}
          onClose={() => setEditAccessOpen(false)}
          open
          userBoundary={userBoundary}
        />
      ) : null}
    </article>
  )
}

export function UserManagementWorkspace({
  api,
  userBoundary,
  userId,
}: UserManagementWorkspaceProps) {
  return userId === null ? (
    <UserListView api={api} userBoundary={userBoundary} />
  ) : (
    <UserDetailView
      api={api}
      userBoundary={userBoundary}
      userId={userId}
    />
  )
}
