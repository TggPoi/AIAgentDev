import { Link, useSearchParams } from 'react-router-dom'

import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { MarkdownViewer } from '@/components/ui/MarkdownViewer'
import { EmptyState, ErrorState, PageSkeleton } from '@/components/ui/PageState'
import { TextField } from '@/components/ui/TextField'
import type { KnowledgeDocumentApi } from '@/features/knowledge-documents/knowledge-document-api'
import {
  mergeKnowledgeDocumentPages,
  type KnowledgeDocumentAccessSource,
  type KnowledgeDocumentContent,
  type KnowledgeDocumentType,
} from '@/features/knowledge-documents/knowledge-document-models'
import {
  useKnowledgeDocumentContent,
  useKnowledgeDocumentDetail,
  useKnowledgeDocumentList,
} from '@/features/knowledge-documents/knowledge-document-queries'
import styles from '@/features/knowledge-documents/KnowledgeDocumentWorkspace.module.css'


interface KnowledgeDocumentWorkspaceProps {
  api: KnowledgeDocumentApi
  docId: string | null
  userBoundary: string
}

const documentTypeLabels: Record<KnowledgeDocumentType, string> = {
  markdown: 'Markdown',
  pdf: 'PDF',
  powerpoint: 'PowerPoint',
  spreadsheet: 'Spreadsheet',
  text: '纯文本',
  word: 'Word',
}

const accessSourceLabels: Record<KnowledgeDocumentAccessSource, string> = {
  admin: '管理员范围',
  department: '同部门',
  explicit_grant: '精确授权',
  original_acl: '原始权限',
  public: '公共区域',
}

const documentTypes = new Set<KnowledgeDocumentType>(
  Object.keys(documentTypeLabels) as KnowledgeDocumentType[],
)

function safeErrorState(error: unknown, message: string) {
  return (
    <ErrorState
      code={error instanceof ApiError ? error.code : undefined}
      message={message}
      requestId={error instanceof ApiError ? error.requestId : undefined}
    />
  )
}

function fieldError(error: unknown, field: string): string | undefined {
  if (!(error instanceof ApiError)) return undefined
  return error.fieldErrors.find((item) => item.field === field)?.message
}

