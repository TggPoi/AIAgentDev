import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import styles from '@/features/auth/AuthPage.module.css'
import { useAuth } from '@/features/auth/AuthProvider'
import { LoginPage } from '@/pages/LoginPage'
import { SecuritySettingsPage } from '@/pages/SecuritySettingsPage'

function StartupScreen() {
  return (
    <main className={styles.page}>
      <section
        className={styles.card}
        aria-labelledby="startup-title"
        aria-live="polite"
      >
        <p className={styles.eyebrow}>React Agent Frontend</p>
        <h1 className={styles.title} id="startup-title">
          正在恢复身份
        </h1>
        <p className={styles.description}>正在安全轮换凭证并加载用户与能力快照。</p>
      </section>
    </main>
  )
}

function AuthenticatedHome() {
  const auth = useAuth()
  const currentUser = auth.snapshot?.currentUser
  return (
    <main className={styles.page}>
      <section className={styles.card} aria-labelledby="authenticated-title">
        <p className={styles.eyebrow}>认证生命周期已就绪</p>
        <h1 className={styles.title} id="authenticated-title">
          欢迎，{currentUser?.displayName ?? currentUser?.username}
        </h1>
        <p className={styles.description}>
          身份与能力已由 AuthProvider 原子发布。完整应用工作台将在下一 Slice 装配。
        </p>
        <div className={styles.actions}>
          <Link className={styles.link} to="/settings/security">
            账号安全
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
        {auth.status === 'refreshing' || auth.status === 'stale' ? (
          <p className={styles.status} role="status">
            {auth.status === 'refreshing'
              ? '正在刷新身份凭证…'
              : '身份快照暂时无法刷新，操作仍以后端授权为准。'}
          </p>
        ) : null}
      </section>
    </main>
  )
}

export function App() {
  const auth = useAuth()
  const location = useLocation()
  if (auth.status === 'bootstrapping') return <StartupScreen />
  if (auth.snapshot === null) {
    if (location.pathname === '/login') return <LoginPage />
    const returnTo = `${location.pathname}${location.search}${location.hash}`
    return <Navigate replace to={`/login?returnTo=${encodeURIComponent(returnTo)}`} />
  }
  return (
    <Routes>
      <Route path="/login" element={<Navigate replace to="/chat" />} />
      <Route path="/settings/security" element={<SecuritySettingsPage />} />
      <Route path="*" element={<AuthenticatedHome />} />
    </Routes>
  )
}
