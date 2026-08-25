import { type FormEvent, useState } from 'react'

import { ApiError } from '@/api/api-error'
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
      <div className={styles.field}>
        <label className={styles.label} htmlFor="current-password">
          当前密码
        </label>
        <input
          aria-describedby={
            fieldErrors.current_password ? 'current-password-error' : undefined
          }
          aria-invalid={fieldErrors.current_password ? 'true' : 'false'}
          autoComplete="current-password"
          className={styles.input}
          disabled={isSubmitting}
          id="current-password"
          name="current_password"
          onChange={(event) => setCurrentPassword(event.target.value)}
          required
          type="password"
          value={currentPassword}
        />
        {fieldErrors.current_password ? (
          <p className={styles.fieldError} id="current-password-error">
            {fieldErrors.current_password}
          </p>
        ) : null}
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor="new-password">
          新密码
        </label>
        <input
          aria-describedby={
            fieldErrors.new_password ? 'new-password-error' : undefined
          }
          aria-invalid={fieldErrors.new_password ? 'true' : 'false'}
          autoComplete="new-password"
          className={styles.input}
          disabled={isSubmitting}
          id="new-password"
          name="new_password"
          onChange={(event) => setNewPassword(event.target.value)}
          required
          type="password"
          value={newPassword}
        />
        {fieldErrors.new_password ? (
          <p className={styles.fieldError} id="new-password-error">
            {fieldErrors.new_password}
          </p>
        ) : null}
      </div>

      {formError ? (
        <div className={styles.formError} role="alert">
          {formError}
          {requestId ? (
            <span className={styles.requestId}>请求 ID：{requestId}</span>
          ) : null}
        </div>
      ) : null}

      <button className={styles.submit} disabled={isSubmitting} type="submit">
        {isSubmitting ? '提交中…' : '修改密码'}
      </button>
    </form>
  )
}
