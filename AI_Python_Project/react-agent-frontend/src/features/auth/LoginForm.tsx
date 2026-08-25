import { type FormEvent, useState } from 'react'

import { ApiError } from '@/api/api-error'
import styles from '@/features/auth/AuthForm.module.css'
import { useAuth } from '@/features/auth/AuthProvider'


interface LoginFormProps {
  onAuthenticated?: () => void
}

interface LoginFieldErrors {
  password?: string
  username_or_email?: string
}

export function LoginForm({ onAuthenticated }: LoginFormProps) {
  const auth = useAuth()
  const [usernameOrEmail, setUsernameOrEmail] = useState('')
  const [password, setPassword] = useState('')
  const [fieldErrors, setFieldErrors] = useState<LoginFieldErrors>({})
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
      await auth.login({
        username_or_email: usernameOrEmail,
        password,
      })
      setPassword('')
      onAuthenticated?.()
    } catch (error) {
      setPassword('')
      if (error instanceof ApiError) {
        const nextFieldErrors: LoginFieldErrors = {}
        for (const fieldError of error.fieldErrors) {
          if (
            fieldError.field === 'username_or_email' ||
            fieldError.field === 'password'
          ) {
            nextFieldErrors[fieldError.field] = fieldError.message
          }
        }
        setFieldErrors(nextFieldErrors)
        setFormError(error.message)
        setRequestId(error.requestId)
      } else {
        setFormError('登录失败，请重试')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit} noValidate>
      <div className={styles.field}>
        <label className={styles.label} htmlFor="login-account">
          用户名或邮箱
        </label>
        <input
          aria-describedby={
            fieldErrors.username_or_email ? 'login-account-error' : undefined
          }
          aria-invalid={fieldErrors.username_or_email ? 'true' : 'false'}
          autoComplete="username"
          className={styles.input}
          disabled={isSubmitting}
          id="login-account"
          name="username_or_email"
          onChange={(event) => setUsernameOrEmail(event.target.value)}
          required
          type="text"
          value={usernameOrEmail}
        />
        {fieldErrors.username_or_email ? (
          <p className={styles.fieldError} id="login-account-error">
            {fieldErrors.username_or_email}
          </p>
        ) : null}
      </div>

      <div className={styles.field}>
        <label className={styles.label} htmlFor="login-password">
          密码
        </label>
        <input
          aria-describedby={fieldErrors.password ? 'login-password-error' : undefined}
          aria-invalid={fieldErrors.password ? 'true' : 'false'}
          autoComplete="current-password"
          className={styles.input}
          disabled={isSubmitting}
          id="login-password"
          name="password"
          onChange={(event) => setPassword(event.target.value)}
          required
          type="password"
          value={password}
        />
        {fieldErrors.password ? (
          <p className={styles.fieldError} id="login-password-error">
            {fieldErrors.password}
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
        {isSubmitting ? '登录中…' : '登录'}
      </button>
    </form>
  )
}
