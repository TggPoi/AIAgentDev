import { type FormEvent, useState } from 'react'

import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/TextField'
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
      <TextField
        autoComplete="username"
        disabled={isSubmitting}
        error={fieldErrors.username_or_email}
        id="login-account"
        label="用户名或邮箱"
        name="username_or_email"
        onChange={(event) => setUsernameOrEmail(event.target.value)}
        required
        type="text"
        value={usernameOrEmail}
      />

      <TextField
        autoComplete="current-password"
        disabled={isSubmitting}
        error={fieldErrors.password}
        id="login-password"
        label="密码"
        name="password"
        onChange={(event) => setPassword(event.target.value)}
        required
        type="password"
        value={password}
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
        {isSubmitting ? '登录中…' : '登录'}
      </Button>
    </form>
  )
}
