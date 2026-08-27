export function credentialFreeHttpHref(href: string | null): string | null {
  if (href === null) return null
  try {
    const url = new URL(href)
    return (url.protocol === 'http:' || url.protocol === 'https:') &&
      url.username.length === 0 &&
      url.password.length === 0
      ? href
      : null
  } catch {
    return null
  }
}
