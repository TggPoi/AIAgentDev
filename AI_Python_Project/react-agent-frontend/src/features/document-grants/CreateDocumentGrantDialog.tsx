import { useState } from 'react'

import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorState, PageSkeleton } from '@/components/ui/PageState'
import { TextField } from '@/components/ui/TextField'
import type { DocumentGrantApi } from '@/features/document-grants/document-grant-api'
import {
  buildCreateDocumentGrantsRequest,
  type CreateDocumentGrantDraftErrors,
} from '@/features/document-grants/document-grant-draft'
import {
  mergeGrantableDocumentPages,
  type CreateDocumentGrantsResult,
  type GrantableDocument,
} from '@/features/document-grants/document-grant-models'
import {
  useCreateDocumentGrants,
  useGrantableDocumentList,
} from '@/features/document-grants/document-grant-queries'
import styles from '@/features/document-grants/DocumentGrantWorkspace.module.css'


interface CreateDocumentGrantDialogProps {
  api: DocumentGrantApi
  canFilterDepartment: boolean
  onClose: () => void
  onCreated: (result: CreateDocumentGrantsResult) => void
  userBoundary: string
}

interface GrantableCatalogFieldErrors {
  departmentCode?: string
  query?: string
}

function serverFieldErrors(error: unknown): CreateDocumentGrantDraftErrors {
  if (!(error instanceof ApiError)) return {}
  const errors: CreateDocumentGrantDraftErrors = {}
  for (const item of error.fieldErrors) {
    if (item.field === 'target_account') errors.targetAccount = item.message
    else if (item.field === 'document_ids') errors.documentIds = item.message
  }
  return errors
}

function catalogFieldErrors(error: unknown): GrantableCatalogFieldErrors {
  if (!(error instanceof ApiError)) return {}
  const errors: GrantableCatalogFieldErrors = {}
  for (const item of error.fieldErrors) {
    if (item.field === 'query') errors.query = item.message
    else if (item.field === 'department_code') {
      errors.departmentCode = item.message
    }
  }
  return errors
}

