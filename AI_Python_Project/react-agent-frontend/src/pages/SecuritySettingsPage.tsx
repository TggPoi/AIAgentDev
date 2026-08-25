import { Link } from 'react-router-dom'

import styles from '@/features/auth/AuthPage.module.css'
import { ChangePasswordForm } from '@/features/auth/ChangePasswordForm'
import { useAuth } from '@/features/auth/AuthProvider'

export function SecuritySettingsPage() {
  const auth = useAuth()
  const currentUser = auth.snapshot?.currentUser
  return (
    <main className={styles.page}>
      <section
        className={`${styles.card} ${styles.wideCard}`}
        aria-labelledby="security-title"
      >
        <p className={styles.eyebrow}>账号安全</p>
        <h1 className={styles.title} id="security-title">
          修改当前密码
        </h1>
        <p className={styles.identity}>
          当前用户：
          {currentUser?.displayName ?? currentUser?.username ?? '已认证用户'}
        </p>
        <ChangePasswordForm />
        <div className={styles.actions}>
          <Link className={styles.link} to="/chat">
            返回工作台
          </Link>
          <button
            className={styles.secondaryButton}
            disabled={auth.status === 'loggingOut'}
            onClick={() => void auth.logout().catch(() => undefined)}
            type="button"
          >
            {auth.status === 'loggingOut' ? '正在退出…' : '退出登录'}
          </button>
        </div>
      </section>
    </main>
  )
}
