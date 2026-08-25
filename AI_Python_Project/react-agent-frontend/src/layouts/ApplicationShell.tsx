import { useCallback, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'

import { Button } from '@/components/ui/Button'
import { Drawer } from '@/components/ui/Drawer'
import { useAuth } from '@/features/auth/AuthProvider'
import type { Capabilities } from '@/features/auth/auth-models'
import styles from '@/layouts/ApplicationShell.module.css'

interface NavigationItem {
  capability?: keyof Capabilities
  end?: boolean
  label: string
  to: string
}

const navigationItems: NavigationItem[] = [
  { end: false, label: '对话', to: '/chat' },
  { end: false, label: 'TaskPlan', to: '/tasks' },
  { capability: 'canReadDocuments', label: '知识文档', to: '/documents' },
  { capability: 'canManageUsers', label: '用户管理', to: '/admin/users' },
  {
    capability: 'canManageDocumentGrants',
    label: '跨部门授权',
    to: '/admin/document-grants',
  },
  { label: '账号安全', to: '/settings/security' },
]

function pageTitle(pathname: string): string {
  if (pathname.startsWith('/tasks')) return 'TaskPlan'
  if (pathname.startsWith('/documents')) return '知识文档'
  if (pathname.startsWith('/admin/users')) return '用户管理'
  if (pathname.startsWith('/admin/document-grants')) return '跨部门授权'
  if (pathname.startsWith('/settings/security')) return '账号安全'
  return '对话'
}

function ShellNavigation({ onNavigate }: { onNavigate?: () => void }) {
  const auth = useAuth()
  const capabilities = auth.snapshot?.capabilities
  return (
    <nav aria-label="主导航" className={styles.navigation}>
      {navigationItems.map((item) => {
        if (item.capability && !capabilities?.[item.capability]) return null
        return (
          <NavLink
            className={({ isActive }) =>
              `${styles.navLink} ${isActive ? styles.activeLink : ''}`
            }
            end={item.end}
            key={item.to}
            onClick={onNavigate}
            to={item.to}
          >
            {item.label}
          </NavLink>
        )
      })}
    </nav>
  )
}

export function ApplicationShell() {
  const auth = useAuth()
  const location = useLocation()
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const currentUser = auth.snapshot?.currentUser
  const notice =
    typeof location.state === 'object' &&
    location.state !== null &&
    'shellNotice' in location.state &&
    typeof location.state.shellNotice === 'string'
      ? location.state.shellNotice
      : null

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false)
    menuButtonRef.current?.focus()
  }, [])

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <p className={styles.brand}>React Agent</p>
        <ShellNavigation />
      </aside>

      <div className={styles.contentColumn}>
        <header className={styles.topbar}>
          <Button
            ref={menuButtonRef}
            aria-expanded={drawerOpen}
            aria-label="打开导航"
            className={styles.menuButton}
            iconOnly
            onClick={() => setDrawerOpen(true)}
            type="button"
            variant="ghost"
          >
            ☰
          </Button>
          <div className={styles.titleGroup}>
            <h1 className={styles.pageTitle}>{pageTitle(location.pathname)}</h1>
          </div>
          <div className={styles.accountArea}>
            <span className={styles.department}>
              {currentUser?.primaryDepartmentCode ?? '无主部门'}
            </span>
            <details className={styles.userMenu}>
              <summary
                aria-label={`用户菜单：${currentUser?.displayName ?? currentUser?.username}`}
              >
                {currentUser?.displayName ?? currentUser?.username}
              </summary>
              <div className={styles.userMenuPanel}>
                <Link to="/settings/security">打开账号安全设置</Link>
                <Button
                  disabled={auth.status === 'loggingOut'}
                  onClick={() => void auth.logout().catch(() => undefined)}
                  type="button"
                  variant="ghost"
                >
                  {auth.status === 'loggingOut' ? '正在退出…' : '退出登录'}
                </Button>
              </div>
            </details>
          </div>
        </header>

        <Drawer label="主导航" onClose={closeDrawer} open={drawerOpen}>
          <ShellNavigation onNavigate={() => setDrawerOpen(false)} />
        </Drawer>

        <main className={styles.content}>
          {notice ? (
            <p aria-label={notice} className={styles.notice} role="status">
              {notice}
            </p>
          ) : null}
          <Outlet />
        </main>
      </div>
    </div>
  )
}
