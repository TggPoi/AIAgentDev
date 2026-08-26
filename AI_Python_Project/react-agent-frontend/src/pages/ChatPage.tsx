import { useMemo } from 'react'
import { useParams } from 'react-router-dom'

import { useAuth } from '@/features/auth/AuthProvider'
import { createConversationApi } from '@/features/conversations/conversation-api'
import { ConversationsWorkspace } from '@/features/conversations/ConversationsWorkspace'


export function ChatPage() {
  const auth = useAuth()
  const { sessionId } = useParams<{ sessionId: string }>()
  const api = useMemo(
    () => createConversationApi(auth.httpClient),
    [auth.httpClient],
  )
  const userBoundary = auth.snapshot?.currentUser.userId
  if (userBoundary === undefined) return null

  return (
    <ConversationsWorkspace
      api={api}
      sessionId={sessionId ?? null}
      userBoundary={userBoundary}
    />
  )
}
