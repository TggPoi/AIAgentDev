import { useMemo } from 'react'
import { useParams } from 'react-router-dom'

import { useAuth } from '@/features/auth/AuthProvider'
import { createUserManagementApi } from '@/features/user-management/user-management-api'
import { UserManagementWorkspace } from '@/features/user-management/UserManagementWorkspace'


export function UserManagementPage() {
  const auth = useAuth()
  const { userId } = useParams<{ userId: string }>()
  const api = useMemo(
    () => createUserManagementApi(auth.httpClient),
    [auth.httpClient],
  )
  const snapshot = auth.snapshot
  if (snapshot === null) return null
  const userBoundary = snapshot.currentUser.userId

  return (
    <UserManagementWorkspace
      api={api}
      currentUserId={snapshot.currentUser.userId}
      key={`${userBoundary}:${userId ?? '__list__'}`}
      reloadIdentitySnapshot={auth.reloadIdentitySnapshot}
      userBoundary={userBoundary}
      userId={userId ?? null}
    />
  )
}
