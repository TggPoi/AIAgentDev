import { describe, expect, it } from 'vitest'

import {
  clearChatWebPreferences,
  loadChatWebPreferences,
  saveChatWebPreferences,
} from '@/features/chat/chat-preferences'


describe('Chat Web preferences', () => {
  it('defaults both controls off and restores only the current user in this tab', () => {
    const storage = new Map<string, string>()
    const adapter: Storage = {
      clear: () => storage.clear(),
      getItem: (key) => storage.get(key) ?? null,
      key: (index) => [...storage.keys()][index] ?? null,
      get length() {
        return storage.size
      },
      removeItem: (key) => storage.delete(key),
      setItem: (key, value) => storage.set(key, value),
    }

    expect(loadChatWebPreferences(adapter, 'user-a')).toEqual({
      allowDirectWeb: false,
      allowWebFallback: false,
    })

    saveChatWebPreferences(adapter, 'user-a', {
      allowDirectWeb: true,
      allowWebFallback: true,
    })
    expect(loadChatWebPreferences(adapter, 'user-a')).toEqual({
      allowDirectWeb: true,
      allowWebFallback: true,
    })
    expect(loadChatWebPreferences(adapter, 'user-b')).toEqual({
      allowDirectWeb: false,
      allowWebFallback: false,
    })

    clearChatWebPreferences(adapter, 'user-a')
    expect(loadChatWebPreferences(adapter, 'user-a')).toEqual({
      allowDirectWeb: false,
      allowWebFallback: false,
    })
  })
})
