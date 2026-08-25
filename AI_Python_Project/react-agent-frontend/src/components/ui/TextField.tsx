import type { InputHTMLAttributes } from 'react'

import styles from '@/components/ui/TextField.module.css'

interface TextFieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, 'className' | 'id'> {
  error?: string
  id: string
  label: string
}

export function TextField({ error, id, label, ...inputProps }: TextFieldProps) {
  const errorId = `${id}-error`
  return (
    <div className={styles.field}>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <input
        {...inputProps}
        aria-describedby={error ? errorId : inputProps['aria-describedby']}
        aria-invalid={error ? 'true' : 'false'}
        className={styles.input}
        id={id}
      />
      {error ? (
        <p className={styles.error} id={errorId}>
          {error}
        </p>
      ) : null}
    </div>
  )
}
