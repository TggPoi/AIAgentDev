import { describe, expect, it, vi } from 'vitest'

import {
  saveKnowledgeDocumentDownload,
  type KnowledgeDocumentDownloadEnvironment,
} from '@/features/knowledge-documents/knowledge-document-download'


function environment() {
  const calls: string[] = []
  const value: KnowledgeDocumentDownloadEnvironment = {
    createObjectUrl: () => {
      calls.push('create')
      return 'blob:knowledge-document'
    },
    revokeObjectUrl: (url) => calls.push(`revoke:${url}`),
    triggerDownload: (url, fileName) =>
      calls.push(`download:${url}:${fileName}`),
  }
  return { calls, value }
}

function downloader(options: {
  contentDisposition?: string | null
  sourceRevision?: string | null
}) {
  return {
    downloadDocument: vi.fn().mockResolvedValue({
      blob: new Blob(['document bytes']),
      contentDisposition:
        options.contentDisposition === undefined
          ? "attachment; filename*=UTF-8''guide%20v1.md"
          : options.contentDisposition,
      requestId: 'download-request-id',
      sourceRevision:
        options.sourceRevision === undefined
          ? 'revision-1'
          : options.sourceRevision,
    }),
  }
}

describe('knowledge document download policy', () => {
  it('saves only a matching revision with a decoded header filename and revokes the URL', async () => {
    const api = downloader({})
    const sideEffects = environment()

    const result = await saveKnowledgeDocumentDownload({
      contentRevision: 'revision-1',
      detailRevision: 'revision-1',
      docId: 'doc-1',
      downloader: api,
      environment: sideEffects.value,
    })

    expect(result).toEqual({ fileName: 'guide v1.md', status: 'saved' })
    expect(api.downloadDocument).toHaveBeenCalledWith('doc-1')
    expect(sideEffects.calls).toEqual([
      'create',
      'download:blob:knowledge-document:guide v1.md',
      'revoke:blob:knowledge-document',
    ])
  })

  it('does not fetch or save when detail and content revisions already differ', async () => {
    const api = downloader({})
    const sideEffects = environment()

    const result = await saveKnowledgeDocumentDownload({
      contentRevision: 'revision-2',
      detailRevision: 'revision-1',
      docId: 'doc-1',
      downloader: api,
      environment: sideEffects.value,
    })

    expect(result).toEqual({ status: 'revision_mismatch' })
    expect(api.downloadDocument).not.toHaveBeenCalled()
    expect(sideEffects.calls).toEqual([])
  })

  it('discards a downloaded Blob when the response revision does not match', async () => {
    const api = downloader({ sourceRevision: 'revision-2' })
    const sideEffects = environment()

    const result = await saveKnowledgeDocumentDownload({
      contentRevision: 'revision-1',
      detailRevision: 'revision-1',
      docId: 'doc-1',
      downloader: api,
      environment: sideEffects.value,
    })

    expect(result).toEqual({ status: 'revision_mismatch' })
    expect(sideEffects.calls).toEqual([])
  })

  it.each([
    null,
    'attachment',
    "attachment; filename*=UTF-8''..%2Fprivate.txt",
    'attachment; filename="..\\private.txt"',
  ])('rejects a missing or unsafe filename header: %s', async (header) => {
    const api = downloader({ contentDisposition: header })
    const sideEffects = environment()

    await expect(
      saveKnowledgeDocumentDownload({
        contentRevision: 'revision-1',
        detailRevision: 'revision-1',
        docId: 'doc-1',
        downloader: api,
        environment: sideEffects.value,
      }),
    ).rejects.toMatchObject({
      code: 'INVALID_DOCUMENT_FILENAME',
      requestId: 'download-request-id',
      statusKind: 'protocol',
    })
    expect(sideEffects.calls).toEqual([])
  })

  it('revokes the object URL even when the browser save trigger fails', async () => {
    const api = downloader({})
    const sideEffects = environment()
    sideEffects.value.triggerDownload = () => {
      sideEffects.calls.push('download-failed')
      throw new Error('save unavailable')
    }

    await expect(
      saveKnowledgeDocumentDownload({
        contentRevision: 'revision-1',
        detailRevision: 'revision-1',
        docId: 'doc-1',
        downloader: api,
        environment: sideEffects.value,
      }),
    ).rejects.toThrow('save unavailable')
    expect(sideEffects.calls).toEqual([
      'create',
      'download-failed',
      'revoke:blob:knowledge-document',
    ])
  })
})
