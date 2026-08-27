import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useReducer, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '@/api/api-error'
import { credentialFreeHttpHref } from '@/api/safe-url'
import {
  getTerminalKind,
  type PublicSource,
} from '@/api/sse/public-events'
import { Button } from '@/components/ui/Button'
import { MarkdownViewer } from '@/components/ui/MarkdownViewer'
import { TextField } from '@/components/ui/TextField'
import type { ChatApi } from '@/features/chat/chat-api'
import {
  buildChatRequest,
  chatReducer,
  createInitialChatState,
  queryErrorMessage,
} from '@/features/chat/chat-model'
import {
  clearChatWebPreferences,
  loadChatWebPreferences,
  saveChatWebPreferences,
} from '@/features/chat/chat-preferences'
import { conversationKeys } from '@/features/conversations/conversation-queries'
import styles from '@/features/chat/ChatWorkspace.module.css'


interface ChatWorkspaceProps {
  api: ChatApi
  canUseWebSearch: boolean
  registerPrivateActivity(controller: AbortController): () => void
  sessionId: string | null
  userBoundary: string
}

const activeStatuses = new Set(['connecting', 'streaming'])

function SourceReference({ source }: { source: PublicSource }) {
  const label = source.title ?? source.contentPreview
  if (source.sourceType === 'knowledge_document' && source.docId !== null) {
    return (
      <Link to={`/documents/${encodeURIComponent(source.docId)}`}>{label}</Link>
    )
  }
  const href =
    source.sourceType === 'web' ? credentialFreeHttpHref(source.href) : null
  if (href !== null) {
    return (
      <a href={href} rel="noopener noreferrer" target="_blank">
        {label}
      </a>
    )
  }
  return <>{label}</>
}

