import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppErrorBoundary } from '@/app/AppErrorBoundary'
import { CapabilityGuard } from '@/app/route-guards'
import { PageSkeleton } from '@/components/ui/PageState'
import styles from '@/features/auth/AuthPage.module.css'
import { useAuth } from '@/features/auth/AuthProvider'
import { ApplicationShell } from '@/layouts/ApplicationShell'
import { LoginPage } from '@/pages/LoginPage'
import { PlaceholderPage } from '@/pages/PlaceholderPage'
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
        <PageSkeleton />
      </section>
    </main>
  )
}

const chatPage = (
  <PlaceholderPage
    description="在统一工作区中恢复历史会话并发起结构化 RAG / Agent 对话。"
    emptyDescription="选择历史会话或新建会话后，消息将在这里显示。"
    emptyTitle="准备开始对话"
    eyebrow="RAG / Agent"
    title="新对话"
  />
)

const taskPlanPage = (
  <PlaceholderPage
    description="查看需要确认、执行中或已经完成的结构化任务计划。"
    emptyDescription="任务计划数据将在业务模块接入后显示。"
    emptyTitle="暂无任务计划"
    eyebrow="Agent Operations"
    title="TaskPlan"
  />
)

const documentsPage = (
  <PlaceholderPage
    description="浏览当前身份可读取的公共、部门与精确授权知识文档。"
    emptyDescription="可读取的文档将在业务模块接入后显示。"
    emptyTitle="暂无知识文档"
    eyebrow="Knowledge"
    title="知识文档"
  />
)

const usersPage = (
  <PlaceholderPage
    description="管理当前授权范围内的用户账号与访问能力。"
    emptyDescription="用户目录将在业务模块接入后显示。"
    emptyTitle="暂无用户数据"
    eyebrow="Administration"
    title="用户管理"
  />
)

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
        <Route path="/chat" element={chatPage} />
        <Route path="/chat/:sessionId" element={chatPage} />
        <Route path="/tasks" element={taskPlanPage} />
        <Route path="/tasks/:taskPlanId" element={taskPlanPage} />
        <Route
          path="/documents"
          element={
            <CapabilityGuard capability="canReadDocuments">
              {documentsPage}
            </CapabilityGuard>
          }
        />
        <Route
          path="/documents/:docId"
          element={
            <CapabilityGuard capability="canReadDocuments">
              {documentsPage}
            </CapabilityGuard>
          }
        />
        <Route
          path="/admin/users"
          element={
            <CapabilityGuard capability="canManageUsers">
              {usersPage}
            </CapabilityGuard>
          }
        />
        <Route
          path="/admin/users/:userId"
          element={
            <CapabilityGuard capability="canManageUsers">
              {usersPage}
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
