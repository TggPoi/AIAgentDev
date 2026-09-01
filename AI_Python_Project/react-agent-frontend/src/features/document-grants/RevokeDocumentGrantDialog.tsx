import { ApiError } from '@/api/api-error'
import { Button } from '@/components/ui/Button'
import { Dialog } from '@/components/ui/Dialog'
import { ErrorState } from '@/components/ui/PageState'
import type { DocumentGrantApi } from '@/features/document-grants/document-grant-api'
import type { DocumentGrant } from '@/features/document-grants/document-grant-models'
import { useRevokeDocumentGrant } from '@/features/document-grants/document-grant-queries'
import styles from '@/features/document-grants/DocumentGrantWorkspace.module.css'


interface RevokeDocumentGrantDialogProps {
  api: DocumentGrantApi
  grant: DocumentGrant
  onClose: () => void
  userBoundary: string
}

export function RevokeDocumentGrantDialog({
  api,
  grant,
  onClose,
  userBoundary,
}: RevokeDocumentGrantDialogProps) {
  const mutation = useRevokeDocumentGrant(api, userBoundary)
  const close = () => {
    if (!mutation.isPending) onClose()
  }

  const revoke = async () => {
    try {
      await mutation.mutateAsync(grant.grantId)
      onClose()
    } catch {
      // The fixed safe ErrorState below owns public failure rendering.
    }
  }

  return (
    <Dialog label="撤销文档授权" onClose={close} open>
      <div className={styles.mutationForm}>
        <p>撤销后，目标账号将不再通过此授权读取该文档。</p>
        <dl className={styles.revokeFacts}>
          <div>
            <dt>文档</dt>
            <dd>{grant.repositoryPath}</dd>
          </div>
          <div>
            <dt>目标账号</dt>
            <dd>{grant.grantee.username}</dd>
          </div>
          <div>
            <dt>原授权人</dt>
            <dd>{grant.grantedByUserId}</dd>
          </div>
          <div>
            <dt>原授权时间</dt>
            <dd>{grant.grantedAt}</dd>
          </div>
        </dl>
        {mutation.isError ? (
          <ErrorState
            code={
              mutation.error instanceof ApiError
                ? mutation.error.code
                : undefined
            }
            message="撤销文档授权失败"
            requestId={
              mutation.error instanceof ApiError
                ? mutation.error.requestId
                : undefined
            }
          />
        ) : null}
        <div className={styles.actions}>
          <Button
            disabled={mutation.isPending}
            onClick={close}
            type="button"
            variant="secondary"
          >
            取消
          </Button>
          <Button
            disabled={mutation.isPending}
            onClick={() => void revoke()}
            type="button"
          >
            {mutation.isPending ? '正在撤销…' : '确认撤销授权'}
          </Button>
        </div>
      </div>
    </Dialog>
  )
}
