import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { MarkdownViewer } from '@/components/ui/MarkdownViewer'


describe('MarkdownViewer', () => {
  it('renders GFM while dropping raw HTML, images and unsafe link targets', () => {
    render(
      <MarkdownViewer
        markdown={[
          '## 安全回答',
          '',
          '~~已修正内容~~',
          '',
          '| 项目 | 状态 |',
          '| --- | --- |',
          '| Contract | 通过 |',
          '',
          '<span data-testid="raw-html">raw-html</span>',
          '',
          '[安全外链](https://example.test/public)',
          '',
          '[带凭据链接](https://user:password@example.test/private)',
          '',
          '[脚本链接](javascript:alert(1))',
          '',
          '![远程图片](https://example.test/pixel.png)',
        ].join('\n')}
      />,
    )

    expect(screen.getByRole('heading', { name: '安全回答' })).toBeInTheDocument()
    expect(screen.getByText('已修正内容').tagName).toBe('DEL')
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.queryByTestId('raw-html')).not.toBeInTheDocument()
    expect(screen.queryByRole('img')).not.toBeInTheDocument()

    expect(screen.getByRole('link', { name: '安全外链' })).toHaveAttribute(
      'href',
      'https://example.test/public',
    )
    expect(screen.getByRole('link', { name: '安全外链' })).toHaveAttribute(
      'rel',
      'noopener noreferrer',
    )
    expect(screen.getByRole('link', { name: '安全外链' })).toHaveAttribute(
      'target',
      '_blank',
    )
    expect(screen.getByText('带凭据链接').closest('a')).toBeNull()
    expect(screen.getByText('脚本链接').closest('a')).toBeNull()
  })
})
