import { type ReactNode, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { ApiError } from '@/api/api-error'
import { credentialFreeHttpHref } from '@/api/safe-url'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { EmptyState, ErrorState, PageSkeleton } from '@/components/ui/PageState'
import { MarkdownViewer } from '@/components/ui/MarkdownViewer'
import { TextField } from '@/components/ui/TextField'
import type { ConversationApi } from '@/features/conversations/conversation-api'
import {
  mergeConversationPages,
  mergeMessagePages,
  type ConversationSummary,
  type HistoricalSource,
} from '@/features/conversations/conversation-models'
import {
  useConversationList,
  useConversationMessages,
  useCreateConversation,
  useDeleteConversation,
  useRenameConversation,
} from '@/features/conversations/conversation-queries'
import styles from '@/features/conversations/ConversationsWorkspace.module.css'


interface ConversationsWorkspaceProps {
  api: ConversationApi
  chatPanel?: ReactNode
  sessionId: string | null
  userBoundary: string
}

type OpenDialog = 'create' | 'delete' | 'rename' | null

function titleFieldError(error: unknown): string | undefined {
  if (!(error instanceof ApiError)) return undefined
  return error.fieldErrors.find((item) => item.field === 'title')?.message
}

function MutationErrorState({ error, message }: { error: unknown; message: string }) {
  return (
    <ErrorState
      code={error instanceof ApiError ? error.code : undefined}
      message={message}
      requestId={error instanceof ApiError ? error.requestId : undefined}
    />
  )
}

function SourceReference({ source }: { source: HistoricalSource }) {
  const label = source.title ?? source.contentPreview
  if (source.sourceType === 'knowledge_document' && source.docId) {
    return <Link to={`/documents/${encodeURIComponent(source.docId)}`}>{label}</Link>
  }
  const href =
    source.sourceType === 'web' ? credentialFreeHttpHref(source.href) : null
  if (href) {
    return (
      <a href={href} rel="noopener noreferrer" target="_blank">
        {label}
      </a>
    )
  }
  return <>{label}</>
}

function ConversationList({
  conversations,
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
  selectedSessionId,
}: {
  conversations: ConversationSummary[]
  hasNextPage: boolean
  isFetchingNextPage: boolean
  onLoadMore: () => void
  selectedSessionId: string | null
}) {
  return (
    <div aria-label="会话列表" className={styles.listRegion} role="region">
      {conversations.length === 0 ? (
        <p className={styles.muted}>暂无历史会话</p>
      ) : (
        <ol className={styles.conversationList}>
          {conversations.map((conversation) => (
            <li key={conversation.sessionId}>
              <Link
                aria-current={
                  conversation.sessionId === selectedSessionId ? 'page' : undefined
                }
                className={styles.conversationLink}
                to={`/chat/${encodeURIComponent(conversation.sessionId)}`}
              >
                <strong>{conversation.title}</strong>
                <span>{conversation.lastMessagePreview ?? '暂无消息'}</span>
              </Link>
            </li>
          ))}
        </ol>
      )}
      {hasNextPage ? (
        <Button
          disabled={isFetchingNextPage}
          onClick={onLoadMore}
          type="button"
          variant="secondary"
        >
          {isFetchingNextPage ? '正在加载…' : '加载更多会话'}
        </Button>
      ) : null}
    </div>
  )
}

export function ConversationsWorkspace({
  api,
  chatPanel,
  sessionId,
  userBoundary,
}: ConversationsWorkspaceProps) {
  const navigate = useNavigate()
  const listQuery = useConversationList(api, userBoundary)
  const messagesQuery = useConversationMessages(api, userBoundary, sessionId)
  const createMutation = useCreateConversation(api, userBoundary)
  const renameMutation = useRenameConversation(api, userBoundary)
  const deleteMutation = useDeleteConversation(api, userBoundary)
  const [openDialog, setOpenDialog] = useState<OpenDialog>(null)
  const [titleDraft, setTitleDraft] = useState('')

  const conversations = mergeConversationPages(listQuery.data?.pages ?? [])
  const messages = mergeMessagePages(messagesQuery.data?.pages ?? [])
  const selectedConversation =
    conversations.find((item) => item.sessionId === sessionId) ?? null
  const createTitleError = titleFieldError(createMutation.error)
  const renameTitleError = titleFieldError(renameMutation.error)

  const closeDialog = () => {
    setOpenDialog(null)
    setTitleDraft('')
    createMutation.reset()
    renameMutation.reset()
    deleteMutation.reset()
  }

  const openCreate = () => {
    closeDialog()
    setOpenDialog('create')
  }
  const openRename = () => {
    closeDialog()
    setTitleDraft(selectedConversation?.title ?? '')
    setOpenDialog('rename')
  }
  const openDelete = () => {
    closeDialog()
    setOpenDialog('delete')
  }

  const submitCreate = async () => {
    try {
      const normalized = titleDraft.trim()
      const created = await createMutation.mutateAsync(normalized || undefined)
      closeDialog()
      navigate(`/chat/${encodeURIComponent(created.sessionId)}`)
    } catch {
      // Mutation state owns the safe error projection.
    }
  }

  const submitRename = async () => {
    if (sessionId === null) return
    try {
      await renameMutation.mutateAsync({ sessionId, title: titleDraft })
      closeDialog()
    } catch {
      // Mutation state owns the safe error projection.
    }
  }

  const submitDelete = async () => {
    if (sessionId === null) return
    try {
      await deleteMutation.mutateAsync(sessionId)
      closeDialog()
      navigate('/chat')
    } catch {
      // Mutation state owns the safe error projection.
    }
  }

  return (
    <section aria-label="会话工作区" className={styles.workspace}>
      <aside className={styles.catalog}>
        <div className={styles.catalogHeader}>
          <div>
            <p className={styles.eyebrow}>Conversations</p>
            <h2>历史会话</h2>
          </div>
          <Button onClick={openCreate} type="button">
            新建会话
          </Button>
        </div>
        {listQuery.isPending ? <PageSkeleton /> : null}
        {listQuery.isError ? (
          <ErrorState
            code={listQuery.error instanceof ApiError ? listQuery.error.code : undefined}
            message="会话列表加载失败"
            requestId={
              listQuery.error instanceof ApiError ? listQuery.error.requestId : undefined
            }
          />
        ) : null}
        {listQuery.isSuccess ? (
          <ConversationList
            conversations={conversations}
            hasNextPage={listQuery.hasNextPage}
            isFetchingNextPage={listQuery.isFetchingNextPage}
            onLoadMore={() => void listQuery.fetchNextPage()}
            selectedSessionId={sessionId}
          />
        ) : null}
        {listQuery.isFetching && !listQuery.isPending ? (
          <p className={styles.refreshing} role="status">
            正在刷新会话
          </p>
        ) : null}
      </aside>

      <div className={styles.history}>
        <header className={styles.historyHeader}>
          <div>
            <p className={styles.eyebrow}>RAG / Agent History</p>
            <h2>{selectedConversation?.title ?? (sessionId ? '历史会话' : '新对话')}</h2>
          </div>
          {sessionId && selectedConversation ? (
            <div className={styles.actions}>
              <Button onClick={openRename} type="button" variant="secondary">
                重命名当前会话
              </Button>
              <Button onClick={openDelete} type="button" variant="ghost">
                删除当前会话
              </Button>
            </div>
          ) : null}
        </header>

        {sessionId === null ? (
          <EmptyState
            description="选择历史会话或新建会话后，服务端持久化消息将在这里显示。"
            title="准备开始对话"
          />
        ) : null}
        {sessionId !== null && messagesQuery.isPending ? <PageSkeleton /> : null}
        {sessionId !== null && messagesQuery.isError ? (
          <ErrorState
            code={
              messagesQuery.error instanceof ApiError
                ? messagesQuery.error.code
                : undefined
            }
            message={
              messagesQuery.error instanceof ApiError &&
              messagesQuery.error.statusKind === 'not_found'
                ? '会话不可用'
                : '历史消息加载失败'
            }
            requestId={
              messagesQuery.error instanceof ApiError
                ? messagesQuery.error.requestId
                : undefined
            }
          />
        ) : null}
        {sessionId !== null && messagesQuery.isSuccess && messages.length === 0 ? (
          <EmptyState description="这个会话还没有持久化消息。" title="暂无消息" />
        ) : null}
        {messages.length > 0 ? (
          <ol aria-label="历史消息" className={styles.messageList}>
            {messages.map((item) => (
              <li className={styles.message} key={item.messageId}>
                <p className={styles.messageRole}>
                  {item.role === 'user' ? '你' : 'Agent'}
                </p>
                {item.role === 'assistant' ? (
                  <div className={styles.messageContent}>
                    <MarkdownViewer markdown={item.content} />
                  </div>
                ) : (
                  <p className={styles.messageContent}>{item.content}</p>
                )}
                {item.sources.length > 0 ? (
                  <ul aria-label="消息来源" className={styles.sources}>
                    {item.sources.map((source) => (
                      <li key={source.id}>
                        <SourceReference source={source} />
                      </li>
                    ))}
                  </ul>
                ) : null}
                {item.agentTaskPlanId ? (
                  <Link to={`/tasks/${encodeURIComponent(item.agentTaskPlanId)}`}>
                    查看 TaskPlan {item.agentTaskPlanId}
                  </Link>
                ) : null}
                <span className={styles.terminal}>终态：{item.terminalStatus}</span>
              </li>
            ))}
          </ol>
        ) : null}
        {messagesQuery.hasNextPage ? (
          <Button
            disabled={messagesQuery.isFetchingNextPage}
            onClick={() => void messagesQuery.fetchNextPage()}
            type="button"
            variant="secondary"
          >
            {messagesQuery.isFetchingNextPage ? '正在加载…' : '加载更多消息'}
          </Button>
        ) : null}
        {chatPanel}
      </div>

      <Dialog label="新建会话" onClose={closeDialog} open={openDialog === 'create'}>
        <form
          className={styles.dialogForm}
          onSubmit={(event) => {
            event.preventDefault()
            void submitCreate()
          }}
        >
          <TextField
            error={createTitleError}
            id="create-conversation-title"
            label="会话标题（可选）"
            maxLength={160}
            onChange={(event) => setTitleDraft(event.target.value)}
            value={titleDraft}
          />
          {createMutation.isError && !createTitleError ? (
            <MutationErrorState
              error={createMutation.error}
              message="创建会话失败"
            />
          ) : null}
          <Button disabled={createMutation.isPending} type="submit">
            {createMutation.isPending ? '正在创建…' : '创建'}
          </Button>
        </form>
      </Dialog>

      <Dialog label="重命名会话" onClose={closeDialog} open={openDialog === 'rename'}>
        <form
          className={styles.dialogForm}
          onSubmit={(event) => {
            event.preventDefault()
            void submitRename()
          }}
        >
          <TextField
            error={renameTitleError}
            id="rename-conversation-title"
            label="新标题"
            maxLength={160}
            onChange={(event) => setTitleDraft(event.target.value)}
            required
            value={titleDraft}
          />
          {renameMutation.isError && !renameTitleError ? (
            <MutationErrorState
              error={renameMutation.error}
              message="重命名会话失败"
            />
          ) : null}
          <Button disabled={renameMutation.isPending} type="submit">
            {renameMutation.isPending ? '正在保存…' : '保存'}
          </Button>
        </form>
      </Dialog>

      <Dialog label="删除会话" onClose={closeDialog} open={openDialog === 'delete'}>
        <div className={styles.dialogForm}>
          <p>删除后会话、消息与近期上下文都不可恢复。确认继续吗？</p>
          {deleteMutation.isError ? (
            <ErrorState
              code={
                deleteMutation.error instanceof ApiError
                  ? deleteMutation.error.code
                  : undefined
              }
              message="删除会话失败"
              requestId={
                deleteMutation.error instanceof ApiError
                  ? deleteMutation.error.requestId
                  : undefined
              }
            />
          ) : null}
          <Button disabled={deleteMutation.isPending} onClick={() => void submitDelete()}>
            {deleteMutation.isPending ? '正在删除…' : '确认删除'}
          </Button>
        </div>
      </Dialog>
    </section>
  )
}
