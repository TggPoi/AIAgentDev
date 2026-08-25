import type { PropsWithChildren } from 'react'
import { Navigate } from 'react-router-dom'

import { useAuth } from '@/features/auth/AuthProvider'
import type { Capabilities } from '@/features/auth/auth-models'

interface CapabilityGuardProps extends PropsWithChildren {
  capability: keyof Capabilities
}

const CAPABILITY_DENIED_NOTICE =
  '当前账号没有访问该页面的能力，已返回安全入口。'

export function CapabilityGuard({
  capability,
  children,
}: CapabilityGuardProps) {
  const auth = useAuth()
  if (!auth.snapshot?.capabilities[capability]) {
    return (
      <Navigate
        replace
        state={{ shellNotice: CAPABILITY_DENIED_NOTICE }}
        to="/chat"
      />
    )
  }
  return children
}
