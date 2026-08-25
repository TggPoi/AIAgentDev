import { Component, type ErrorInfo, type PropsWithChildren } from 'react'

import { ErrorState } from '@/components/ui/PageState'
import styles from '@/features/auth/AuthPage.module.css'

interface AppErrorBoundaryState {
  failed: boolean
}

export class AppErrorBoundary extends Component<
  PropsWithChildren,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { failed: false }

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { failed: true }
  }

  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // Rendering failures are intentionally not serialized to logs here.
  }

  render() {
    if (this.state.failed) {
      return (
        <main className={styles.page}>
          <ErrorState
            code="UI_RENDER_ERROR"
            message="页面暂时无法显示，请刷新后重试。"
          />
        </main>
      )
    }
    return this.props.children
  }
}
