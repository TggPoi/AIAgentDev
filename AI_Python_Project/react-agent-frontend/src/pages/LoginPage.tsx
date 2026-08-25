import { useNavigate, useSearchParams } from 'react-router-dom'

import styles from '@/features/auth/AuthPage.module.css'
import { LoginForm } from '@/features/auth/LoginForm'
import { validateLoginReturnPath } from '@/features/auth/return-path'

export function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const handleAuthenticated = () => {
    navigate(
      validateLoginReturnPath(searchParams.get('returnTo'), window.location.origin),
      { replace: true },
    )
  }
  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="login-title">
        <p className={styles.eyebrow}>React Agent Frontend</p>
        <h1 className={styles.title} id="login-title">
          登录工作台
        </h1>
        <p className={styles.description}>
          使用管理员或部门主管已创建的账号继续。
        </p>
        <LoginForm onAuthenticated={handleAuthenticated} />
      </section>
    </main>
  )
}
