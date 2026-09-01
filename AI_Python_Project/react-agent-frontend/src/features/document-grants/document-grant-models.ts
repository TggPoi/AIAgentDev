import type {
  CreateDocumentAccessGrantsResponseDto,
  DocumentAccessGrantItemDto,
  DocumentAccessGrantListResponseDto,
  DocumentAccessGrantUserDto,
} from '@/features/document-grants/document-grant-contracts'


export type DocumentGrantStatus = DocumentAccessGrantItemDto['status']

export interface DocumentGrantUser {
  displayName: string | null
  primaryDepartmentCode: string | null
  userId: string
  username: string
}

export interface DocumentGrant {
  documentDepartmentCode: string
  documentId: string
  grantId: string
  grantedAt: string
  grantedByUserId: string
  grantee: DocumentGrantUser
  repositoryPath: string
  revokedAt: string | null
  revokedByUserId: string | null
  status: DocumentGrantStatus
}

export interface DocumentGrantPage {
  items: DocumentGrant[]
  nextCursor: string | null
}

export interface CreateDocumentGrantsResult {
  createdCount: number
  existingCount: number
  items: DocumentGrant[]
}

function mapDocumentGrantUser(
  dto: DocumentAccessGrantUserDto,
): DocumentGrantUser {
  return {
    displayName: dto.display_name ?? null,
    primaryDepartmentCode: dto.primary_department_code ?? null,
    userId: dto.user_id,
    username: dto.username,
  }
}

export function mapDocumentGrant(
  dto: DocumentAccessGrantItemDto,
): DocumentGrant {
  return {
    documentDepartmentCode: dto.document_department_code,
    documentId: dto.document_id,
    grantId: dto.grant_id,
    grantedAt: dto.granted_at,
    grantedByUserId: dto.granted_by_user_id,
    grantee: mapDocumentGrantUser(dto.grantee),
    repositoryPath: dto.repository_path,
    revokedAt: dto.revoked_at ?? null,
    revokedByUserId: dto.revoked_by_user_id ?? null,
    status: dto.status,
  }
}

export function mapDocumentGrantPage(
  dto: DocumentAccessGrantListResponseDto,
): DocumentGrantPage {
  return {
    items: dto.items.map(mapDocumentGrant),
    nextCursor: dto.next_cursor ?? null,
  }
}

export function mapCreateDocumentGrantsResult(
  dto: CreateDocumentAccessGrantsResponseDto,
): CreateDocumentGrantsResult {
  return {
    createdCount: dto.created_count,
    existingCount: dto.existing_count,
    items: dto.items.map(mapDocumentGrant),
  }
}

export function mergeDocumentGrantPages(
  pages: readonly DocumentGrantPage[],
): DocumentGrant[] {
  const seen = new Set<string>()
  const merged: DocumentGrant[] = []
  for (const page of pages) {
    for (const item of page.items) {
      if (seen.has(item.grantId)) continue
      seen.add(item.grantId)
      merged.push(item)
    }
  }
  return merged
}
