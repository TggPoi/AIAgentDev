import type { AccessDraftValidationErrors, ManagedUserAccessDraft } from '@/features/user-management/user-management-draft'
import type { AccessCatalog } from '@/features/user-management/user-management-models'
import styles from '@/features/user-management/UserManagementWorkspace.module.css'


interface ManagedUserAccessFieldsProps {
  catalog: AccessCatalog
  disabled: boolean
  draft: ManagedUserAccessDraft
  errors: AccessDraftValidationErrors
  onChange: (draft: ManagedUserAccessDraft) => void
}

export function ManagedUserAccessFields({
  catalog,
  disabled,
  draft,
  errors,
  onChange,
}: ManagedUserAccessFieldsProps) {
  const departmentDraft = (departmentCode: string) =>
    draft.departmentAccess.find(
      (department) => department.departmentCode === departmentCode,
    )

  const toggleDepartment = (departmentCode: string, selected: boolean) => {
    if (selected) {
      onChange({
        ...draft,
        departmentAccess: [
          ...draft.departmentAccess,
          {
            departmentCode,
            isPrimary: draft.departmentAccess.length === 0,
            roleCodes: [],
          },
        ],
      })
      return
    }
    const nextDepartments = draft.departmentAccess.filter(
      (department) => department.departmentCode !== departmentCode,
    )
    if (
      nextDepartments.length > 0 &&
      !nextDepartments.some((department) => department.isPrimary)
    ) {
      nextDepartments[0] = { ...nextDepartments[0], isPrimary: true }
    }
    onChange({ ...draft, departmentAccess: nextDepartments })
  }

  const toggleRole = (
    departmentCode: string,
    roleCode: string,
    selected: boolean,
  ) => {
    onChange({
      ...draft,
      departmentAccess: draft.departmentAccess.map((department) =>
        department.departmentCode === departmentCode
          ? {
              ...department,
              roleCodes: selected
                ? [...department.roleCodes, roleCode]
                : department.roleCodes.filter((code) => code !== roleCode),
            }
          : department,
      ),
    })
  }

  const toggleDirectPermission = (code: string, selected: boolean) => {
    onChange({
      ...draft,
      directPermissionCodes: selected
        ? [...draft.directPermissionCodes, code]
        : draft.directPermissionCodes.filter((item) => item !== code),
    })
  }

  return (
    <div className={styles.accessFields}>
      <label className={styles.selectField}>
        账号类型
        <select
          aria-invalid={errors.accountType ? 'true' : 'false'}
          disabled={disabled}
          onChange={(event) =>
            onChange({ ...draft, accountType: event.currentTarget.value })
          }
          value={draft.accountType}
        >
          <option value="">请选择账号类型</option>
          {catalog.accountTypes.map((accountType) => (
            <option key={accountType.code} value={accountType.code}>
              {accountType.name}
            </option>
          ))}
        </select>
        {errors.accountType ? (
          <span className={styles.fieldError}>{errors.accountType}</span>
        ) : null}
      </label>

      <fieldset className={styles.choiceGroup} disabled={disabled}>
        <legend>部门与部门角色</legend>
        {catalog.departments.map((department) => {
          const selected = departmentDraft(department.code)
          return (
            <div className={styles.departmentChoice} key={department.code}>
              <label>
                <input
                  checked={selected !== undefined}
                  onChange={(event) =>
                    toggleDepartment(department.code, event.currentTarget.checked)
                  }
                  type="checkbox"
                />
                选择部门 {department.name}
              </label>
              {selected ? (
                <div className={styles.nestedChoices}>
                  <label>
                    <input
                      checked={selected.isPrimary}
                      name="managed-user-primary-department"
                      onChange={() =>
                        onChange({
                          ...draft,
                          departmentAccess: draft.departmentAccess.map(
                            (item) => ({
                              ...item,
                              isPrimary:
                                item.departmentCode === department.code,
                            }),
                          ),
                        })
                      }
                      type="radio"
                    />
                    设为主部门 {department.name}
                  </label>
                  {catalog.departmentRoles.map((role) => (
                    <label key={role.code}>
                      <input
                        checked={selected.roleCodes.includes(role.code)}
                        onChange={(event) =>
                          toggleRole(
                            department.code,
                            role.code,
                            event.currentTarget.checked,
                          )
                        }
                        type="checkbox"
                      />
                      {department.name}：{role.name}
                    </label>
                  ))}
                </div>
              ) : null}
            </div>
          )
        })}
        {errors.departmentAccess ? (
          <span className={styles.fieldError}>{errors.departmentAccess}</span>
        ) : null}
      </fieldset>

      <fieldset className={styles.choiceGroup} disabled={disabled}>
        <legend>直接权限</legend>
        {catalog.directPermissions.length === 0 ? (
          <p className={styles.muted}>当前身份没有可下放的直接权限。</p>
        ) : null}
        {catalog.directPermissions.map((permission) => (
          <label key={permission.code}>
            <input
              aria-label={`直接权限 ${permission.name}`}
              checked={draft.directPermissionCodes.includes(permission.code)}
              onChange={(event) =>
                toggleDirectPermission(
                  permission.code,
                  event.currentTarget.checked,
                )
              }
              type="checkbox"
            />
            直接权限 {permission.name}
            {permission.riskLevel ? `（风险：${permission.riskLevel}）` : ''}
          </label>
        ))}
        {errors.directPermissionCodes ? (
          <span className={styles.fieldError}>
            {errors.directPermissionCodes}
          </span>
        ) : null}
      </fieldset>
    </div>
  )
}
