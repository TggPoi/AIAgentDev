import type {
  ConversationItemDto,
  ConversationListResponseDto,
  ConversationMessageItemDto,
  ConversationMessageListResponseDto,
} from '@/features/conversations/conversation-contracts'


export interface ConversationSummary {
  createdAt: string
  kind: 'conversation'
  lastMessagePreview: string | null
  lastMessageRole: 'assistant' | 'user' | null
  messageCount: number
  sessionId: string
  title: string
  updatedAt: string
}

export interface ConversationPage {
  items: ConversationSummary[]
  nextCursor: string | null
}

export interface HistoricalSource {
  contentPreview: string
  docId: string | null
  href: string | null
  id: string
  sectionPath: string[]
  sourceType: 'knowledge_document' | 'web'
  title: string | null
}

export interface PersistedConversationMessage {
  agentTaskPlanId: string | null
  agentTaskStatus: string | null
  content: string
  createdAt: string
  kind: 'persisted'
  messageId: string
  role: 'assistant' | 'user'
  sequenceNo: number
  sources: HistoricalSource[]
  terminalStatus: 'aborted' | 'completed' | 'error'
}

export interface PendingUserMessage {
  clientMessageId: string
  content: string
  createdAt: string
  kind: 'pending'
  role: 'user'
}

export type ConversationTimelineMessage =
  | PendingUserMessage
  | PersistedConversationMessage

export interface ConversationMessagePage {
  items: PersistedConversationMessage[]
  nextCursor: string | null
}

function mapConversation(dto: ConversationItemDto): ConversationSummary {
  return {
    createdAt: dto.created_at,
    kind: 'conversation',
    lastMessagePreview: dto.last_message_preview ?? null,
    lastMessageRole: dto.last_message_role ?? null,
    messageCount: dto.message_count,
    sessionId: dto.session_id,
    title: dto.title,
    updatedAt: dto.updated_at,
  }
}

function mapMessage(
  dto: ConversationMessageItemDto,
): PersistedConversationMessage {
  return {
    agentTaskPlanId: dto.agent_task_plan_id ?? null,
    agentTaskStatus: dto.agent_task_status ?? null,
    content: dto.content,
    createdAt: dto.created_at,
    kind: 'persisted',
    messageId: dto.message_id,
    role: dto.role,
    sequenceNo: dto.sequence_no,
    sources: (dto.sources ?? []).map((source) => ({
      contentPreview: source.content_preview,
      docId: source.doc_id ?? null,
      href: source.href ?? null,
      id: source.id,
      sectionPath: [...(source.section_path ?? [])],
      sourceType: source.source_type,
      title: source.title ?? null,
    })),
    terminalStatus: dto.terminal_status,
  }
}

export function mapConversationPage(
  dto: ConversationListResponseDto,
): ConversationPage {
  return {
    items: dto.items.map(mapConversation),
    nextCursor: dto.next_cursor ?? null,
  }
}

export function mapConversationMessagePage(
  dto: ConversationMessageListResponseDto,
): ConversationMessagePage {
  return {
    items: dto.items.map(mapMessage),
    nextCursor: dto.next_cursor ?? null,
  }
}

export function mergeConversationPages(
  pages: readonly ConversationPage[],
): ConversationSummary[] {
  const seen = new Set<string>()
  const merged: ConversationSummary[] = []
  for (const page of pages) {
    for (const item of page.items) {
      if (seen.has(item.sessionId)) continue
      seen.add(item.sessionId)
      merged.push(item)
    }
  }
  return merged
}

export function mergeMessagePages(
  pages: readonly ConversationMessagePage[],
): PersistedConversationMessage[] {
  const seen = new Set<string>()
  const merged: PersistedConversationMessage[] = []
  for (const page of pages) {
    for (const item of page.items) {
      if (seen.has(item.messageId)) continue
      seen.add(item.messageId)
      merged.push(item)
    }
  }
  return merged
}
