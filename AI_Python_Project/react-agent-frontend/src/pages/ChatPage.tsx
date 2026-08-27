import { useMemo } from 'react'
import { useParams } from 'react-router-dom'

import { useAuth } from '@/features/auth/AuthProvider'
import { createChatApi } from '@/features/chat/chat-api'
import { ChatWorkspace } from '@/features/chat/ChatWorkspace'
import { createConversationApi } from '@/features/conversations/conversation-api'
import { ConversationsWorkspace } from '@/features/conversations/ConversationsWorkspace'


export function ChatPage() {
  const auth = useAuth()
  const { sessionId } = useParams<{ sessionId: string }>()
  const api = useMemo(
    () => createConversationApi(auth.httpClient),
    [auth.httpClient],
  )
  const chatApi = useMemo(() => createChatApi(auth.httpClient), [auth.httpClient])
  const snapshot = auth.snapshot
  if (snapshot === null) return null
  const userBoundary = snapshot.currentUser.userId

  return (
    <ConversationsWorkspace
      api={api}
      chatPanel={
        <ChatWorkspace
          api={chatApi}
          canUseWebSearch={snapshot.capabilities.canUseWebSearch}
          key={`${userBoundary}:${sessionId ?? '__new__'}`}
          registerPrivateActivity={auth.registerPrivateActivity}
          sessionId={sessionId ?? null}
          userBoundary={userBoundary}
        />
      }
      sessionId={sessionId ?? null}
      userBoundary={userBoundary}
    />
  )
}
