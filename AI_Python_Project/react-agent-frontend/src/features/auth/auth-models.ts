import type {
  CurrentUserDto,
  UserCapabilitiesDto,
} from '@/features/auth/auth-contracts'


export interface CurrentUser {
  accountType: CurrentUserDto['account_type']
  authSource: string
  departmentCodes: string[]
  departmentPermissionCodes: Record<string, string[]>
  displayName: string | null
  email: string | null
  globalPermissionCodes: string[]
  globalRoleCodes: string[]
  isAuthenticated: boolean
  primaryDepartmentCode: string | null
  userId: string
  username: string
}

export interface Capabilities {
  canManageDocumentGrants: boolean
  canManageDocuments: boolean
  canManageUsers: boolean
  canReadDocuments: boolean
  canUseNl2sql: boolean
  canUseWebSearch: boolean
  userManagementScope: UserCapabilitiesDto['user_management_scope']
}

export interface IdentitySnapshot {
  capabilities: Capabilities
  currentUser: CurrentUser
}

export interface ChangePasswordResult {
  passwordChanged: boolean
  revokedRefreshTokenCount: number
}

export function mapCurrentUser(dto: CurrentUserDto): CurrentUser {
  return {
    accountType: dto.account_type,
    authSource: dto.auth_source,
    departmentCodes: [...(dto.department_codes ?? [])],
    departmentPermissionCodes: Object.fromEntries(
      Object.entries(dto.department_permission_codes ?? {}).map(
        ([key, values]) => [key, [...values]],
      ),
    ),
    displayName: dto.display_name ?? null,
    email: dto.email ?? null,
    globalPermissionCodes: [...(dto.global_permission_codes ?? [])],
    globalRoleCodes: [...(dto.global_role_codes ?? [])],
    isAuthenticated: dto.is_authenticated,
    primaryDepartmentCode: dto.primary_department_code ?? null,
    userId: dto.user_id,
    username: dto.username,
  }
}

export function mapCapabilities(dto: UserCapabilitiesDto): Capabilities {
  return {
    canManageDocumentGrants: dto.can_manage_document_grants,
    canManageDocuments: dto.can_manage_documents,
    canManageUsers: dto.can_manage_users,
    canReadDocuments: dto.can_read_documents,
    canUseNl2sql: dto.can_use_nl2sql,
    canUseWebSearch: dto.can_use_web_search,
    userManagementScope: dto.user_management_scope,
  }
}
