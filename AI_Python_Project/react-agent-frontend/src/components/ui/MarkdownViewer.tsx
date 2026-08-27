import Markdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { credentialFreeHttpHref } from '@/api/safe-url'
import styles from '@/components/ui/MarkdownViewer.module.css'

interface MarkdownViewerProps {
  markdown: string
}

const markdownComponents: Components = {
  a({ children, href }) {
    const safeHref = credentialFreeHttpHref(href ?? null)
    return safeHref === null ? (
      <span>{children}</span>
    ) : (
      <a href={safeHref} rel="noopener noreferrer" target="_blank">
        {children}
      </a>
    )
  },
}

export function MarkdownViewer({ markdown }: MarkdownViewerProps) {
  return (
    <div className={styles.markdown}>
      <Markdown
        components={markdownComponents}
        disallowedElements={['img']}
        remarkPlugins={[remarkGfm]}
        skipHtml
      >
        {markdown}
      </Markdown>
    </div>
  )
}
