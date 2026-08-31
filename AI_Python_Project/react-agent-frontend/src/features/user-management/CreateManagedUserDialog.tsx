import { useState } from 'react'

import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorState } from '@/components/ui/PageState'
import { TextField } from '@/components/ui/TextField'
import type { UserManagementApi } from '@/features/user-management/user-management-api'
import {
  buildCreateManagedUserRequest,
  reconcileAccessDraft,
  type AccessDraftValidationErrors,
  type ManagedUserAccessDraft,
} from '@/features/user-management/user-management-draft'
import { ManagedUserAccessFields } from '@/features/user-management/ManagedUserAccessFields'
import type { AccessCatalog } from '@/features/user-management/user-management-models'
import { useCreateManagedUser } from '@/features/user-management/user-management-queries'
import styles from '@/features/user-management/UserManagementWorkspace.module.css'


interface CreateManagedUserDialogProps {
  api: UserManagementApi
  catalog: AccessCatalog
  onClose: () => void
  onCreated: (userId: string) => void
  open: boolean
  userBoundary: string
}

interface CreateFieldErrors extends AccessDraftValidationErrors {
  displayName?: string
  email?: string
  password?: string
  username?: string
}

function emptyAccessDraft(): ManagedUserAccessDraft {
  return {
    accountType: '',
    departmentAccess: [],
    directPermissionCodes: [],
  }
}

function serverFieldErrors(error: unknown): CreateFieldErrors {
  if (!(error instanceof ApiError)) return {}
  const errors: CreateFieldErrors = {}
  for (const item of error.fieldErrors) {
    if (item.field === 'username') errors.username = item.message
    else if (item.field === 'password') errors.password = item.message
    else if (item.field === 'email') errors.email = item.message
    else if (item.field === 'display_name') errors.displayName = item.message
    else if (item.field === 'account_type') errors.accountType = item.message
    else if (item.field === 'department_access') {
      errors.departmentAccess = item.message
    } else if (item.field === 'direct_permission_codes') {
      errors.directPermissionCodes = item.message
    }
  }
  return errors
}

export function CreateManagedUserDialog({
  api,
  catalog,
  onClose,
  onCreated,
  open,
  userBoundary,
}: CreateManagedUserDialogProps) {
  const mutation = useCreateManagedUser(api, userBoundary)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [access, setAccess] = useState<ManagedUserAccessDraft>(emptyAccessDraft)
  const [localErrors, setLocalErrors] = useState<CreateFieldErrors>({})
  const [confirmedCatalog, setConfirmedCatalog] =
    useState<AccessCatalog | null>(null)
  const errors = { ...localErrors, ...serverFieldErrors(mutation.error) }
  const catalogReconciliation = reconcileAccessDraft(access, catalog)
  const effectiveAccess = catalogReconciliation.draft
  const catalogNeedsConfirmation =
    catalogReconciliation.requiresReconfirmation &&
    confirmedCatalog !== catalog

  const clear = () => {
    setUsername('')
    setPassword('')
    setEmail('')
    setDisplayName('')
    setAccess(emptyAccessDraft())
    setLocalErrors({})
    setConfirmedCatalog(null)
    mutation.reset()
  }

  const close = () => {
    if (mutation.isPending) return
    clear()
    onClose()
  }

  const submit = async () => {
    mutation.reset()
    if (catalogNeedsConfirmation) {
      setLocalErrors({
        departmentAccess: '请先确认访问目录变化后的最新选择。',
      })
      setPassword('')
      return
    }
    const result = buildCreateManagedUserRequest(
      {
        access: effectiveAccess,
        displayName: displayName.trim() || null,
        email: email.trim() || null,
        password,
        username,
      },
      catalog,
    )
    if (!result.ok) {
      setLocalErrors(result.errors)
      setPassword('')
      return
    }
    setLocalErrors({})
    try {
      const created = await mutation.mutateAsync(result.request)
      clear()
      onClose()
      onCreated(created.userId)
    } catch {
      // Mutation state owns the safe public error projection.
    } finally {
      setPassword('')
    }
  }

  const hasServerFieldError = Object.keys(serverFieldErrors(mutation.error)).length > 0

  return (
    <Dialog label="创建账号" onClose={close} open={open}>
      <form
        className={styles.mutationForm}
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <div className={styles.identityFields}>
          <TextField
            autoComplete="off"
            disabled={mutation.isPending}
            error={errors.username}
            id="managed-user-create-username"
            label="用户名"
            onChange={(event) => setUsername(event.currentTarget.value)}
            value={username}
          />
          <TextField
            autoComplete="new-password"
            disabled={mutation.isPending}
            error={errors.password}
            id="managed-user-create-password"
            label="初始密码"
            onChange={(event) => setPassword(event.currentTarget.value)}
            type="password"
            value={password}
          />
          <TextField
            disabled={mutation.isPending}
            error={errors.email}
            id="managed-user-create-email"
            label="邮箱（可选）"
            onChange={(event) => setEmail(event.currentTarget.value)}
            type="email"
            value={email}
          />
          <TextField
            disabled={mutation.isPending}
            error={errors.displayName}
            id="managed-user-create-display-name"
            label="展示名称（可选）"
            onChange={(event) => setDisplayName(event.currentTarget.value)}
            value={displayName}
          />
        </div>
        <ManagedUserAccessFields
          catalog={catalog}
          disabled={mutation.isPending}
          draft={effectiveAccess}
          errors={errors}
          onChange={(next) => {
            setAccess(next)
            setConfirmedCatalog(catalog)
            setLocalErrors({})
          }}
        />
        {catalogNeedsConfirmation ? (
          <div className={styles.catalogNotice} role="alert">
            <p>访问目录已变化，已移除不再允许的选择。</p>
            <Button
              onClick={() => {
                setAccess(effectiveAccess)
                setConfirmedCatalog(catalog)
                setLocalErrors({})
              }}
              type="button"
              variant="secondary"
            >
              确认已审查最新目录
            </Button>
          </div>
        ) : null}
        {mutation.isError && !hasServerFieldError ? (
          <ErrorState
            code={mutation.error instanceof ApiError ? mutation.error.code : undefined}
            message="创建账号失败"
            requestId={
              mutation.error instanceof ApiError
                ? mutation.error.requestId
                : undefined
            }
          />
        ) : null}
        <Button disabled={mutation.isPending} type="submit">
          {mutation.isPending ? '正在创建…' : '确认创建'}
        </Button>
      </form>
    </Dialog>
  )
}
