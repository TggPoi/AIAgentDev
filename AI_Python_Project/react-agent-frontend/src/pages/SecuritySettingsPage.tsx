import styles from '@/features/auth/AuthPage.module.css'
import { ChangePasswordForm } from '@/features/auth/ChangePasswordForm'
import { useAuth } from '@/features/auth/AuthProvider'

export function SecuritySettingsPage() {
  const auth = useAuth()
  const currentUser = auth.snapshot?.currentUser
  return (
    <section
      className={`${styles.card} ${styles.wideCard}`}
      aria-labelledby="security-title"
    >
      <p className={styles.eyebrow}>账号安全</p>
      <h2 className={styles.title} id="security-title">
        修改当前密码
      </h2>
      <p className={styles.identity}>
        当前用户：
        {currentUser?.displayName ?? currentUser?.username ?? '已认证用户'}
      </p>
      <ChangePasswordForm />
    </section>
  )
}
