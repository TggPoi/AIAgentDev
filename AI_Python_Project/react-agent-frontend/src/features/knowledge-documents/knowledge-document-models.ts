import type {
  KnowledgeDocumentContentResponseDto,
  KnowledgeDocumentDetailDto,
  KnowledgeDocumentItemDto,
  KnowledgeDocumentListResponseDto,
} from '@/features/knowledge-documents/knowledge-document-contracts'


export type KnowledgeDocumentAccessSource =
  KnowledgeDocumentItemDto['access_source']
export type KnowledgeDocumentType = KnowledgeDocumentItemDto['document_type']
export type KnowledgeDocumentRenderMode =
  KnowledgeDocumentContentResponseDto['render_mode']

export interface KnowledgeDocumentSummary {
  accessSource: KnowledgeDocumentAccessSource
  departmentCode: string
  docId: string
  documentType: KnowledgeDocumentType
  fileName: string
  repositoryPath: string
  sourceRevision: string
  title: string
  updatedAt: string
}

export interface KnowledgeDocumentPage {
  items: KnowledgeDocumentSummary[]
  nextCursor: string | null
}

export interface KnowledgeDocumentDetail extends KnowledgeDocumentSummary {
  sourceId: string
  sourceProjectPath: string
  visibility: string
}

export interface KnowledgeDocumentContent {
  content: string
  docId: string
  documentType: KnowledgeDocumentType
  renderMode: KnowledgeDocumentRenderMode
  sourceRevision: string
  truncated: boolean
  warnings: string[]
}

function mapKnowledgeDocumentSummary(
  dto: KnowledgeDocumentItemDto,
): KnowledgeDocumentSummary {
  return {
    accessSource: dto.access_source,
    departmentCode: dto.department_code,
    docId: dto.doc_id,
    documentType: dto.document_type,
    fileName: dto.file_name,
    repositoryPath: dto.repository_path,
    sourceRevision: dto.source_revision,
    title: dto.title,
    updatedAt: dto.updated_at,
  }
}

export function mapKnowledgeDocumentPage(
  dto: KnowledgeDocumentListResponseDto,
): KnowledgeDocumentPage {
  return {
    items: dto.items.map(mapKnowledgeDocumentSummary),
    nextCursor: dto.next_cursor ?? null,
  }
}

export function mapKnowledgeDocumentDetail(
  dto: KnowledgeDocumentDetailDto,
): KnowledgeDocumentDetail {
  return {
    ...mapKnowledgeDocumentSummary(dto),
    sourceId: dto.source_id,
    sourceProjectPath: dto.source_project_path,
    visibility: dto.visibility,
  }
}

export function mapKnowledgeDocumentContent(
  dto: KnowledgeDocumentContentResponseDto,
): KnowledgeDocumentContent {
  return {
    content: dto.content,
    docId: dto.doc_id,
    documentType: dto.document_type,
    renderMode: dto.render_mode,
    sourceRevision: dto.source_revision,
    truncated: dto.truncated,
    warnings: [...dto.warnings],
  }
}

export function mergeKnowledgeDocumentPages(
  pages: readonly KnowledgeDocumentPage[],
): KnowledgeDocumentSummary[] {
  const seen = new Set<string>()
  const merged: KnowledgeDocumentSummary[] = []
  for (const page of pages) {
    for (const item of page.items) {
      if (seen.has(item.docId)) continue
      seen.add(item.docId)
      merged.push(item)
    }
  }
  return merged
}