export function ChatWorkspace({
  api,
  canUseWebSearch,
  registerPrivateActivity,
  sessionId,
  userBoundary,
}: ChatWorkspaceProps) {
  const queryClient = useQueryClient()
  const [state, dispatch] = useReducer(chatReducer, undefined, createInitialChatState)
  const [draft, setDraft] = useState('')
  const [queryError, setQueryError] = useState<string | undefined>()
  const [webPreferences, setWebPreferences] = useState(() =>
    loadChatWebPreferences(window.sessionStorage, userBoundary),
  )
  const activeController = useRef<AbortController | null>(null)
  const activeRequestId = useRef<string | null>(null)
  const isActive = activeStatuses.has(state.status)

  useEffect(() => {
    return () => {
      activeController.current?.abort()
    }
  }, [])

  useEffect(() => {
    const privacyBoundary = new AbortController()
    const clearPreferences = () => {
      clearChatWebPreferences(window.sessionStorage, userBoundary)
    }
    privacyBoundary.signal.addEventListener('abort', clearPreferences, {
      once: true,
    })
    const unregister = registerPrivateActivity(privacyBoundary)
    return () => {
      unregister()
      privacyBoundary.signal.removeEventListener('abort', clearPreferences)
    }
  }, [registerPrivateActivity, userBoundary])

  const updateWebPreferences = (
    allowDirectWeb: boolean,
    allowWebFallback: boolean,
  ) => {
    const next = {
      allowDirectWeb,
      allowWebFallback: allowDirectWeb && allowWebFallback,
    }
    setWebPreferences(next)
    saveChatWebPreferences(window.sessionStorage, userBoundary, next)
  }

  const reconcileHistory = async (activeSessionId: string) => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: conversationKeys.messageRoot(userBoundary, activeSessionId),
      }),
      queryClient.invalidateQueries({
        queryKey: conversationKeys.listRoot(userBoundary),
      }),
    ])
  }

  const submit = async () => {
    const query = draft.trim()
    if (sessionId === null || query.length === 0 || isActive) return

    const requestId = crypto.randomUUID()
    const controller = new AbortController()
    activeController.current = controller
    activeRequestId.current = requestId
    const unregister = registerPrivateActivity(controller)
    setQueryError(undefined)
    dispatch({ query, requestId, type: 'start' })

    try {
      let terminalReceived = false
      const request = buildChatRequest({
        ...webPreferences,
        canUseWebSearch,
        query,
        sessionId,
      })
      for await (const streamEvent of api.stream(
        request,
        requestId,
        controller.signal,
      )) {
        dispatch({ event: streamEvent, type: 'event' })
        if (getTerminalKind(streamEvent) !== null) {
          terminalReceived = true
          break
        }
      }
      if (!terminalReceived) {
        dispatch({
          message: '连接提前结束，已重新读取服务端历史。',
          requestId,
          type: 'interrupt',
        })
      }
    } catch (error) {
      if (controller.signal.aborted) {
        dispatch({ requestId, type: 'cancel' })
      } else {
        setQueryError(queryErrorMessage(error) ?? undefined)
        dispatch({
          message:
            error instanceof ApiError
              ? '对话请求未完成，请检查输入后重试。'
              : '连接中断，已重新读取服务端历史。',
          requestId,
          type: error instanceof ApiError ? 'fail' : 'interrupt',
        })
      }
    } finally {
      unregister()
      if (activeController.current === controller) {
        activeController.current = null
        activeRequestId.current = null
      }
      await reconcileHistory(sessionId)
    }
  }

  const stop = () => {
    if (activeRequestId.current !== null) {
      dispatch({ requestId: activeRequestId.current, type: 'cancel' })
    }
    activeController.current?.abort()
  }

  return (
    <section aria-label="实时对话" className={styles.workspace}>
      {state.query ? (
        <div className={styles.turn}>
          <p className={styles.role}>你</p>
          <p>{state.query}</p>
          <p className={styles.role}>Agent</p>
          <div aria-live="polite" className={styles.answer}>
            {state.answer ? (
              <MarkdownViewer markdown={state.answer} />
            ) : (
              isActive ? '正在连接…' : state.errorMessage
            )}
          </div>
          {state.clarification ? (
            <aside className={styles.notice}>
              <strong>需要补充信息</strong>
              <p>{state.clarification}</p>
            </aside>
          ) : null}
          {state.taskPlanId ? (
            <Link to={`/tasks/${encodeURIComponent(state.taskPlanId)}`}>
              查看 TaskPlan {state.taskPlanId}
            </Link>
          ) : null}
          {state.timeline.length > 0 ? (
            <ol aria-label="执行时间线" className={styles.timeline}>
              {state.timeline.map((item, index) => (
                <li key={`${item.receivedAt}-${item.event}-${index}`}>
                  {item.description ??
                    `当前前端版本暂不支持 ${item.event}`}
                </li>
              ))}
            </ol>
          ) : null}
          {state.sources.length > 0 ? (
            <ul aria-label="实时回答来源" className={styles.sources}>
              {state.sources.map((source) => (
                <li key={source.id}>
                  <SourceReference source={source} />
                  <div className={styles.sourcePreview}>
                    <MarkdownViewer markdown={source.contentPreview} />
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
          {state.stale ? (
            <div className={styles.notice}>
              <p>知识已在生成期间更新，可以重新提问。</p>
              <Button
                onClick={() => setDraft(state.query)}
                type="button"
                variant="secondary"
              >
                重新提问
              </Button>
            </div>
          ) : null}
          <span className={styles.status}>状态：{state.status}</span>
        </div>
      ) : null}
      <form
        className={styles.composer}
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <TextField
          disabled={sessionId === null || isActive}
          error={queryError}
          id="chat-query"
          label="问题"
          maxLength={500}
          onChange={(event) => setDraft(event.target.value)}
          required
          value={draft}
        />
        <div className={styles.actions}>
          <Button
            disabled={sessionId === null || isActive || draft.trim().length === 0}
            type="submit"
          >
            发送
          </Button>
          {isActive ? (
            <Button onClick={stop} type="button" variant="secondary">
              停止读取
            </Button>
          ) : null}
        </div>
        {canUseWebSearch ? (
          <fieldset className={styles.webSettings} disabled={isActive}>
            <legend>公开 Web 设置</legend>
            <label>
              <input
                checked={webPreferences.allowDirectWeb}
                onChange={(event) =>
                  updateWebPreferences(event.target.checked, false)
                }
                type="checkbox"
              />
              允许联网搜索
            </label>
            <label>
              <input
                checked={webPreferences.allowWebFallback}
                disabled={!webPreferences.allowDirectWeb}
                onChange={(event) =>
                  updateWebPreferences(true, event.target.checked)
                }
                type="checkbox"
              />
              本地证据不足时允许 Web 补充
            </label>
          </fieldset>
        ) : null}
        {sessionId === null ? <p>请先新建或选择一个会话。</p> : null}
      </form>
    </section>
  )
}