export function CreateDocumentGrantDialog({
  api,
  canFilterDepartment,
  onClose,
  onCreated,
  userBoundary,
}: CreateDocumentGrantDialogProps) {
  const [targetAccount, setTargetAccount] = useState('')
  const [query, setQuery] = useState('')
  const [departmentCode, setDepartmentCode] = useState('')
  const [selectedDocuments, setSelectedDocuments] = useState<
    GrantableDocument[]
  >([])
  const [localErrors, setLocalErrors] =
    useState<CreateDocumentGrantDraftErrors>({})
  const [reviewing, setReviewing] = useState(false)
  const catalogQuery = useGrantableDocumentList(api, userBoundary, {
    departmentCode:
      canFilterDepartment && departmentCode.trim()
        ? departmentCode.trim()
        : null,
    query: query.trim() || null,
  })
  const mutation = useCreateDocumentGrants(api, userBoundary)
  const catalogItems = mergeGrantableDocumentPages(catalogQuery.data?.pages ?? [])
  const errors = { ...localErrors, ...serverFieldErrors(mutation.error) }
  const hasServerFieldError =
    Object.keys(serverFieldErrors(mutation.error)).length > 0
  const catalogErrors = catalogFieldErrors(catalogQuery.error)
  const hasCatalogFieldError = Object.keys(catalogErrors).length > 0
  const close = () => {
    if (!mutation.isPending) onClose()
  }

  const edit = () => {
    setReviewing(false)
    setLocalErrors({})
    mutation.reset()
  }

  const toggleDocument = (document: GrantableDocument) => {
    setSelectedDocuments((current) =>
      current.some((item) => item.documentId === document.documentId)
        ? current.filter((item) => item.documentId !== document.documentId)
        : [...current, document],
    )
    setReviewing(false)
    setLocalErrors({})
    mutation.reset()
  }

  const review = () => {
    mutation.reset()
    const result = buildCreateDocumentGrantsRequest({
      selectedDocuments,
      targetAccount,
    })
    if (!result.ok) {
      setLocalErrors(result.errors)
      return
    }
    setTargetAccount(result.request.target_account)
    setLocalErrors({})
    setReviewing(true)
  }

  const submit = async () => {
    const result = buildCreateDocumentGrantsRequest({
      selectedDocuments,
      targetAccount,
    })
    if (!result.ok) {
      setReviewing(false)
      setLocalErrors(result.errors)
      return
    }
    try {
      const created = await mutation.mutateAsync(result.request)
      onCreated(created)
      onClose()
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        setReviewing(false)
      }
    }
  }

  return (
    <Dialog label="创建文档授权" onClose={close} open>
      <form
        className={styles.mutationForm}
        noValidate
        onSubmit={(event) => {
          event.preventDefault()
          if (reviewing) void submit()
          else review()
        }}
      >
        {reviewing ? (
          <div className={styles.review}>
            <h3>确认授权清单</h3>
            <p>目标账号：{targetAccount}</p>
            <ul aria-label="待授权文档">
              {selectedDocuments.map((document) => (
                <li key={document.documentId}>
                  <strong>{document.title}</strong>
                  <span>{document.repositoryPath}</span>
                </li>
              ))}
            </ul>
            <div className={styles.actions}>
              <Button
                disabled={mutation.isPending}
                onClick={edit}
                type="button"
                variant="secondary"
              >
                返回修改
              </Button>
              <Button disabled={mutation.isPending} type="submit">
                {mutation.isPending ? '正在创建…' : '确认创建授权'}
              </Button>
            </div>
          </div>
        ) : (
          <>
            <TextField
              autoComplete="off"
              disabled={mutation.isPending}
              error={errors.targetAccount}
              id="document-grant-create-target-account"
              label="精确目标账号"
              onChange={(event) => {
                setTargetAccount(event.currentTarget.value)
                setLocalErrors({})
                mutation.reset()
              }}
              value={targetAccount}
            />
            <div className={styles.dialogFilters}>
              <TextField
                disabled={mutation.isPending}
                error={catalogErrors.query}
                id="document-grant-create-query"
                label="筛选可授权文档"
                onChange={(event) => setQuery(event.currentTarget.value)}
                value={query}
              />
              {canFilterDepartment ? (
                <TextField
                  disabled={mutation.isPending}
                  error={catalogErrors.departmentCode}
                  id="document-grant-create-department"
                  label="筛选文档部门"
                  onChange={(event) =>
                    setDepartmentCode(event.currentTarget.value)
                  }
                  value={departmentCode}
                />
              ) : null}
            </div>
            {catalogQuery.isPending ? <PageSkeleton /> : null}
            {catalogQuery.isError && !hasCatalogFieldError ? (
              <ErrorState
                code={
                  catalogQuery.error instanceof ApiError
                    ? catalogQuery.error.code
                    : undefined
                }
                message="可授权文档加载失败"
                requestId={
                  catalogQuery.error instanceof ApiError
                    ? catalogQuery.error.requestId
                    : undefined
                }
              />
            ) : null}
            {catalogItems.length > 0 ? (
              <ul aria-label="可授权文档" className={styles.candidateList}>
                {catalogItems.map((document) => {
                  const selected = selectedDocuments.some(
                    (item) => item.documentId === document.documentId,
                  )
                  return (
                    <li key={document.documentId}>
                      <label className={styles.candidate}>
                        <input
                          checked={selected}
                          disabled={
                            mutation.isPending ||
                            (!selected && selectedDocuments.length >= 100)
                          }
                          onChange={() => toggleDocument(document)}
                          type="checkbox"
                        />
                        <span>
                          <strong>{document.title}</strong>
                          <small>
                            {document.repositoryPath} ·{' '}
                            {document.documentDepartmentCode}
                          </small>
                        </span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            ) : null}
            {catalogQuery.hasNextPage ? (
              <Button
                disabled={catalogQuery.isFetchingNextPage}
                onClick={() => void catalogQuery.fetchNextPage()}
                type="button"
                variant="secondary"
              >
                {catalogQuery.isFetchingNextPage
                  ? '正在加载…'
                  : '加载更多可授权文档'}
              </Button>
            ) : null}
            {errors.documentIds ? (
              <p className={styles.fieldError} role="alert">
                {errors.documentIds}
              </p>
            ) : null}
            <Button disabled={mutation.isPending} type="submit">
              审查授权
            </Button>
          </>
        )}
        {mutation.isError && !hasServerFieldError ? (
          <ErrorState
            code={
              mutation.error instanceof ApiError
                ? mutation.error.code
                : undefined
            }
            message="创建文档授权失败"
            requestId={
              mutation.error instanceof ApiError
                ? mutation.error.requestId
                : undefined
            }
          />
        ) : null}
      </form>
    </Dialog>
  )
}
