import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { App } from '@/app/App'
import { AppProviders } from '@/app/AppProviders'

describe('App environment check', () => {
  it('renders the development environment readiness message', () => {
    render(
      <AppProviders>
        <App />
      </AppProviders>,
    )

    expect(
      screen.getByRole('heading', { name: '开发环境已就绪' }),
    ).toBeInTheDocument()
    expect(screen.getByText(/尚未开始任何业务功能开发/)).toBeInTheDocument()
  })
})
