import { describe, expect, it } from 'vitest'

import {
  buildCreateDocumentGrantsRequest,
  type CreateDocumentGrantDraft,
} from '@/features/document-grants/document-grant-draft'
import type { GrantableDocument } from '@/features/document-grants/document-grant-models'


function document(documentId: string): GrantableDocument {
  return {
    documentDepartmentCode: 'development',
    documentId,
    documentType: 'markdown',
    repositoryPath: `docs/${documentId}.md`,
    title: `Document ${documentId}`,
  }
}

function draft(
  overrides: Partial<CreateDocumentGrantDraft> = {},
): CreateDocumentGrantDraft {
  return {
    selectedDocuments: [document('doc-1')],
    targetAccount: ' Reader@Example.com ',
    ...overrides,
  }
}

describe('document grant catalog-backed create draft policy', () => {
  it('builds only the exact account and IDs from selected safe catalog items', () => {
    expect(
      buildCreateDocumentGrantsRequest(
        draft({ selectedDocuments: [document('doc-1'), document('doc-2')] }),
      ),
    ).toEqual({
      ok: true,
      request: {
        document_ids: ['doc-1', 'doc-2'],
        target_account: 'reader@example.com',
      },
    })
  })

  it('rejects a blank or overlong exact target account', () => {
    expect(
      buildCreateDocumentGrantsRequest(draft({ targetAccount: '   ' })),
    ).toEqual({
      errors: { targetAccount: '请输入精确用户名或邮箱。' },
      ok: false,
    })
    expect(
      buildCreateDocumentGrantsRequest(draft({ targetAccount: 'a'.repeat(256) })),
    ).toEqual({
      errors: { targetAccount: '精确用户名或邮箱不能超过 255 个字符。' },
      ok: false,
    })
  })

  it('requires between one and one hundred selected catalog documents', () => {
    expect(
      buildCreateDocumentGrantsRequest(draft({ selectedDocuments: [] })),
    ).toEqual({
      errors: { documentIds: '请至少选择一篇可授权文档。' },
      ok: false,
    })
    expect(
      buildCreateDocumentGrantsRequest(
        draft({
          selectedDocuments: Array.from({ length: 101 }, (_, index) =>
            document(`doc-${index}`),
          ),
        }),
      ),
    ).toEqual({
      errors: { documentIds: '一次最多选择 100 篇可授权文档。' },
      ok: false,
    })
  })

  it('rejects duplicate catalog selections instead of sending duplicate IDs', () => {
    expect(
      buildCreateDocumentGrantsRequest(
        draft({ selectedDocuments: [document('doc-1'), document('doc-1')] }),
      ),
    ).toEqual({
      errors: { documentIds: '已选文档不能重复。' },
      ok: false,
    })
  })
})
