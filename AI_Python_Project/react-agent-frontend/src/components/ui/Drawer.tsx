import {
  type KeyboardEvent as ReactKeyboardEvent,
  type PropsWithChildren,
  useEffect,
  useRef,
} from 'react'

import { Button } from '@/components/ui/Button'
import styles from '@/components/ui/Drawer.module.css'

interface DrawerProps extends PropsWithChildren {
  label: string
  onClose: () => void
  open: boolean
}

export function Drawer({ children, label, onClose, open }: DrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!open) return
    closeButtonRef.current?.focus()
  }, [open])

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === 'Escape') {
      onClose()
      return
    }
    if (event.key !== 'Tab' || panelRef.current === null) return
    const focusable = Array.from(
      panelRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
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
    <>
      <button
        aria-hidden="true"
        className={styles.backdrop}
        onClick={onClose}
        tabIndex={-1}
        type="button"
      />
      <aside
        ref={panelRef}
        aria-label={label}
        aria-modal="true"
        className={styles.panel}
        onKeyDown={handleKeyDown}
        role="dialog"
      >
        <div className={styles.header}>
          <h2 className={styles.title}>{label}</h2>
          <Button
            ref={closeButtonRef}
            aria-label="关闭导航"
            iconOnly
            onClick={onClose}
            type="button"
            variant="ghost"
          >
            ×
          </Button>
        </div>
        {children}
      </aside>
    </>
  )
}
