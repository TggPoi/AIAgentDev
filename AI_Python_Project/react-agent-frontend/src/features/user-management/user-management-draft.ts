import type {
  CreateManagedUserRequestDto,
  ReplaceManagedUserAccessRequestDto,
} from '@/features/user-management/user-management-contracts'
import type {
  AccessCatalog,
  AccountType,
} from '@/features/user-management/user-management-models'


export interface ManagedUserDepartmentAccessDraft {
  departmentCode: string
  isPrimary: boolean
  roleCodes: string[]
}

export interface ManagedUserAccessDraft {
  accountType: string
  departmentAccess: ManagedUserDepartmentAccessDraft[]
  directPermissionCodes: string[]
}

export interface CreateManagedUserDraft {
  access: ManagedUserAccessDraft
  displayName: string | null
  email: string | null
  password: string
  username: string
}

export interface AccessDraftValidationErrors {
  accountType?: string
  departmentAccess?: string
  directPermissionCodes?: string
}

export type AccessDraftBuildResult<T> =
  | { ok: true; request: T }
  | { errors: AccessDraftValidationErrors; ok: false }

export interface ReconciledAccessDraft {
  changed: boolean
  draft: ManagedUserAccessDraft
  requiresReconfirmation: boolean
}

const accountTypes = new Set<AccountType>([
  'admin',
  'department_manager',
  'employee',
])

function isAccountType(value: string): value is AccountType {
  return accountTypes.has(value as AccountType)
}

function codeSet(items: AccessCatalog['departments']): Set<string> {
  return new Set(items.map((item) => item.code))
}

function filterUniqueCodes(
  codes: readonly string[],
  allowed: ReadonlySet<string>,
): string[] {
  const result: string[] = []
  const seen = new Set<string>()
  for (const code of codes) {
    if (!allowed.has(code) || seen.has(code)) continue
    seen.add(code)
    result.push(code)
  }
  return result
}

export function reconcileAccessDraft(
  draft: ManagedUserAccessDraft,
  catalog: AccessCatalog,
): ReconciledAccessDraft {
  const allowedAccountTypes = codeSet(catalog.accountTypes)
  const allowedDepartments = codeSet(catalog.departments)
  const allowedRoles = codeSet(catalog.departmentRoles)
  const allowedPermissions = codeSet(catalog.directPermissions)
  const seenDepartments = new Set<string>()
  const departmentAccess: ManagedUserDepartmentAccessDraft[] = []

  for (const department of draft.departmentAccess) {
    if (
      !allowedDepartments.has(department.departmentCode) ||
      seenDepartments.has(department.departmentCode)
    ) {
      continue
    }
    seenDepartments.add(department.departmentCode)
    departmentAccess.push({
      departmentCode: department.departmentCode,
      isPrimary: department.isPrimary,
      roleCodes: filterUniqueCodes(department.roleCodes, allowedRoles),
    })
  }

  const reconciled: ManagedUserAccessDraft = {
    accountType:
      isAccountType(draft.accountType) &&
      allowedAccountTypes.has(draft.accountType)
        ? draft.accountType
        : '',
    departmentAccess,
    directPermissionCodes: filterUniqueCodes(
      draft.directPermissionCodes,
      allowedPermissions,
    ),
  }
  const changed = JSON.stringify(reconciled) !== JSON.stringify(draft)
  return {
    changed,
    draft: reconciled,
    requiresReconfirmation: changed,
  }
}

function hasDuplicates(values: readonly string[]): boolean {
  return new Set(values).size !== values.length
}

function validateAccessDraft(
  draft: ManagedUserAccessDraft,
  catalog: AccessCatalog,
): AccessDraftValidationErrors {
  const allowedAccountTypes = codeSet(catalog.accountTypes)
  if (
    !isAccountType(draft.accountType) ||
    !allowedAccountTypes.has(draft.accountType)
  ) {
    return { accountType: '请选择当前访问目录允许的账号类型。' }
  }

  const allowedDepartments = codeSet(catalog.departments)
  const allowedRoles = codeSet(catalog.departmentRoles)
  const departmentCodes = draft.departmentAccess.map(
    (department) => department.departmentCode,
  )
  const hasInvalidDepartment = draft.departmentAccess.some(
    (department) =>
      !allowedDepartments.has(department.departmentCode) ||
      department.roleCodes.some((code) => !allowedRoles.has(code)) ||
      hasDuplicates(department.roleCodes),
  )
  if (hasInvalidDepartment || hasDuplicates(departmentCodes)) {
    return { departmentAccess: '部门与角色必须来自当前访问目录。' }
  }
  if (
    draft.departmentAccess.filter((department) => department.isPrimary)
      .length !== 1
  ) {
    return { departmentAccess: '必须且只能选择一个主部门。' }
  }

  const allowedPermissions = codeSet(catalog.directPermissions)
  if (
    hasDuplicates(draft.directPermissionCodes) ||
    draft.directPermissionCodes.some(
      (code) => !allowedPermissions.has(code),
    )
  ) {
    return { directPermissionCodes: '直接权限必须来自当前访问目录。' }
  }
  return {}
}

export function buildReplaceManagedUserAccessRequest(
  draft: ManagedUserAccessDraft,
  catalog: AccessCatalog,
): AccessDraftBuildResult<ReplaceManagedUserAccessRequestDto> {
  const errors = validateAccessDraft(draft, catalog)
  if (Object.keys(errors).length > 0) return { errors, ok: false }

  return {
    ok: true,
    request: {
      account_type: draft.accountType as AccountType,
      department_access: draft.departmentAccess.map((department) => ({
        department_code: department.departmentCode,
        is_primary: department.isPrimary,
        role_codes: [...department.roleCodes],
      })),
      direct_permission_codes: [...draft.directPermissionCodes],
    },
  }
}

export function buildCreateManagedUserRequest(
  draft: CreateManagedUserDraft,
  catalog: AccessCatalog,
): AccessDraftBuildResult<CreateManagedUserRequestDto> {
  const access = buildReplaceManagedUserAccessRequest(draft.access, catalog)
  if (!access.ok) return access

  return {
    ok: true,
    request: {
      ...access.request,
      display_name: draft.displayName,
      email: draft.email,
      password: draft.password,
      username: draft.username,
    },
  }
}
