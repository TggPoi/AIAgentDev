import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { EmptyState, ErrorState, PageSkeleton } from '@/components/ui/PageState'

describe('shared page states', () => {
  it('renders a non-blocking empty state and an accessible loading skeleton', () => {
    const { rerender } = render(
      <EmptyState description="没有可显示的记录" title="暂无记录" />,
    )
    expect(screen.getByRole('heading', { name: '暂无记录' })).toBeInTheDocument()

    rerender(<PageSkeleton />)
    expect(screen.getByRole('status', { name: '页面加载中' })).toBeInTheDocument()
  })

  it('shows only safe troubleshooting fields and copies the request ID', async () => {
    const user = userEvent.setup()
    render(
      <ErrorState
        code="FORBIDDEN"
        message="当前操作没有权限"
        requestId="request-public-1"
        traceId="trace-public-1"
      />,
    )

    expect(screen.getByText('错误代码：FORBIDDEN')).toBeInTheDocument()
    expect(screen.getByText('请求 ID：request-public-1')).toBeInTheDocument()
    expect(screen.getByText('排障信息')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '复制请求 ID' }))
    expect(screen.getByRole('button', { name: '已复制' })).toBeInTheDocument()
  })
})
