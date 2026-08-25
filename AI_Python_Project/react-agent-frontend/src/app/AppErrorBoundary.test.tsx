import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AppErrorBoundary } from '@/app/AppErrorBoundary'

function BrokenPage(): never {
  throw new Error('internal-render-details-must-not-appear')
}

describe('AppErrorBoundary', () => {
  beforeEach(() => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
  })

  it('replaces rendering failures with a safe blocking error state', () => {
    render(
      <AppErrorBoundary>
        <BrokenPage />
      </AppErrorBoundary>,
    )

    expect(
      screen.getByRole('heading', {
        name: '页面暂时无法显示，请刷新后重试。',
      }),
    ).toBeInTheDocument()
    expect(screen.getByText('错误代码：UI_RENDER_ERROR')).toBeInTheDocument()
    expect(
      screen.queryByText('internal-render-details-must-not-appear'),
    ).not.toBeInTheDocument()
  })
})
