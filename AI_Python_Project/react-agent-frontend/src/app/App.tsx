import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppErrorBoundary } from '@/app/AppErrorBoundary'
import { CapabilityGuard } from '@/app/route-guards'
import { PageSkeleton } from '@/components/ui/PageState'
import styles from '@/features/auth/AuthPage.module.css'
import { useAuth } from '@/features/auth/AuthProvider'
import { ApplicationShell } from '@/layouts/ApplicationShell'
import { LoginPage } from '@/pages/LoginPage'
import { PlaceholderPage } from '@/pages/PlaceholderPage'
import { ChatPage } from '@/pages/ChatPage'
import { DocumentPage } from '@/pages/DocumentPage'
import { SecuritySettingsPage } from '@/pages/SecuritySettingsPage'
import { TaskPlanPage } from '@/pages/TaskPlanPage'
import { UserManagementPage } from '@/pages/UserManagementPage'

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
        <PageSkeleton />
      </section>
    </main>
  )
}

const documentGrantsPage = (
  <PlaceholderPage
    description="管理非公开文档的精确跨部门只读授权。"
    emptyDescription="授权记录将在业务模块接入后显示。"
    emptyTitle="暂无授权记录"
    eyebrow="Administration"
    title="跨部门授权"
  />
)

function AppContent() {
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
      <Route element={<ApplicationShell />}>
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/chat/:sessionId" element={<ChatPage />} />
        <Route path="/tasks" element={<TaskPlanPage />} />
        <Route path="/tasks/:taskPlanId" element={<TaskPlanPage />} />
        <Route
          path="/documents"
          element={
            <CapabilityGuard capability="canReadDocuments">
              <DocumentPage />
            </CapabilityGuard>
          }
        />
        <Route
          path="/documents/:docId"
          element={
            <CapabilityGuard capability="canReadDocuments">
              <DocumentPage />
            </CapabilityGuard>
          }
        />
        <Route
          path="/admin/users"
          element={
            <CapabilityGuard capability="canManageUsers">
              <UserManagementPage />
            </CapabilityGuard>
          }
        />
        <Route
          path="/admin/users/:userId"
          element={
            <CapabilityGuard capability="canManageUsers">
              <UserManagementPage />
            </CapabilityGuard>
          }
        />
        <Route
          path="/admin/document-grants"
          element={
            <CapabilityGuard capability="canManageDocumentGrants">
              {documentGrantsPage}
            </CapabilityGuard>
          }
        />
        <Route path="/settings/security" element={<SecuritySettingsPage />} />
        <Route path="*" element={<Navigate replace to="/chat" />} />
      </Route>
    </Routes>
  )
}

export function App() {
  return (
    <AppErrorBoundary>
      <AppContent />
    </AppErrorBoundary>
  )
}
