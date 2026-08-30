import { useMemo } from 'react'
import { useParams } from 'react-router-dom'

import { useAuth } from '@/features/auth/AuthProvider'
import { createKnowledgeDocumentApi } from '@/features/knowledge-documents/knowledge-document-api'
import { KnowledgeDocumentWorkspace } from '@/features/knowledge-documents/KnowledgeDocumentWorkspace'


export function DocumentPage() {
  const auth = useAuth()
  const { docId } = useParams<{ docId: string }>()
  const api = useMemo(
    () => createKnowledgeDocumentApi(auth.httpClient),
    [auth.httpClient],
  )
  const snapshot = auth.snapshot
  if (snapshot === null) return null
  const userBoundary = snapshot.currentUser.userId

  return (
    <KnowledgeDocumentWorkspace
      api={api}
      docId={docId ?? null}
      key={`${userBoundary}:${docId ?? '__list__'}`}
      userBoundary={userBoundary}
    />
  )
}
