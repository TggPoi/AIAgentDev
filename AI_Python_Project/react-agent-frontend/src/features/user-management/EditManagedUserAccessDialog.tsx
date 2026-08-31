import { useState } from 'react'

import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorState } from '@/components/ui/PageState'
import type { UserManagementApi } from '@/features/user-management/user-management-api'
import {
  buildReplaceManagedUserAccessRequest,
  reconcileAccessDraft,
  type AccessDraftValidationErrors,
  type ManagedUserAccessDraft,
} from '@/features/user-management/user-management-draft'
import { ManagedUserAccessFields } from '@/features/user-management/ManagedUserAccessFields'
import type {
  AccessCatalog,
  ManagedUserDetail,
} from '@/features/user-management/user-management-models'
import { useReplaceManagedUserAccess } from '@/features/user-management/user-management-queries'
import styles from '@/features/user-management/UserManagementWorkspace.module.css'


interface EditManagedUserAccessDialogProps {
  api: UserManagementApi
  catalog: AccessCatalog
  detail: ManagedUserDetail
  onClose: () => void
  onMutationSuccess: () => void
  open: boolean
  userBoundary: string
}

function detailAccessDraft(detail: ManagedUserDetail): ManagedUserAccessDraft {
  return {
    accountType: detail.accountType,
    departmentAccess: detail.departmentAccess.map((department) => ({
      departmentCode: department.departmentCode,
      isPrimary: department.isPrimary,
      roleCodes: [...department.roleCodes],
    })),
    directPermissionCodes: [...detail.directPermissionCodes],
  }
}

function serverFieldErrors(error: unknown): AccessDraftValidationErrors {
  if (!(error instanceof ApiError)) return {}
  const errors: AccessDraftValidationErrors = {}
  for (const item of error.fieldErrors) {
    if (item.field === 'account_type') errors.accountType = item.message
    else if (item.field === 'department_access') {
      errors.departmentAccess = item.message
    } else if (item.field === 'direct_permission_codes') {
      errors.directPermissionCodes = item.message
    }
  }
  return errors
}

export function EditManagedUserAccessDialog({
  api,
  catalog,
  detail,
  onClose,
  onMutationSuccess,
  open,
  userBoundary,
}: EditManagedUserAccessDialogProps) {
  const mutation = useReplaceManagedUserAccess(
    api,
    userBoundary,
    detail.userId,
  )
  const [access, setAccess] = useState<ManagedUserAccessDraft>(() =>
    detailAccessDraft(detail),
  )
  const [localErrors, setLocalErrors] =
    useState<AccessDraftValidationErrors>({})
  const [confirmedCatalog, setConfirmedCatalog] =
    useState<AccessCatalog | null>(null)
  const [accountTypeConfirmation, setAccountTypeConfirmation] =
    useState(false)
  const catalogReconciliation = reconcileAccessDraft(access, catalog)
  const effectiveAccess = catalogReconciliation.draft
  const catalogNeedsConfirmation =
    catalogReconciliation.requiresReconfirmation &&
    confirmedCatalog !== catalog
  const mappedServerErrors = serverFieldErrors(mutation.error)
  const errors = { ...localErrors, ...mappedServerErrors }
  const hasServerFieldError = Object.keys(mappedServerErrors).length > 0

  const close = () => {
    if (!mutation.isPending) onClose()
  }

  const submit = async (accountTypeConfirmed = false) => {
    mutation.reset()
    if (catalogNeedsConfirmation) {
      setLocalErrors({
        departmentAccess: '请先确认访问目录变化后的最新选择。',
      })
      return
    }
    const result = buildReplaceManagedUserAccessRequest(
      effectiveAccess,
      catalog,
    )
    if (!result.ok) {
      setLocalErrors(result.errors)
      return
    }
    if (
      result.request.account_type !== detail.accountType &&
      !accountTypeConfirmed
    ) {
      setLocalErrors({})
      setAccountTypeConfirmation(true)
      return
    }

    setLocalErrors({})
    try {
      await mutation.mutateAsync(result.request)
      onClose()
      onMutationSuccess()
    } catch {
      // Mutation state owns the safe public error projection.
    }
  }

  return (
    <Dialog label="编辑用户访问" onClose={close} open={open}>
      <form
        className={styles.mutationForm}
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <ManagedUserAccessFields
          catalog={catalog}
          disabled={mutation.isPending}
          draft={effectiveAccess}
          errors={errors}
          onChange={(next) => {
            setAccess(next)
            setConfirmedCatalog(catalog)
            setAccountTypeConfirmation(false)
            setLocalErrors({})
          }}
        />
        {catalogNeedsConfirmation ? (
          <div className={styles.catalogNotice} role="alert">
            <p>访问目录已变化，已移除不再允许的选择。</p>
            <Button
              disabled={mutation.isPending}
              onClick={() => {
                setAccess(effectiveAccess)
                setConfirmedCatalog(catalog)
                setAccountTypeConfirmation(false)
                setLocalErrors({})
              }}
              type="button"
              variant="secondary"
            >
              确认已审查最新目录
            </Button>
          </div>
        ) : null}
        {accountTypeConfirmation ? (
          <div className={styles.catalogNotice} role="alert">
            <p>账号类型变更会改变该用户的访问边界，请再次确认。</p>
            <Button
              disabled={mutation.isPending}
              onClick={() => void submit(true)}
              type="button"
              variant="secondary"
            >
              确认账号类型变更并保存
            </Button>
          </div>
        ) : null}
        {mutation.isError && !hasServerFieldError ? (
          <ErrorState
            code={
              mutation.error instanceof ApiError
                ? mutation.error.code
                : undefined
            }
            message="保存访问失败"
            requestId={
              mutation.error instanceof ApiError
                ? mutation.error.requestId
                : undefined
            }
          />
        ) : null}
        <Button disabled={mutation.isPending} type="submit">
          {mutation.isPending ? '正在保存…' : '保存访问'}
        </Button>
      </form>
    </Dialog>
  )
}
