import { useState } from 'react'

import { Button } from '@/components/ui/Button'
import styles from '@/components/ui/PageState.module.css'

interface EmptyStateProps {
  description: string
  title: string
}

interface ErrorStateProps {
  code?: string | null
  message: string
  requestId?: string | null
  traceId?: string | null
}

export function EmptyState({ description, title }: EmptyStateProps) {
  return (
    <section className={styles.state} aria-labelledby="empty-state-title">
      <p className={styles.eyebrow}>准备就绪</p>
      <h2 className={styles.title} id="empty-state-title">
        {title}
      </h2>
      <p className={styles.description}>{description}</p>
    </section>
  )
}

export function ErrorState({
  code,
  message,
  requestId,
  traceId,
}: ErrorStateProps) {
  const [copied, setCopied] = useState(false)
  const copyRequestId = async () => {
    if (!requestId) return
    try {
      await navigator.clipboard.writeText(requestId)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }
  return (
    <section className={styles.state} aria-labelledby="error-state-title">
      <p className={styles.eyebrow}>请求未完成</p>
      <h2 className={styles.title} id="error-state-title">
        {message}
      </h2>
      {code ? <p className={styles.details}>错误代码：{code}</p> : null}
      {requestId ? (
        <>
          <span className={styles.requestId}>请求 ID：{requestId}</span>
          <Button
            onClick={() => void copyRequestId()}
            type="button"
            variant="secondary"
          >
            {copied ? '已复制' : '复制请求 ID'}
          </Button>
        </>
      ) : null}
      {traceId ? (
        <details className={styles.details}>
          <summary>排障信息</summary>
          <span className={styles.requestId}>Trace ID：{traceId}</span>
        </details>
      ) : null}
    </section>
  )
}

export function PageSkeleton() {
  return (
    <div className={styles.state} aria-label="页面加载中" role="status">
      <div className={styles.skeleton} />
      <div className={styles.skeleton} />
      <div className={styles.skeleton} />
    </div>
  )
}
