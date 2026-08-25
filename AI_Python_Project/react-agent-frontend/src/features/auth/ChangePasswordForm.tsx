import { type FormEvent, useState } from 'react'

import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/TextField'
import styles from '@/features/auth/AuthForm.module.css'
import { useAuth } from '@/features/auth/AuthProvider'


interface ChangePasswordFieldErrors {
  current_password?: string
  new_password?: string
}

export function ChangePasswordForm() {
  const auth = useAuth()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [fieldErrors, setFieldErrors] =
    useState<ChangePasswordFieldErrors>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [requestId, setRequestId] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFieldErrors({})
    setFormError(null)
    setRequestId(null)
    setIsSubmitting(true)
    try {
      await auth.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      })
    } catch (error) {
      if (error instanceof ApiError) {
        const nextFieldErrors: ChangePasswordFieldErrors = {}
        for (const fieldError of error.fieldErrors) {
          if (
            fieldError.field === 'current_password' ||
            fieldError.field === 'new_password'
          ) {
            nextFieldErrors[fieldError.field] = fieldError.message
          }
        }
        setFieldErrors(nextFieldErrors)
        setFormError(error.message)
        setRequestId(error.requestId)
      } else {
        setFormError('密码修改失败，请重试')
      }
    } finally {
      setCurrentPassword('')
      setNewPassword('')
      setIsSubmitting(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      <TextField
        autoComplete="current-password"
        disabled={isSubmitting}
        error={fieldErrors.current_password}
        id="current-password"
        label="当前密码"
        name="current_password"
        onChange={(event) => setCurrentPassword(event.target.value)}
        required
        type="password"
        value={currentPassword}
      />

      <TextField
        autoComplete="new-password"
        disabled={isSubmitting}
        error={fieldErrors.new_password}
        id="new-password"
        label="新密码"
        name="new_password"
        onChange={(event) => setNewPassword(event.target.value)}
        required
        type="password"
        value={newPassword}
      />

      {formError ? (
        <div className={styles.formError} role="alert">
          {formError}
          {requestId ? (
            <span className={styles.requestId}>请求 ID：{requestId}</span>
          ) : null}
        </div>
      ) : null}

      <Button disabled={isSubmitting} type="submit">
        {isSubmitting ? '提交中…' : '修改密码'}
      </Button>
    </form>
  )
}
