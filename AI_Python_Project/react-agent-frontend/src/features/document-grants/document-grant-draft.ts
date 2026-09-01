import type { CreateDocumentAccessGrantsRequestDto } from '@/features/document-grants/document-grant-contracts'
import type { GrantableDocument } from '@/features/document-grants/document-grant-models'


export interface CreateDocumentGrantDraft {
  selectedDocuments: GrantableDocument[]
  targetAccount: string
}

export interface CreateDocumentGrantDraftErrors {
  documentIds?: string
  targetAccount?: string
}

export type CreateDocumentGrantDraftResult =
  | { ok: true; request: CreateDocumentAccessGrantsRequestDto }
  | { errors: CreateDocumentGrantDraftErrors; ok: false }

export function buildCreateDocumentGrantsRequest(
  draft: CreateDocumentGrantDraft,
): CreateDocumentGrantDraftResult {
  const targetAccount = draft.targetAccount.trim().toLowerCase()
  if (!targetAccount) {
    return {
      errors: { targetAccount: '请输入精确用户名或邮箱。' },
      ok: false,
    }
  }
  if (targetAccount.length > 255) {
    return {
      errors: { targetAccount: '精确用户名或邮箱不能超过 255 个字符。' },
      ok: false,
    }
  }

  if (draft.selectedDocuments.length === 0) {
    return {
      errors: { documentIds: '请至少选择一篇可授权文档。' },
      ok: false,
    }
  }
  if (draft.selectedDocuments.length > 100) {
    return {
      errors: { documentIds: '一次最多选择 100 篇可授权文档。' },
      ok: false,
    }
  }

  const documentIds = draft.selectedDocuments.map(
    (document) => document.documentId,
  )
  if (new Set(documentIds).size !== documentIds.length) {
    return {
      errors: { documentIds: '已选文档不能重复。' },
      ok: false,
    }
  }

  return {
    ok: true,
    request: {
      document_ids: documentIds,
      target_account: targetAccount,
    },
  }
}
