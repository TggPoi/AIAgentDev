import { forwardRef, type ButtonHTMLAttributes } from 'react'

import styles from '@/components/ui/Button.module.css'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  iconOnly?: boolean
  variant?: 'ghost' | 'primary' | 'secondary'
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    { className, iconOnly = false, variant = 'primary', ...props },
    ref,
  ) {
    const classes = [
      styles.button,
      styles[variant],
      iconOnly ? styles.icon : '',
      className ?? '',
    ]
      .filter(Boolean)
      .join(' ')
    return <button ref={ref} className={classes} {...props} />
  },
)
