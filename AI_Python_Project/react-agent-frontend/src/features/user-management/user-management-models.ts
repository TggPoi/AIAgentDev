import type {
  AccessCatalogItemDto,
  AccessCatalogResponseDto,
  AccountTypeDto,
  ManagedDepartmentAccessDto,
  ManagedUserDetailDto,
  ManagedUserListResponseDto,
  ManagedUserPasswordResetResponseDto,
  ManagedUserStatusResponseDto,
  ManagedUserSummaryDto,
  UserStatusDto,
} from '@/features/user-management/user-management-contracts'


export type AccountType = AccountTypeDto
export type UserStatus = UserStatusDto

export interface AccessCatalogItem {
  code: string
  description: string | null
  name: string
  riskLevel: string | null
}

export interface AccessCatalog {
  accountTypes: AccessCatalogItem[]
  departmentRoles: AccessCatalogItem[]
  departments: AccessCatalogItem[]
  directPermissions: AccessCatalogItem[]
}

export interface ManagedUserSummary {
  accountType: AccountType
  departmentCodes: string[]
  displayName: string | null
  email: string | null
  primaryDepartmentCode: string | null
  status: UserStatus
  updatedAt: string
  userId: string
  username: string
}

export interface ManagedUserPage {
  items: ManagedUserSummary[]
  nextCursor: string | null
}

export interface ManagedDepartmentAccess {
  departmentCode: string
  isPrimary: boolean
  permissionCodes: string[]
  roleCodes: string[]
}

export interface ManagedUserDetail {
  accountType: AccountType
  createdAt: string
  departmentAccess: ManagedDepartmentAccess[]
  directPermissionCodes: string[]
  displayName: string | null
  effectiveGlobalPermissionCodes: string[]
  email: string | null
  globalRoleCodes: string[]
  lastLoginAt: string | null
  status: UserStatus
  updatedAt: string
  userId: string
  username: string
}

export interface ManagedUserStatusResult {
  revokedApiKeyCount: number
  revokedRefreshTokenCount: number
  user: ManagedUserDetail
}

export interface ManagedUserPasswordResetResult {
  passwordReset: boolean
  revokedApiKeyCount: number
  revokedRefreshTokenCount: number
}

function mapCatalogItem(dto: AccessCatalogItemDto): AccessCatalogItem {
  return {
    code: dto.code,
    description: dto.description ?? null,
    name: dto.name,
    riskLevel: dto.risk_level ?? null,
  }
}

export function mapAccessCatalog(
  dto: AccessCatalogResponseDto,
): AccessCatalog {
  return {
    accountTypes: dto.account_types.map(mapCatalogItem),
    departmentRoles: dto.department_roles.map(mapCatalogItem),
    departments: dto.departments.map(mapCatalogItem),
    directPermissions: dto.direct_permissions.map(mapCatalogItem),
  }
}

function mapManagedUserSummary(
  dto: ManagedUserSummaryDto,
): ManagedUserSummary {
  return {
    accountType: dto.account_type,
    departmentCodes: [...dto.department_codes],
    displayName: dto.display_name ?? null,
    email: dto.email ?? null,
    primaryDepartmentCode: dto.primary_department_code,
    status: dto.status,
    updatedAt: dto.updated_at,
    userId: dto.user_id,
    username: dto.username,
  }
}

export function mapManagedUserPage(
  dto: ManagedUserListResponseDto,
): ManagedUserPage {
  return {
    items: dto.items.map(mapManagedUserSummary),
    nextCursor: dto.next_cursor ?? null,
  }
}

function mapDepartmentAccess(
  dto: ManagedDepartmentAccessDto,
): ManagedDepartmentAccess {
  return {
    departmentCode: dto.department_code,
    isPrimary: dto.is_primary,
    permissionCodes: [...dto.permission_codes],
    roleCodes: [...dto.role_codes],
  }
}

export function mapManagedUserDetail(
  dto: ManagedUserDetailDto,
): ManagedUserDetail {
  return {
    accountType: dto.account_type,
    createdAt: dto.created_at,
    departmentAccess: dto.department_access.map(mapDepartmentAccess),
    directPermissionCodes: [...dto.direct_permission_codes],
    displayName: dto.display_name ?? null,
    effectiveGlobalPermissionCodes: [
      ...dto.effective_global_permission_codes,
    ],
    email: dto.email ?? null,
    globalRoleCodes: [...dto.global_role_codes],
    lastLoginAt: dto.last_login_at ?? null,
    status: dto.status,
    updatedAt: dto.updated_at,
    userId: dto.user_id,
    username: dto.username,
  }
}

export function mapManagedUserStatusResult(
  dto: ManagedUserStatusResponseDto,
): ManagedUserStatusResult {
  return {
    revokedApiKeyCount: dto.revoked_api_key_count,
    revokedRefreshTokenCount: dto.revoked_refresh_token_count,
    user: mapManagedUserDetail(dto.user),
  }
}

export function mapManagedUserPasswordResetResult(
  dto: ManagedUserPasswordResetResponseDto,
): ManagedUserPasswordResetResult {
  return {
    passwordReset: dto.password_reset,
    revokedApiKeyCount: dto.revoked_api_key_count,
    revokedRefreshTokenCount: dto.revoked_refresh_token_count,
  }
}

export function mergeManagedUserPages(
  pages: readonly ManagedUserPage[],
): ManagedUserSummary[] {
  const seen = new Set<string>()
  const merged: ManagedUserSummary[] = []
  for (const page of pages) {
    for (const item of page.items) {
      if (seen.has(item.userId)) continue
      seen.add(item.userId)
      merged.push(item)
    }
  }
  return merged
}