function KnowledgeDocumentListView({
  api,
  userBoundary,
}: Omit<KnowledgeDocumentWorkspaceProps, 'docId'>) {
  const [searchParams, setSearchParams] = useSearchParams()
  const query = searchParams.get('query') || null
  const departmentCode = searchParams.get('department_code') || null
  const documentTypeValue = searchParams.get('document_type')
  const documentType =
    documentTypeValue !== null &&
    documentTypes.has(documentTypeValue as KnowledgeDocumentType)
      ? (documentTypeValue as KnowledgeDocumentType)
      : null
  const listQuery = useKnowledgeDocumentList(api, userBoundary, {
    departmentCode,
    documentType,
    query,
  })
  const items = mergeKnowledgeDocumentPages(listQuery.data?.pages ?? [])
  const queryError = fieldError(listQuery.error, 'query')
  const departmentError = fieldError(listQuery.error, 'department_code')
  const documentTypeError = fieldError(listQuery.error, 'document_type')
  const hasFieldError = Boolean(
    queryError || departmentError || documentTypeError,
  )

  const setFilter = (
    name: 'department_code' | 'document_type' | 'query',
    value: string,
  ) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(name, value)
    else next.delete(name)
    setSearchParams(next, { replace: true })
  }

  return (
    <section aria-labelledby="knowledge-document-list-title" className={styles.page}>
      <header className={styles.header}>
        <p className={styles.eyebrow}>Knowledge Library</p>
        <h2 id="knowledge-document-list-title">知识文档</h2>
        <p>浏览当前身份可读取的公共区域、同部门和精确授权文档。</p>
      </header>
      <div className={styles.filters}>
        <TextField
          error={queryError}
          id="knowledge-document-query"
          label="关键词"
          onChange={(event) => setFilter('query', event.currentTarget.value)}
          value={query ?? ''}
        />
        <TextField
          error={departmentError}
          id="knowledge-document-department"
          label="部门"
          onChange={(event) =>
            setFilter('department_code', event.currentTarget.value)
          }
          value={departmentCode ?? ''}
        />
        <label className={styles.selectField}>
          文档格式
          <select
            aria-invalid={documentTypeError ? 'true' : 'false'}
            onChange={(event) =>
              setFilter('document_type', event.currentTarget.value)
            }
            value={documentType ?? ''}
          >
            <option value="">全部格式</option>
            {Object.entries(documentTypeLabels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
          {documentTypeError ? (
            <span className={styles.fieldError}>{documentTypeError}</span>
          ) : null}
        </label>
      </div>
      {listQuery.isPending ? <PageSkeleton /> : null}
      {listQuery.isError && !hasFieldError
        ? safeErrorState(listQuery.error, '知识文档列表加载失败')
        : null}
      {listQuery.isSuccess && items.length === 0 ? (
        <EmptyState
          description="当前筛选条件下没有可读取的文档。"
          title="暂无知识文档"
        />
      ) : null}
      {items.length > 0 ? (
        <ol aria-label="知识文档列表" className={styles.list}>
          {items.map((item) => (
            <li key={item.docId}>
              <Link
                className={styles.cardLink}
                to={`/documents/${encodeURIComponent(item.docId)}`}
              >
                <span className={styles.cardHeader}>
                  <strong>{item.title}</strong>
                  <span className={styles.badge}>
                    {accessSourceLabels[item.accessSource]}
                  </span>
                </span>
                <span>来源部门：{item.departmentCode}</span>
                <span>
                  {documentTypeLabels[item.documentType]} · 更新于 {item.updatedAt}
                </span>
              </Link>
            </li>
          ))}
        </ol>
      ) : null}
      {listQuery.hasNextPage ? (
        <Button
          disabled={listQuery.isFetchingNextPage}
          onClick={() => void listQuery.fetchNextPage()}
          type="button"
          variant="secondary"
        >
          {listQuery.isFetchingNextPage ? '正在加载…' : '加载更多文档'}
        </Button>
      ) : null}
    </section>
  )
}

function ContentWarnings({ content }: { content: KnowledgeDocumentContent }) {
  const hasUnknownWarning = content.warnings.some(
    (warning) =>
      warning !== 'preview_truncated' &&
      warning !== 'pdf_text_content_unavailable',
  )
  return content.truncated || content.warnings.length > 0 ? (
    <aside aria-label="内容预览提示" className={styles.notice}>
      {content.truncated ? <p>预览内容已被截断。</p> : null}
      {content.warnings.includes('pdf_text_content_unavailable') ? (
        <p>未提取到可显示的 PDF 文本。</p>
      ) : null}
      {hasUnknownWarning ? <p>内容预览包含非阻断提示。</p> : null}
    </aside>
  ) : null
}

function DocumentContentView({ content }: { content: KnowledgeDocumentContent }) {
  return (
    <>
      {content.renderMode === 'markdown' ? (
        <MarkdownViewer markdown={content.content} />
      ) : (
        <>
          <p className={styles.renderNotice}>
            {content.renderMode === 'plain_text'
              ? '纯文本按原始换行显示。'
              : '提取文本不保留原始 PDF 或 Office 排版。'}
          </p>
          <pre className={styles.plainText}>{content.content}</pre>
        </>
      )}
      <ContentWarnings content={content} />
    </>
  )
}

function KnowledgeDocumentDetailView({
  api,
  docId,
  userBoundary,
}: KnowledgeDocumentWorkspaceProps & { docId: string }) {
  const detailQuery = useKnowledgeDocumentDetail(api, userBoundary, docId)
  const contentQuery = useKnowledgeDocumentContent(
    api,
    userBoundary,
    detailQuery.isSuccess ? docId : null,
  )

  if (detailQuery.isPending) return <PageSkeleton />
  if (detailQuery.isError) {
    return (
      <div className={styles.page}>
        <Link to="/documents">返回知识文档列表</Link>
        {detailQuery.error instanceof ApiError &&
        detailQuery.error.statusKind === 'not_found'
          ? safeErrorState(detailQuery.error, '文档不可用')
          : safeErrorState(detailQuery.error, '知识文档详情加载失败')}
      </div>
    )
  }

  const detail = detailQuery.data
  return (
    <article aria-labelledby="knowledge-document-detail-title" className={styles.page}>
      <Link to="/documents">← 返回知识文档列表</Link>
      <header className={styles.detailHeader}>
        <p className={styles.eyebrow}>{accessSourceLabels[detail.accessSource]}</p>
        <h2 id="knowledge-document-detail-title">{detail.title}</h2>
        <p>
          来源部门：{detail.departmentCode} · {documentTypeLabels[detail.documentType]}
        </p>
      </header>
      <dl className={styles.facts}>
        <div>
          <dt>文件名</dt>
          <dd>{detail.fileName}</dd>
        </div>
        <div>
          <dt>来源项目</dt>
          <dd>{detail.sourceProjectPath}</dd>
        </div>
        <div>
          <dt>更新时间</dt>
          <dd>{detail.updatedAt}</dd>
        </div>
      </dl>
      <section aria-labelledby="knowledge-document-content-title" className={styles.panel}>
        <h3 id="knowledge-document-content-title">内容预览</h3>
        {contentQuery.isPending ? <PageSkeleton /> : null}
        {contentQuery.isError
          ? safeErrorState(contentQuery.error, '文档内容不可用')
          : null}
        {contentQuery.isSuccess ? (
          <DocumentContentView content={contentQuery.data} />
        ) : null}
      </section>
    </article>
  )
}

export function KnowledgeDocumentWorkspace({
  api,
  docId,
  userBoundary,
}: KnowledgeDocumentWorkspaceProps) {
  return docId === null ? (
    <KnowledgeDocumentListView api={api} userBoundary={userBoundary} />
  ) : (
    <KnowledgeDocumentDetailView
      api={api}
      docId={docId}
      userBoundary={userBoundary}
    />
  )
}
