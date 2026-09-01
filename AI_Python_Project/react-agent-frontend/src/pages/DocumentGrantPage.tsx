import { useMemo } from 'react'

import { useAuth } from '@/features/auth/AuthProvider'
import { createDocumentGrantApi } from '@/features/document-grants/document-grant-api'
import { DocumentGrantWorkspace } from '@/features/document-grants/DocumentGrantWorkspace'


export function DocumentGrantPage() {
  const auth = useAuth()
  const api = useMemo(
    () => createDocumentGrantApi(auth.httpClient),
    [auth.httpClient],
  )
  const snapshot = auth.snapshot
  if (snapshot === null) return null
  const userBoundary = snapshot.currentUser.userId

  return (
    <DocumentGrantWorkspace
      api={api}
      key={userBoundary}
      userBoundary={userBoundary}
    />
  )
}
