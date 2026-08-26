import {
  type KeyboardEvent as ReactKeyboardEvent,
  type PropsWithChildren,
  useEffect,
  useRef,
} from 'react'

import { Button } from '@/components/ui/Button'
import styles from '@/components/ui/Dialog.module.css'


interface DialogProps extends PropsWithChildren {
  label: string
  onClose: () => void
  open: boolean
}

export function Dialog({ children, label, onClose, open }: DialogProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const trigger =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null
    closeButtonRef.current?.focus()
    return () => trigger?.focus()
  }, [open])

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      onClose()
      return
    }
    if (event.key !== 'Tab' || panelRef.current === null) return
    const focusable = Array.from(
      panelRef.current.querySelectorAll<HTMLElement>(
        'button:not(:disabled), input:not(:disabled), [href], [tabindex]:not([tabindex="-1"])',
      ),
    )
    const first = focusable.at(0)
    const last = focusable.at(-1)
    if (first === undefined || last === undefined) return
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  if (!open) return null

  return (
    <div className={styles.layer}>
      <button
        aria-hidden="true"
        className={styles.backdrop}
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <div
        ref={panelRef}
        aria-label={label}
        aria-modal="true"
        className={styles.panel}
        onKeyDown={handleKeyDown}
        role="dialog"
      >
        <header className={styles.header}>
          <h2>{label}</h2>
          <Button
            ref={closeButtonRef}
            aria-label={`关闭${label}`}
            iconOnly
            onClick={onClose}
            type="button"
            variant="ghost"
          >
            ×
          </Button>
        </header>
        {children}
      </div>
    </div>
  )
}
