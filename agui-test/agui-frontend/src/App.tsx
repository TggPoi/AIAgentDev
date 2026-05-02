import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport, type UIMessage } from 'ai'
import { useMemo, useState } from 'react'
import { MessagePart } from './components/ToolPanels'
import './App.css'

/** 后端根地址（与本地 `agui-backend` 默认端口一致） */
const API_BASE = 'http://localhost:3000'

export default function App() {
  const chatUrl = `${API_BASE}/ai/chat`

  //官方文档：https://zh-hans.react.dev/reference/react/useMemo
  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: chatUrl,
      }),

      //缓存计算结果，只有当 chatUrl 发生变化时才会重新创建 transport 实例
    [chatUrl],
  )

  const { messages, sendMessage, status, stop, error, clearError } = useChat<UIMessage>({
    transport,
  })
  const [input, setInput] = useState('')

  const busy = status === 'submitted' || status === 'streaming'
  const canSend = status === 'ready' && input.trim().length > 0
  const lastAssistant = messages.filter((m) => m.role === 'assistant').at(-1)

  return (
    <div className="chat-app">
      <header className="chat-header">
        <div>
          <h1>agui</h1>
          <p className="chat-sub">后端：{chatUrl}</p>
        </div>
        {busy && (
          <button type="button" className="btn-stop" onClick={() => stop()}>
            停止
          </button>
        )}
      </header>

      <div className="chat-messages" role="log" aria-live="polite">
        {messages.length === 0 && (
          <p className="chat-empty">
            输入问题开始对话
          </p>
        )}
        {messages.map((message) => {
          const textPartIndices = message.parts
            .map((p, i) => (p.type === 'text' ? i : -1))
            .filter((i) => i >= 0)
          const lastTextPartIdx = textPartIndices[textPartIndices.length - 1]

          return (
            <article
              key={message.id}
              className={`chat-bubble chat-bubble--${message.role}`}
            >
              <span className="chat-role">
                {message.role === 'user' ? '你' : '助手'}
              </span>
              <div className="chat-body">
                {message.parts.map((part, index) => (
                  <MessagePart
                    key={`${message.id}-p-${index}`}
                    part={part}
                    textStreamActive={
                      part.type === 'text' &&
                      message.role === 'assistant' &&
                      message.id === lastAssistant?.id &&
                      index === lastTextPartIdx &&
                      busy
                    }
                  />
                ))}
              </div>
            </article>
          )
        })}
      </div>

      {error && (
        <div className="chat-error" role="alert">
          <span>{error.message}</span>
          <button type="button" onClick={() => clearError()}>
            关闭
          </button>
        </div>
      )}

      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault()
          if (!canSend) return
          void sendMessage({ text: input })
          setInput('')
        }}
      >
        <textarea
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              if (canSend) {
                void sendMessage({ text: input })
                setInput('')
              }
            }
          }}
          placeholder="输入消息，Enter 发送，Shift+Enter 换行"
          rows={3}
          disabled={status !== 'ready'}
          aria-label="消息输入"
        />
        <div className="chat-actions">
          <span className="chat-status">
            {status === 'ready' && '就绪'}
            {status === 'submitted' && '已发送…'}
            {status === 'streaming' && '生成中…'}
            {status === 'error' && '出错'}
          </span>
          <button type="submit" disabled={!canSend}>
            发送
          </button>
        </div>
      </form>
    </div>
  )
}