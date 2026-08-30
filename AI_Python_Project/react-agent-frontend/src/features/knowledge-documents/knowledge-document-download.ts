import { protocolApiError } from '@/api/api-error'
import type { KnowledgeDocumentDownload } from '@/features/knowledge-documents/knowledge-document-api'


interface KnowledgeDocumentDownloader {
  downloadDocument(docId: string): Promise<KnowledgeDocumentDownload>
}

export interface KnowledgeDocumentDownloadEnvironment {
  createObjectUrl(blob: Blob): string
  revokeObjectUrl(url: string): void
  triggerDownload(url: string, fileName: string): void
}

interface SaveKnowledgeDocumentDownloadOptions {
  contentRevision: string
  detailRevision: string
  docId: string
  downloader: KnowledgeDocumentDownloader
  environment?: KnowledgeDocumentDownloadEnvironment
}

export type KnowledgeDocumentDownloadResult =
  | { fileName: string; status: 'saved' }
  | { status: 'revision_mismatch' }

const browserEnvironment: KnowledgeDocumentDownloadEnvironment = {
  createObjectUrl: (blob) => URL.createObjectURL(blob),
  revokeObjectUrl: (url) => URL.revokeObjectURL(url),
  triggerDownload: (url, fileName) => {
    const anchor = document.createElement('a')
    anchor.download = fileName
    anchor.href = url
    anchor.hidden = true
    document.body.append(anchor)
    try {
      anchor.click()
    } finally {
      anchor.remove()
    }
  },
}

function safeFileName(value: string): string | null {
  const fileName = value.trim()
  const hasControlCharacter = Array.from(fileName).some((character) => {
    const codePoint = character.codePointAt(0) ?? 0
    return codePoint <= 0x1f || codePoint === 0x7f
  })
  if (
    fileName.length === 0 ||
    fileName.length > 255 ||
    fileName === '.' ||
    fileName === '..' ||
    hasControlCharacter ||
    /[/\\:*?"<>|]/u.test(fileName)
  ) {
    return null
  }
  return fileName
}

function fileNameFromContentDisposition(value: string | null): string | null {
  if (value === null || !/^\s*attachment(?:\s*;|\s*$)/iu.test(value)) {
    return null
  }

  const encodedMatch = value.match(/(?:^|;)\s*filename\*\s*=\s*([^;]+)/iu)
  if (encodedMatch) {
    const encoded = encodedMatch[1]?.trim().replace(/^"|"$/gu, '') ?? ''
    const utf8Match = encoded.match(/^UTF-8''(.+)$/iu)
    if (!utf8Match) return null
    try {
      return safeFileName(decodeURIComponent(utf8Match[1] ?? ''))
    } catch {
      return null
    }
  }

  const plainMatch = value.match(
    /(?:^|;)\s*filename\s*=\s*(?:"([^"]*)"|([^;]*))/iu,
  )
  return safeFileName((plainMatch?.[1] ?? plainMatch?.[2] ?? '').trim())
}

export async function saveKnowledgeDocumentDownload({
  contentRevision,
  detailRevision,
  docId,
  downloader,
  environment = browserEnvironment,
}: SaveKnowledgeDocumentDownloadOptions): Promise<KnowledgeDocumentDownloadResult> {
  if (detailRevision !== contentRevision) {
    return { status: 'revision_mismatch' }
  }

  const download = await downloader.downloadDocument(docId)
  if (
    download.sourceRevision === null ||
    download.sourceRevision !== detailRevision
  ) {
    return { status: 'revision_mismatch' }
  }

  const fileName = fileNameFromContentDisposition(download.contentDisposition)
  if (fileName === null) {
    throw protocolApiError({
      code: 'INVALID_DOCUMENT_FILENAME',
      message: '下载响应缺少安全文件名',
      requestId: download.requestId,
      status: 200,
    })
  }

  const objectUrl = environment.createObjectUrl(download.blob)
  try {
    environment.triggerDownload(objectUrl, fileName)
  } finally {
    environment.revokeObjectUrl(objectUrl)
  }
  return { fileName, status: 'saved' }
}
