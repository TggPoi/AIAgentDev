const DEFAULT_AUTHENTICATED_ROUTE = '/chat'

export function validateLoginReturnPath(
  candidate: string | null | undefined,
  applicationOrigin: string,
): string {
  if (
    typeof candidate !== 'string' ||
    !candidate.startsWith('/') ||
    candidate.startsWith('//') ||
    candidate.includes('\\')
  ) {
    return DEFAULT_AUTHENTICATED_ROUTE
  }

  let decodedCandidate: string
  try {
    decodedCandidate = decodeURIComponent(candidate)
  } catch {
    return DEFAULT_AUTHENTICATED_ROUTE
  }
  if (decodedCandidate.startsWith('//') || decodedCandidate.includes('\\')) {
    return DEFAULT_AUTHENTICATED_ROUTE
  }

  try {
    const expectedOrigin = new URL(applicationOrigin).origin
    const parsed = new URL(candidate, expectedOrigin)
    if (parsed.origin !== expectedOrigin) {
      return DEFAULT_AUTHENTICATED_ROUTE
    }
    return `${parsed.pathname}${parsed.search}${parsed.hash}`
  } catch {
    return DEFAULT_AUTHENTICATED_ROUTE
  }
}
