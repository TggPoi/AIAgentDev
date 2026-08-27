export interface ChatWebPreferences {
  allowDirectWeb: boolean
  allowWebFallback: boolean
}

const defaults: ChatWebPreferences = {
  allowDirectWeb: false,
  allowWebFallback: false,
}

function preferenceKey(userBoundary: string): string {
  return `react-agent.chat.web.${encodeURIComponent(userBoundary)}`
}

export function loadChatWebPreferences(
  storage: Storage,
  userBoundary: string,
): ChatWebPreferences {
  try {
    const raw = storage.getItem(preferenceKey(userBoundary))
    if (raw === null) return { ...defaults }
    const value: unknown = JSON.parse(raw)
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      return { ...defaults }
    }
    const record = value as Record<string, unknown>
    return {
      allowDirectWeb: record.allowDirectWeb === true,
      allowWebFallback:
        record.allowDirectWeb === true && record.allowWebFallback === true,
    }
  } catch {
    return { ...defaults }
  }
}

export function saveChatWebPreferences(
  storage: Storage,
  userBoundary: string,
  preferences: ChatWebPreferences,
): void {
  try {
    storage.setItem(
      preferenceKey(userBoundary),
      JSON.stringify({
        allowDirectWeb: preferences.allowDirectWeb,
        allowWebFallback:
          preferences.allowDirectWeb && preferences.allowWebFallback,
      }),
    )
  } catch {
    // Storage can be unavailable; request safety still comes from the adapter.
  }
}

export function clearChatWebPreferences(
  storage: Storage,
  userBoundary: string,
): void {
  try {
    storage.removeItem(preferenceKey(userBoundary))
  } catch {
    // Nothing else should fail because tab-scoped storage is unavailable.
  }
}
