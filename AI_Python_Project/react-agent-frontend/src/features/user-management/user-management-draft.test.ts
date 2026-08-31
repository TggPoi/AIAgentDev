import { describe, expect, it } from 'vitest'

import {
  buildCreateManagedUserRequest,
  buildReplaceManagedUserAccessRequest,
  reconcileAccessDraft,
  type ManagedUserAccessDraft,
} from '@/features/user-management/user-management-draft'
import type { AccessCatalog } from '@/features/user-management/user-management-models'


const catalog: AccessCatalog = {
  accountTypes: [
    { code: 'employee', description: null, name: '员工', riskLevel: null },
    {
      code: 'department_manager',
      description: null,
      name: '部门主管',
      riskLevel: 'high',
    },
  ],
  departmentRoles: [
    {
      code: 'department_reader',
      description: null,
      name: '部门读者',
      riskLevel: null,
    },
  ],
  departments: [
    {
      code: 'development',
      description: null,
      name: '研发部',
      riskLevel: null,
    },
    {
      code: 'operations',
      description: null,
      name: '运营部',
      riskLevel: null,
    },
  ],
  directPermissions: [
    {
      code: 'agent:tool:web_search',
      description: null,
      name: '联网搜索',
      riskLevel: 'medium',
    },
  ],
}

function validDraft(): ManagedUserAccessDraft {
  return {
    accountType: 'employee',
    departmentAccess: [
      {
        departmentCode: 'development',
        isPrimary: true,
        roleCodes: ['department_reader'],
      },
    ],
    directPermissionCodes: ['agent:tool:web_search'],
  }
}

describe('User Management catalog-backed draft policy', () => {
  it('removes catalog drift, duplicate codes and requires explicit reconfirmation', () => {
    const result = reconcileAccessDraft(
      {
        accountType: 'removed-account-type',
        departmentAccess: [
          {
            departmentCode: 'development',
            isPrimary: true,
            roleCodes: ['department_reader', 'removed-role', 'department_reader'],
          },
          {
            departmentCode: 'removed-department',
            isPrimary: false,
            roleCodes: ['department_reader'],
          },
          {
            departmentCode: 'development',
            isPrimary: false,
            roleCodes: [],
          },
        ],
        directPermissionCodes: [
          'agent:tool:web_search',
          'removed-permission',
          'agent:tool:web_search',
        ],
      },
      catalog,
    )

    expect(result).toEqual({
      changed: true,
      draft: {
        accountType: '',
        departmentAccess: [
          {
            departmentCode: 'development',
            isPrimary: true,
            roleCodes: ['department_reader'],
          },
        ],
        directPermissionCodes: ['agent:tool:web_search'],
      },
      requiresReconfirmation: true,
    })
  })

  it('leaves a current catalog-backed draft unchanged', () => {
    expect(reconcileAccessDraft(validDraft(), catalog)).toEqual({
      changed: false,
      draft: validDraft(),
      requiresReconfirmation: false,
    })
  })

  it.each([
    [
      { ...validDraft(), accountType: 'admin' },
      { accountType: '请选择当前访问目录允许的账号类型。' },
    ],
    [
      {
        ...validDraft(),
        departmentAccess: [
          {
            departmentCode: 'hidden-department',
            isPrimary: true,
            roleCodes: [],
          },
        ],
      },
      { departmentAccess: '部门与角色必须来自当前访问目录。' },
    ],
    [
      {
        ...validDraft(),
        departmentAccess: [
          {
            departmentCode: 'development',
            isPrimary: true,
            roleCodes: ['hidden-role'],
          },
        ],
      },
      { departmentAccess: '部门与角色必须来自当前访问目录。' },
    ],
    [
      { ...validDraft(), directPermissionCodes: ['hidden-permission'] },
      { directPermissionCodes: '直接权限必须来自当前访问目录。' },
    ],
  ])('rejects non-catalog submission values', (draft, expectedErrors) => {
    expect(buildReplaceManagedUserAccessRequest(draft, catalog)).toEqual({
      errors: expectedErrors,
      ok: false,
    })
  })

  it.each([
    [
      [
        {
          departmentCode: 'development',
          isPrimary: false,
          roleCodes: [],
        },
      ],
    ],
    [
      [
        {
          departmentCode: 'development',
          isPrimary: true,
          roleCodes: [],
        },
        {
          departmentCode: 'operations',
          isPrimary: true,
          roleCodes: [],
        },
      ],
    ],
  ])('requires exactly one primary department', (departmentAccess) => {
    expect(
      buildReplaceManagedUserAccessRequest(
        { ...validDraft(), departmentAccess },
        catalog,
      ),
    ).toEqual({
      errors: { departmentAccess: '必须且只能选择一个主部门。' },
      ok: false,
    })
  })

  it('builds complete access and create snapshots from generated DTO aliases', () => {
    expect(buildReplaceManagedUserAccessRequest(validDraft(), catalog)).toEqual({
      ok: true,
      request: {
        account_type: 'employee',
        department_access: [
          {
            department_code: 'development',
            is_primary: true,
            role_codes: ['department_reader'],
          },
        ],
        direct_permission_codes: ['agent:tool:web_search'],
      },
    })
    expect(
      buildCreateManagedUserRequest(
        {
          access: validDraft(),
          displayName: 'Reader',
          email: 'reader@example.com',
          password: 'form-local-password',
          username: 'reader',
        },
        catalog,
      ),
    ).toEqual({
      ok: true,
      request: {
        account_type: 'employee',
        department_access: [
          {
            department_code: 'development',
            is_primary: true,
            role_codes: ['department_reader'],
          },
        ],
        direct_permission_codes: ['agent:tool:web_search'],
        display_name: 'Reader',
        email: 'reader@example.com',
        password: 'form-local-password',
        username: 'reader',
      },
    })
  })
})
