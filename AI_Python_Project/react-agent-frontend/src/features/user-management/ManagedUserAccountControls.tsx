import { useState } from 'react'

import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorState } from '@/components/ui/PageState'
import { TextField } from '@/components/ui/TextField'
import type { UserManagementApi } from '@/features/user-management/user-management-api'
import type { ManagedUserDetail } from '@/features/user-management/user-management-models'
import {
  useResetManagedUserPassword,
  useUpdateManagedUserStatus,
} from '@/features/user-management/user-management-queries'
import styles from '@/features/user-management/UserManagementWorkspace.module.css'


interface ManagedUserAccountControlsProps {
  api: UserManagementApi
  detail: ManagedUserDetail
  onMutationError: (error: unknown) => void
  onMutationSuccess: () => void
  userBoundary: string
}

interface CredentialRevocationNotice {
  action: 'password-reset' | 'status-active' | 'status-disabled'
  apiKeyCount: number
  refreshTokenCount: number
}

function fieldError(error: unknown, field: string): string | undefined {
  if (!(error instanceof ApiError)) return undefined
  return error.fieldErrors.find((item) => item.field === field)?.message
}

function safeMutationError(error: unknown, message: string) {
  return (
    <ErrorState
      code={error instanceof ApiError ? error.code : undefined}
      message={message}
      requestId={error instanceof ApiError ? error.requestId : undefined}
    />
  )
}

function revocationMessage(notice: CredentialRevocationNotice): string {
  const action =
    notice.action === 'password-reset'
      ? '密码已重置'
      : notice.action === 'status-disabled'
        ? '账号已禁用'
        : '账号已启用'
  return `${action}。已撤销 ${notice.refreshTokenCount} 个 refresh token 和 ${notice.apiKeyCount} 个 API Key。`
}

export function ManagedUserAccountControls({
  api,
  detail,
  onMutationError,
  onMutationSuccess,
  userBoundary,
}: ManagedUserAccountControlsProps) {
  const statusMutation = useUpdateManagedUserStatus(
    api,
    userBoundary,
    detail.userId,
  )
  const passwordMutation = useResetManagedUserPassword(
    api,
    userBoundary,
    detail.userId,
  )
  const [statusDialogOpen, setStatusDialogOpen] = useState(false)
  const [passwordDialogOpen, setPasswordDialogOpen] = useState(false)
  const [newPassword, setNewPassword] = useState('')
  const [notice, setNotice] = useState<CredentialRevocationNotice | null>(null)
  const nextStatus = detail.status === 'active' ? 'disabled' : 'active'
  const statusAction = nextStatus === 'disabled' ? '禁用' : '启用'
  const statusError = fieldError(statusMutation.error, 'status')
  const passwordError = fieldError(passwordMutation.error, 'new_password')

  const closeStatusDialog = () => {
    if (statusMutation.isPending) return
    statusMutation.reset()
    setStatusDialogOpen(false)
  }

  const closePasswordDialog = () => {
    if (passwordMutation.isPending) return
    passwordMutation.reset()
    setNewPassword('')
    setPasswordDialogOpen(false)
  }

  const updateStatus = async () => {
    statusMutation.reset()
    try {
      const result = await statusMutation.mutateAsync({ status: nextStatus })
      setNotice({
        action: nextStatus === 'disabled' ? 'status-disabled' : 'status-active',
        apiKeyCount: result.revokedApiKeyCount,
        refreshTokenCount: result.revokedRefreshTokenCount,
      })
      setStatusDialogOpen(false)
      onMutationSuccess()
    } catch (error) {
      // Mutation state owns the safe public error projection.
      onMutationError(error)
    }
  }

  const resetPassword = async () => {
    passwordMutation.reset()
    try {
      const result = await passwordMutation.mutateAsync({
        new_password: newPassword,
      })
      setNotice({
        action: 'password-reset',
        apiKeyCount: result.revokedApiKeyCount,
        refreshTokenCount: result.revokedRefreshTokenCount,
      })
      setPasswordDialogOpen(false)
      onMutationSuccess()
    } catch (error) {
      // Mutation state owns the safe public error projection.
      onMutationError(error)
    } finally {
      setNewPassword('')
    }
  }

  return (
    <section aria-labelledby="managed-user-account-controls" className={styles.panel}>
      <h3 id="managed-user-account-controls">账号控制</h3>
      <div className={styles.detailActions}>
        <Button
          onClick={() => {
            statusMutation.reset()
            setStatusDialogOpen(true)
          }}
          type="button"
          variant="secondary"
        >
          {statusAction}账号
        </Button>
        <Button
          onClick={() => {
            passwordMutation.reset()
            setNewPassword('')
            setPasswordDialogOpen(true)
          }}
          type="button"
          variant="secondary"
        >
          重置密码
        </Button>
      </div>
      {notice ? (
        <p className={styles.catalogNotice} role="status">
          {revocationMessage(notice)}
        </p>
      ) : null}
      <Dialog
        label={`确认${statusAction}账号`}
        onClose={closeStatusDialog}
        open={statusDialogOpen}
      >
        <div className={styles.mutationForm}>
          <p>
            {nextStatus === 'disabled'
              ? '禁用会撤销该账号现有的 refresh token 和 API Key。'
              : '启用后该账号仍需使用有效凭证重新认证。'}
          </p>
          {statusError ? (
            <p className={styles.fieldError}>{statusError}</p>
          ) : null}
          {statusMutation.isError && !statusError
            ? safeMutationError(statusMutation.error, '修改账号状态失败')
            : null}
          <Button
            disabled={statusMutation.isPending}
            onClick={() => void updateStatus()}
            type="button"
          >
            {statusMutation.isPending ? `正在${statusAction}…` : `确认${statusAction}`}
          </Button>
        </div>
      </Dialog>
      <Dialog
        label="重置用户密码"
        onClose={closePasswordDialog}
        open={passwordDialogOpen}
      >
        <form
          className={styles.mutationForm}
          noValidate
          onSubmit={(event) => {
            event.preventDefault()
            void resetPassword()
          }}
        >
          <p>重置密码会撤销该账号现有的 refresh token 和 API Key。</p>
          <TextField
            autoComplete="new-password"
            disabled={passwordMutation.isPending}
            error={passwordError}
            id="managed-user-reset-password"
            label="新密码"
            onChange={(event) => setNewPassword(event.currentTarget.value)}
            type="password"
            value={newPassword}
          />
          {passwordMutation.isError && !passwordError
            ? safeMutationError(passwordMutation.error, '重置密码失败')
            : null}
          <Button disabled={passwordMutation.isPending} type="submit">
            {passwordMutation.isPending ? '正在重置…' : '确认重置密码'}
          </Button>
        </form>
      </Dialog>
    </section>
  )
}
